"""Icon detection in diagram images using Grounding DINO.

This script supports two usage modes:
1. CLI invocation for one image.
2. Importable functions for workflow integration.

Prompt 2 adds a project-level artifact contract:
- <project>/icon_detection/overlays/
- <project>/icon_detection/crops/
- <project>/icon_detection/metadata/

Prompt 3 adds project-level batch execution.

Prompt 4 adds:
- two-pass detection strategy
- post-detection quality filtering and deduplication
- split metadata outputs: raw detections vs usable icons
"""

import argparse
import json
import os
import shutil
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont
import torch
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor


warnings.filterwarnings(
    "ignore",
    message=r".*The key `labels` is will return integer ids.*",
)

DEFAULT_MODEL_ID = "IDEA-Research/grounding-dino-base"
DEFAULT_TEXT_PROMPT = "logo. icon."
DEFAULT_SECOND_PASS_TEXT_PROMPT = (
    "architecture icon. cloud icon. server icon. database icon. "
    "flowchart symbol. process icon. chart icon. brand logo. app logo. company logo."
)
DEFAULT_BOX_THRESHOLD = 0.05
DEFAULT_TEXT_THRESHOLD = 0.05

DEFAULT_MIN_RAW_FOR_SECOND_PASS = 8
DEFAULT_USABLE_MIN_CONFIDENCE = 0.07
DEFAULT_USABLE_MIN_WIDTH = 14
DEFAULT_USABLE_MIN_HEIGHT = 14
DEFAULT_USABLE_MIN_ASPECT = 0.20
DEFAULT_USABLE_MAX_ASPECT = 5.00
DEFAULT_DEDUPE_IOU_THRESHOLD = 0.60

ICON_DETECTION_DIRNAME = "icon_detection"
ICON_OVERLAYS_DIRNAME = "overlays"
ICON_CROPS_DIRNAME = "crops"
ICON_METADATA_DIRNAME = "metadata"

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
FILENAME_HINTS = (
    "diagram",
    "arch",
    "architecture",
    "logo",
    "icon",
    "flow",
    "system",
    "framework",
    "process",
    "infra",
    "network",
    "topology",
    "screenshot",
    "ui",
    "ux",
)

COLORS = [
    (255, 0, 0),
    (0, 200, 0),
    (0, 0, 255),
    (255, 165, 0),
    (128, 0, 128),
    (0, 200, 200),
    (255, 20, 147),
    (0, 128, 0),
]


@dataclass
class FilterConfig:
    min_confidence: float = DEFAULT_USABLE_MIN_CONFIDENCE
    min_width: int = DEFAULT_USABLE_MIN_WIDTH
    min_height: int = DEFAULT_USABLE_MIN_HEIGHT
    min_aspect: float = DEFAULT_USABLE_MIN_ASPECT
    max_aspect: float = DEFAULT_USABLE_MAX_ASPECT
    dedupe_iou_threshold: float = DEFAULT_DEDUPE_IOU_THRESHOLD


def _safe_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0].strip()
    return stem or "image"


def _is_image_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def _clamp_box(x0f: float, y0f: float, x1f: float, y1f: float, width: int, height: int) -> Tuple[int, int, int, int]:
    x0 = max(0, min(width, int(x0f)))
    y0 = max(0, min(height, int(y0f)))
    x1 = max(0, min(width, int(x1f)))
    y1 = max(0, min(height, int(y1f)))
    return x0, y0, x1, y1


def _box_iou(a: Sequence[int], b: Sequence[int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b

    inter_x0 = max(ax0, bx0)
    inter_y0 = max(ay0, by0)
    inter_x1 = min(ax1, bx1)
    inter_y1 = min(ay1, by1)

    inter_w = max(0, inter_x1 - inter_x0)
    inter_h = max(0, inter_y1 - inter_y0)
    inter_area = inter_w * inter_h

    if inter_area == 0:
        return 0.0

    a_area = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    b_area = max(0, bx1 - bx0) * max(0, by1 - by0)
    union = a_area + b_area - inter_area
    if union <= 0:
        return 0.0

    return inter_area / union


def get_icon_detection_layout(project_path: str) -> Dict[str, str]:
    """Return canonical icon-detection directories for a project."""
    root = os.path.join(project_path, ICON_DETECTION_DIRNAME)
    return {
        "root": root,
        "overlays": os.path.join(root, ICON_OVERLAYS_DIRNAME),
        "crops": os.path.join(root, ICON_CROPS_DIRNAME),
        "metadata": os.path.join(root, ICON_METADATA_DIRNAME),
    }


def ensure_icon_detection_dirs(project_path: str) -> Dict[str, str]:
    """Create and return canonical icon-detection directories for a project."""
    layout = get_icon_detection_layout(project_path)
    for value in layout.values():
        os.makedirs(value, exist_ok=True)
    return layout


def resolve_output_paths(
    image_path: str,
    output_path: Optional[str],
    crops_dir: Optional[str],
    metadata_json: Optional[str],
    raw_metadata_json: Optional[str],
    usable_metadata_json: Optional[str],
    project_path: Optional[str],
) -> Dict[str, str]:
    """Resolve output paths with Prompt 4 split metadata defaults."""
    image_stem = _safe_stem(image_path)

    if metadata_json and usable_metadata_json is None:
        usable_metadata_json = metadata_json

    if project_path:
        layout = ensure_icon_detection_dirs(project_path)
        if output_path is None:
            output_path = os.path.join(layout["overlays"], f"{image_stem}_detected.png")
        if crops_dir is None:
            crops_dir = os.path.join(layout["crops"], image_stem)
        if raw_metadata_json is None:
            raw_metadata_json = os.path.join(layout["metadata"], f"{image_stem}.raw_detections.json")
        if usable_metadata_json is None:
            usable_metadata_json = os.path.join(layout["metadata"], f"{image_stem}.usable_icons.json")
    else:
        if output_path is None:
            base, _ = os.path.splitext(image_path)
            output_path = f"{base}_detected.png"
        if crops_dir is None:
            crops_dir = "crops"
        if raw_metadata_json is None:
            raw_metadata_json = os.path.join(crops_dir, "raw_detections.json")
        if usable_metadata_json is None:
            usable_metadata_json = os.path.join(crops_dir, "usable_icons.json")

    return {
        "output": output_path,
        "crops_dir": crops_dir,
        "raw_metadata_json": raw_metadata_json,
        "usable_metadata_json": usable_metadata_json,
    }


def resolve_review_report_path(
    image_path: Optional[str],
    project_path: Optional[str],
    usable_metadata_json: Optional[str],
    review_report_md: Optional[str],
    batch_mode: bool,
) -> str:
    """Resolve markdown review-report path for single-image or project batch mode."""
    if review_report_md:
        return review_report_md

    if project_path:
        layout = ensure_icon_detection_dirs(project_path)
        if batch_mode:
            return os.path.join(layout["root"], "review.md")

    if image_path and usable_metadata_json:
        image_stem = _safe_stem(image_path)
        return os.path.join(os.path.dirname(usable_metadata_json), f"{image_stem}.review.md")

    if project_path:
        layout = ensure_icon_detection_dirs(project_path)
        return os.path.join(layout["root"], "review.md")

    return "icon_detection_review.md"


def list_project_images(project_path: str, images_subdir: str = "images") -> List[str]:
    """List image files under project/images recursively."""
    images_root = os.path.join(project_path, images_subdir)
    if not os.path.isdir(images_root):
        raise FileNotFoundError(f"Images directory not found: {images_root}")

    image_paths: List[str] = []
    for root, _, files in os.walk(images_root):
        for filename in files:
            abs_path = os.path.join(root, filename)
            if _is_image_file(abs_path):
                image_paths.append(abs_path)

    image_paths.sort()
    return image_paths


def classify_candidate_image(image_path: str, hints: Sequence[str]) -> Tuple[bool, str]:
    """Classify image as candidate based on filename hints."""
    name = os.path.basename(image_path).lower()
    for hint in hints:
        token = hint.strip().lower()
        if token and token in name:
            return True, f"filename_hint:{token}"

    return False, "no_hint_match"


def select_candidate_images(
    image_paths: Sequence[str],
    process_all_images: bool = False,
    hints: Sequence[str] = FILENAME_HINTS,
) -> Tuple[List[str], Dict[str, str], bool]:
    """Select images to process and return candidate list and reasons."""
    reason_by_image: Dict[str, str] = {}

    if process_all_images:
        for image_path in image_paths:
            reason_by_image[image_path] = "process_all_images"
        return list(image_paths), reason_by_image, False

    candidates: List[str] = []
    for image_path in image_paths:
        is_candidate, reason = classify_candidate_image(image_path, hints)
        reason_by_image[image_path] = reason
        if is_candidate:
            candidates.append(image_path)

    used_fallback_all = False
    if not candidates and image_paths:
        used_fallback_all = True
        candidates = list(image_paths)
        for image_path in image_paths:
            reason_by_image[image_path] = "fallback_all_images"

    return candidates, reason_by_image, used_fallback_all


def load_model(model_id: str = DEFAULT_MODEL_ID):
    """Load Grounding DINO model and processor from Hugging Face."""
    print(f"Loading model: {model_id}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)
    model.eval()
    return processor, model, device


def detect_objects(
    image: Image.Image,
    text_prompt: str,
    processor,
    model,
    device: str,
    box_threshold: float,
    text_threshold: float,
) -> Dict[str, Any]:
    """Run Grounding DINO inference on one image."""
    inputs = processor(images=image, text=text_prompt, return_tensors="pt").to(device)

    with torch.no_grad():
        outputs = model(**inputs)

    try:
        results = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            target_sizes=[image.size[::-1]],
        )
    except TypeError:
        results = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=box_threshold,
            text_threshold=text_threshold,
            target_sizes=[image.size[::-1]],
        )

    return results[0]


def get_detection_labels(detections: Dict[str, Any]) -> List[str]:
    """Normalize detection labels across transformers versions."""
    if "text_labels" in detections:
        values = detections["text_labels"]
        return [str(value) for value in values]

    values = detections.get("labels", [])
    if hasattr(values, "cpu"):
        values = values.cpu().numpy()
    return [str(value) for value in values]


def detections_to_raw_entries(
    detections: Dict[str, Any],
    image_size: Tuple[int, int],
    source_image: str,
    source_image_rel: str,
    pass_name: str,
    prompt_used: str,
) -> List[Dict[str, Any]]:
    """Convert model detections into normalized raw detection records."""
    width, height = image_size
    boxes = detections["boxes"].cpu().tolist()
    scores = detections["scores"].cpu().tolist()
    labels = get_detection_labels(detections)

    entries: List[Dict[str, Any]] = []
    for index, box in enumerate(boxes, start=1):
        x0f, y0f, x1f, y1f = box
        x0, y0, x1, y1 = _clamp_box(x0f, y0f, x1f, y1f, width, height)
        crop_width = max(0, x1 - x0)
        crop_height = max(0, y1 - y0)
        aspect_ratio = float(crop_width / crop_height) if crop_height > 0 else 0.0

        entries.append(
            {
                "raw_id": f"{pass_name}_{index}",
                "pass_name": pass_name,
                "prompt_used": prompt_used,
                "source_image": source_image,
                "source_image_rel": source_image_rel,
                "bbox_xyxy": [x0, y0, x1, y1],
                "confidence": float(scores[index - 1]),
                "label": labels[index - 1] if index - 1 < len(labels) else "unknown",
                "crop_width": crop_width,
                "crop_height": crop_height,
                "aspect_ratio": aspect_ratio,
                "quality_flags": [],
                "drop_reason": None,
                "duplicate_of": None,
            }
        )

    return entries


def filter_and_dedupe_raw_entries(raw_entries: List[Dict[str, Any]], config: FilterConfig) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter detections by quality constraints and dedupe by IoU overlap."""
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for entry in raw_entries:
        reasons: List[str] = []
        x0, y0, x1, y1 = entry["bbox_xyxy"]
        width = x1 - x0
        height = y1 - y0
        aspect = float(width / height) if height > 0 else 0.0

        if width <= 0 or height <= 0:
            reasons.append("invalid_box")
        if width < config.min_width:
            reasons.append("below_min_width")
        if height < config.min_height:
            reasons.append("below_min_height")
        if entry["confidence"] < config.min_confidence:
            reasons.append("below_min_confidence")
        if height <= 0 or aspect < config.min_aspect or aspect > config.max_aspect:
            reasons.append("aspect_out_of_range")

        if reasons:
            new_entry = dict(entry)
            new_entry["quality_flags"] = reasons
            new_entry["drop_reason"] = "quality_filter"
            rejected.append(new_entry)
        else:
            candidates.append(dict(entry))

    candidates.sort(key=lambda item: float(item["confidence"]), reverse=True)

    usable: List[Dict[str, Any]] = []
    for entry in candidates:
        duplicate = None
        for kept in usable:
            iou = _box_iou(entry["bbox_xyxy"], kept["bbox_xyxy"])
            if iou >= config.dedupe_iou_threshold:
                duplicate = kept
                break

        if duplicate is not None:
            new_entry = dict(entry)
            new_entry["quality_flags"] = list(new_entry.get("quality_flags", [])) + ["duplicate_iou"]
            new_entry["drop_reason"] = "duplicate"
            new_entry["duplicate_of"] = duplicate.get("raw_id")
            rejected.append(new_entry)
            continue

        usable.append(entry)

    for idx, entry in enumerate(usable, start=1):
        entry["usable_id"] = idx

    return usable, rejected


def export_usable_crops(
    image: Image.Image,
    usable_entries: List[Dict[str, Any]],
    crops_dir: str,
) -> List[Dict[str, Any]]:
    """Export usable icon crops and return metadata with crop paths."""
    if os.path.isdir(crops_dir):
        shutil.rmtree(crops_dir)
    os.makedirs(crops_dir, exist_ok=True)

    records: List[Dict[str, Any]] = []
    for entry in usable_entries:
        x0, y0, x1, y1 = entry["bbox_xyxy"]
        crop = image.crop((x0, y0, x1, y1))
        crop_filename = f"icon_{entry['usable_id']:03d}.png"
        crop_path_abs = os.path.join(crops_dir, crop_filename)
        crop.save(crop_path_abs)

        crop_path_rel = os.path.relpath(crop_path_abs, start=os.getcwd())
        record = dict(entry)
        record["crop_path"] = crop_path_rel
        records.append(record)

    return records


def draw_detections_from_entries(image: Image.Image, entries: Sequence[Dict[str, Any]], line_width: int = 3) -> Image.Image:
    """Draw raw detection boxes and labels on image copy."""
    draw_image = image.copy().convert("RGB")
    draw = ImageDraw.Draw(draw_image)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for idx, entry in enumerate(entries):
        x0, y0, x1, y1 = entry["bbox_xyxy"]
        color = COLORS[idx % len(COLORS)]
        draw.rectangle([x0, y0, x1, y1], outline=color, width=line_width)

        label = entry.get("label", "unknown")
        confidence = float(entry.get("confidence", 0.0))
        pass_name = entry.get("pass_name", "pass")
        text = f"{label} {confidence:.2f} ({pass_name})"

        bbox_text = draw.textbbox((x0, y0), text, font=font)
        text_w = bbox_text[2] - bbox_text[0]
        text_h = bbox_text[3] - bbox_text[1]
        draw.rectangle([x0, max(0, y0 - text_h - 4), x0 + text_w + 4, y0], fill=color)
        draw.text((x0 + 2, max(0, y0 - text_h - 2)), text, fill="white", font=font)

    return draw_image


def _source_rel(image_path: str, project_path: Optional[str]) -> str:
    if not project_path:
        return image_path
    try:
        return os.path.relpath(image_path, start=project_path)
    except ValueError:
        return image_path


def build_single_image_review_report(
    *,
    image_path: str,
    source_image_rel: str,
    output_path: str,
    raw_metadata_json: str,
    usable_metadata_json: str,
    crops_dir: str,
    num_raw_detections: int,
    num_usable_icons: int,
    num_rejected_icons: int,
    second_pass_used: bool,
    pass1_count: int,
    pass2_count: int,
) -> str:
    """Build a markdown review report for a single processed image."""
    automated_checks = [
        ("Overlay preview generated", os.path.exists(output_path)),
        ("Raw detections JSON generated", os.path.exists(raw_metadata_json)),
        ("Usable icons JSON generated", os.path.exists(usable_metadata_json)),
        ("At least one usable icon produced", num_usable_icons > 0),
    ]

    lines = [
        "# Icon Detection Review Report",
        "",
        f"- Source image: `{source_image_rel}`",
        f"- Overlay preview: `{output_path}`",
        f"- Raw detections JSON: `{raw_metadata_json}`",
        f"- Usable icons JSON: `{usable_metadata_json}`",
        f"- Crops directory: `{crops_dir}`",
        "",
        "## Detection Summary",
        "",
        f"- Raw detections: {num_raw_detections}",
        f"- Usable icons: {num_usable_icons}",
        f"- Rejected icons: {num_rejected_icons}",
        f"- Second pass used: {'yes' if second_pass_used else 'no'}",
        f"- Pass 1 count: {pass1_count}",
        f"- Pass 2 count: {pass2_count}",
        "",
        "## Automated Checks",
        "",
    ]

    for label, ok in automated_checks:
        lines.append(f"- [{'x' if ok else ' '}] {label}")

    lines.extend(
        [
            "",
            "## Manual Acceptance Checklist",
            "",
            "- [ ] Open the overlay preview and confirm the boxes correspond to real reusable icons.",
            "- [ ] Open the usable icon crops and confirm they remain legible at target slide size.",
            "- [ ] Reject crops that mostly contain text fragments, chart marks, or decorative shapes.",
            "- [ ] Confirm any source-specific icons that matter for fidelity are candidates for Design Spec section VI.",
            "- [ ] Confirm every extracted candidate has a practical fallback: built-in icon, redraw, or omit.",
            "",
            "## Acceptance Guidance",
            "",
            "Accept this image for Strategist / Executor handoff only after the automated checks pass and the manual checklist is reviewed.",
        ]
    )

    return "\n".join(lines) + "\n"


def build_project_review_report(summary: Dict[str, Any]) -> str:
    """Build a markdown review report for a project batch run."""
    lines = [
        "# Icon Detection Batch Review",
        "",
        f"- Project path: `{summary['project_path']}`",
        f"- Summary JSON: `{summary['summary_json']}`",
        f"- Total images: {summary['total_images']}",
        f"- Candidate images: {summary['candidate_images']}",
        f"- Processed images: {summary['processed_images']}",
        f"- Raw detections: {summary['total_raw_detections']}",
        f"- Usable icons: {summary['usable_icons']}",
        f"- Rejected icons: {summary['rejected_icons']}",
        f"- Second-pass used images: {summary['second_pass_used_images']}",
        "",
        "## Per-Image Review Queue",
        "",
        "| Image | Selection Reason | Raw | Usable | Rejected | Second Pass | Usable Metadata |",
        "| ----- | ---------------- | --- | ------ | -------- | ----------- | --------------- |",
    ]

    for item in summary.get("images", []):
        lines.append(
            "| {image} | {reason} | {raw} | {usable} | {rejected} | {second_pass} | `{usable_json}` |".format(
                image=item["source_image_rel"],
                reason=item["selection_reason"],
                raw=item["raw_detections"],
                usable=item["usable_icons"],
                rejected=item["rejected_icons"],
                second_pass="yes" if item["second_pass_used"] else "no",
                usable_json=item["usable_metadata_json"],
            )
        )

    lines.extend(
        [
            "",
            "## Automated Acceptance Checks",
            "",
            f"- [{'x' if summary['processed_images'] > 0 else ' '}] At least one image was processed",
            f"- [{'x' if summary['total_raw_detections'] >= summary['usable_icons'] else ' '}] Raw detection count is consistent with usable count",
            f"- [{'x' if summary['usable_icons'] > 0 else ' '}] At least one usable icon exists in the batch",
            f"- [{'x' if os.path.exists(summary['summary_json']) else ' '}] Summary JSON was written",
            "",
            "## Manual Batch Checklist",
            "",
            "- [ ] Review overlay previews for every processed image.",
            "- [ ] Spot-check `*.usable_icons.json` entries for false positives and weak crops.",
            "- [ ] Confirm only fidelity-critical extracted icons will be proposed to Strategist section VI.",
            "- [ ] Confirm low-quality or generic icons have fallback recommendations before Executor use.",
            "- [ ] Confirm images with zero usable icons are acceptable to skip or should be re-run with different thresholds.",
            "",
            "## Acceptance Gate",
            "",
            "Do not treat the batch as ready for design-spec handoff until the manual checklist is reviewed alongside the automated checks above.",
        ]
    )

    if summary.get("skipped"):
        lines.extend(["", "## Skipped Images", ""])
        for item in summary["skipped"]:
            lines.append(f"- `{item['source_image_rel']}` — {item['reason']}")

    return "\n".join(lines) + "\n"


def _run_two_pass_detection(
    image: Image.Image,
    source_image: str,
    source_image_rel: str,
    text_prompt: str,
    second_pass_text_prompt: str,
    enable_second_pass: bool,
    min_raw_for_second_pass: int,
    box_threshold: float,
    text_threshold: float,
    processor,
    model,
    device: str,
) -> Dict[str, Any]:
    """Run broad + focused detection passes and return merged raw entries."""
    raw_entries: List[Dict[str, Any]] = []

    detections_pass1 = detect_objects(
        image=image,
        text_prompt=text_prompt,
        processor=processor,
        model=model,
        device=device,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
    )
    pass1_entries = detections_to_raw_entries(
        detections=detections_pass1,
        image_size=image.size,
        source_image=source_image,
        source_image_rel=source_image_rel,
        pass_name="pass1",
        prompt_used=text_prompt,
    )
    raw_entries.extend(pass1_entries)

    second_pass_used = False
    pass2_entries: List[Dict[str, Any]] = []
    if enable_second_pass and len(pass1_entries) < int(min_raw_for_second_pass):
        second_pass_used = True
        detections_pass2 = detect_objects(
            image=image,
            text_prompt=second_pass_text_prompt,
            processor=processor,
            model=model,
            device=device,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
        )
        pass2_entries = detections_to_raw_entries(
            detections=detections_pass2,
            image_size=image.size,
            source_image=source_image,
            source_image_rel=source_image_rel,
            pass_name="pass2",
            prompt_used=second_pass_text_prompt,
        )
        raw_entries.extend(pass2_entries)

    return {
        "raw_entries": raw_entries,
        "pass1_count": len(pass1_entries),
        "pass2_count": len(pass2_entries),
        "second_pass_used": second_pass_used,
    }


def _detect_icons_for_image_with_runtime(
    image_path: str,
    text_prompt: str,
    second_pass_text_prompt: str,
    enable_second_pass: bool,
    min_raw_for_second_pass: int,
    box_threshold: float,
    text_threshold: float,
    output_path: str,
    crops_dir: str,
    raw_metadata_json: str,
    usable_metadata_json: str,
    review_report_md: str,
    project_path: Optional[str],
    filter_config: FilterConfig,
    processor,
    model,
    device: str,
) -> Dict[str, Any]:
    """Internal helper for one image with preloaded model runtime."""
    image = Image.open(image_path).convert("RGB")
    source_image_rel = _source_rel(image_path, project_path)

    print(f"Image size: {image.size[0]}x{image.size[1]}")
    print(f"Pass 1 prompt: '{text_prompt}'")

    pass_result = _run_two_pass_detection(
        image=image,
        source_image=image_path,
        source_image_rel=source_image_rel,
        text_prompt=text_prompt,
        second_pass_text_prompt=second_pass_text_prompt,
        enable_second_pass=enable_second_pass,
        min_raw_for_second_pass=min_raw_for_second_pass,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
        processor=processor,
        model=model,
        device=device,
    )

    raw_entries = pass_result["raw_entries"]
    print(
        f"Raw detections: {len(raw_entries)} "
        f"(pass1={pass_result['pass1_count']}, pass2={pass_result['pass2_count']}, second_pass_used={pass_result['second_pass_used']})"
    )

    usable_entries, rejected_entries = filter_and_dedupe_raw_entries(raw_entries=raw_entries, config=filter_config)
    usable_with_crops = export_usable_crops(image=image, usable_entries=usable_entries, crops_dir=crops_dir)

    os.makedirs(os.path.dirname(raw_metadata_json) or ".", exist_ok=True)
    with open(raw_metadata_json, "w", encoding="utf-8") as file:
        json.dump(raw_entries, file, indent=2)

    os.makedirs(os.path.dirname(usable_metadata_json) or ".", exist_ok=True)
    usable_payload = {
        "source_image": image_path,
        "source_image_rel": source_image_rel,
        "usable_icons": usable_with_crops,
        "rejected_icons": rejected_entries,
        "filter_config": {
            "min_confidence": filter_config.min_confidence,
            "min_width": filter_config.min_width,
            "min_height": filter_config.min_height,
            "min_aspect": filter_config.min_aspect,
            "max_aspect": filter_config.max_aspect,
            "dedupe_iou_threshold": filter_config.dedupe_iou_threshold,
        },
    }
    with open(usable_metadata_json, "w", encoding="utf-8") as file:
        json.dump(usable_payload, file, indent=2)

    review_report = build_single_image_review_report(
        image_path=image_path,
        source_image_rel=source_image_rel,
        output_path=output_path,
        raw_metadata_json=raw_metadata_json,
        usable_metadata_json=usable_metadata_json,
        crops_dir=crops_dir,
        num_raw_detections=len(raw_entries),
        num_usable_icons=len(usable_with_crops),
        num_rejected_icons=len(rejected_entries),
        second_pass_used=pass_result["second_pass_used"],
        pass1_count=pass_result["pass1_count"],
        pass2_count=pass_result["pass2_count"],
    )
    os.makedirs(os.path.dirname(review_report_md) or ".", exist_ok=True)
    with open(review_report_md, "w", encoding="utf-8") as file:
        file.write(review_report)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    overlay = draw_detections_from_entries(image=image, entries=raw_entries)
    overlay.save(output_path)

    print(f"Saved overlay: {output_path}")
    print(f"Saved raw detections: {raw_metadata_json}")
    print(f"Saved usable icons: {usable_metadata_json}")
    print(f"Saved review report: {review_report_md}")
    print(f"Saved {len(usable_with_crops)} usable crop(s) to: {crops_dir}")

    return {
        "image": image_path,
        "source_image_rel": source_image_rel,
        "project_path": project_path,
        "output": output_path,
        "crops_dir": crops_dir,
        "raw_metadata_json": raw_metadata_json,
        "usable_metadata_json": usable_metadata_json,
        "review_report_md": review_report_md,
        "num_raw_detections": len(raw_entries),
        "num_usable_icons": len(usable_with_crops),
        "num_rejected_icons": len(rejected_entries),
        "raw_detections": raw_entries,
        "usable_icons": usable_with_crops,
        "rejected_icons": rejected_entries,
        "second_pass_used": pass_result["second_pass_used"],
        "pass1_count": pass_result["pass1_count"],
        "pass2_count": pass_result["pass2_count"],
        "artifact_contract": {
            "root": os.path.join(project_path, ICON_DETECTION_DIRNAME) if project_path else None,
            "overlays": os.path.dirname(output_path),
            "crops": crops_dir,
            "metadata": os.path.dirname(usable_metadata_json),
        },
    }


def detect_icons_for_image(
    image_path: str,
    text_prompt: str = DEFAULT_TEXT_PROMPT,
    second_pass_text_prompt: str = DEFAULT_SECOND_PASS_TEXT_PROMPT,
    enable_second_pass: bool = True,
    min_raw_for_second_pass: int = DEFAULT_MIN_RAW_FOR_SECOND_PASS,
    box_threshold: float = DEFAULT_BOX_THRESHOLD,
    text_threshold: float = DEFAULT_TEXT_THRESHOLD,
    model_id: str = DEFAULT_MODEL_ID,
    output_path: Optional[str] = None,
    crops_dir: Optional[str] = None,
    metadata_json: Optional[str] = None,
    raw_metadata_json: Optional[str] = None,
    usable_metadata_json: Optional[str] = None,
    review_report_md: Optional[str] = None,
    project_path: Optional[str] = None,
    filter_config: Optional[FilterConfig] = None,
) -> Dict[str, Any]:
    """Run icon detection on one image with two-pass detection and quality filtering."""
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    resolved = resolve_output_paths(
        image_path=image_path,
        output_path=output_path,
        crops_dir=crops_dir,
        metadata_json=metadata_json,
        raw_metadata_json=raw_metadata_json,
        usable_metadata_json=usable_metadata_json,
        project_path=project_path,
    )

    if filter_config is None:
        filter_config = FilterConfig()

    review_report_md = resolve_review_report_path(
        image_path=image_path,
        project_path=project_path,
        usable_metadata_json=resolved["usable_metadata_json"],
        review_report_md=review_report_md,
        batch_mode=False,
    )

    processor, model, device = load_model(model_id)

    return _detect_icons_for_image_with_runtime(
        image_path=image_path,
        text_prompt=text_prompt,
        second_pass_text_prompt=second_pass_text_prompt,
        enable_second_pass=enable_second_pass,
        min_raw_for_second_pass=min_raw_for_second_pass,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
        output_path=resolved["output"],
        crops_dir=resolved["crops_dir"],
        raw_metadata_json=resolved["raw_metadata_json"],
        usable_metadata_json=resolved["usable_metadata_json"],
        review_report_md=review_report_md,
        project_path=project_path,
        filter_config=filter_config,
        processor=processor,
        model=model,
        device=device,
    )


def detect_icons_for_project(
    project_path: str,
    images_subdir: str = "images",
    process_all_images: bool = False,
    text_prompt: str = DEFAULT_TEXT_PROMPT,
    second_pass_text_prompt: str = DEFAULT_SECOND_PASS_TEXT_PROMPT,
    enable_second_pass: bool = True,
    min_raw_for_second_pass: int = DEFAULT_MIN_RAW_FOR_SECOND_PASS,
    box_threshold: float = DEFAULT_BOX_THRESHOLD,
    text_threshold: float = DEFAULT_TEXT_THRESHOLD,
    model_id: str = DEFAULT_MODEL_ID,
    summary_json: Optional[str] = None,
    review_report_md: Optional[str] = None,
    filter_config: Optional[FilterConfig] = None,
) -> Dict[str, Any]:
    """Run icon detection across candidate images in a project."""
    if not os.path.isdir(project_path):
        raise FileNotFoundError(f"Project path not found: {project_path}")

    if filter_config is None:
        filter_config = FilterConfig()

    image_paths = list_project_images(project_path=project_path, images_subdir=images_subdir)
    selected_images, reason_by_image, used_fallback_all = select_candidate_images(
        image_paths=image_paths,
        process_all_images=process_all_images,
        hints=FILENAME_HINTS,
    )

    layout = ensure_icon_detection_dirs(project_path)
    if summary_json is None:
        summary_json = os.path.join(layout["root"], "summary.json")
    review_report_md = resolve_review_report_path(
        image_path=None,
        project_path=project_path,
        usable_metadata_json=None,
        review_report_md=review_report_md,
        batch_mode=True,
    )

    print(f"Found {len(image_paths)} image(s) in project images directory")
    print(f"Selected {len(selected_images)} candidate image(s) for detection")

    if not selected_images:
        summary = {
            "project_path": project_path,
            "images_subdir": images_subdir,
            "model": model_id,
            "process_all_images": process_all_images,
            "used_fallback_all_images": used_fallback_all,
            "total_images": len(image_paths),
            "candidate_images": 0,
            "processed_images": 0,
            "total_raw_detections": 0,
            "usable_icons": 0,
            "rejected_icons": 0,
            "second_pass_used_images": 0,
            "summary_json": summary_json,
            "review_report_md": review_report_md,
            "artifact_contract": layout,
            "images": [],
            "skipped": [
                {
                    "source_image": image_path,
                    "source_image_rel": os.path.relpath(image_path, start=project_path),
                    "reason": reason_by_image.get(image_path, "not_selected"),
                }
                for image_path in image_paths
            ],
        }
        with open(summary_json, "w", encoding="utf-8") as file:
            json.dump(summary, file, indent=2)
        with open(review_report_md, "w", encoding="utf-8") as file:
            file.write(build_project_review_report(summary))
        return summary

    processor, model, device = load_model(model_id)

    selected_set = set(selected_images)
    image_results: List[Dict[str, Any]] = []
    total_raw_detections = 0
    total_usable_icons = 0
    total_rejected_icons = 0
    second_pass_used_images = 0

    for image_path in selected_images:
        resolved = resolve_output_paths(
            image_path=image_path,
            output_path=None,
            crops_dir=None,
            metadata_json=None,
            raw_metadata_json=None,
            usable_metadata_json=None,
            project_path=project_path,
        )

        print(f"Processing image: {image_path}")
        result = _detect_icons_for_image_with_runtime(
            image_path=image_path,
            text_prompt=text_prompt,
            second_pass_text_prompt=second_pass_text_prompt,
            enable_second_pass=enable_second_pass,
            min_raw_for_second_pass=min_raw_for_second_pass,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            output_path=resolved["output"],
            crops_dir=resolved["crops_dir"],
            raw_metadata_json=resolved["raw_metadata_json"],
            usable_metadata_json=resolved["usable_metadata_json"],
            review_report_md=resolve_review_report_path(
                image_path=image_path,
                project_path=project_path,
                usable_metadata_json=resolved["usable_metadata_json"],
                review_report_md=None,
                batch_mode=False,
            ),
            project_path=project_path,
            filter_config=filter_config,
            processor=processor,
            model=model,
            device=device,
        )

        total_raw_detections += int(result["num_raw_detections"])
        total_usable_icons += int(result["num_usable_icons"])
        total_rejected_icons += int(result["num_rejected_icons"])
        if result["second_pass_used"]:
            second_pass_used_images += 1

        image_results.append(
            {
                "source_image": image_path,
                "source_image_rel": os.path.relpath(image_path, start=project_path),
                "selection_reason": reason_by_image.get(image_path, "selected"),
                "output": result["output"],
                "crops_dir": result["crops_dir"],
                "raw_metadata_json": result["raw_metadata_json"],
                "usable_metadata_json": result["usable_metadata_json"],
                "raw_detections": int(result["num_raw_detections"]),
                "usable_icons": int(result["num_usable_icons"]),
                "rejected_icons": int(result["num_rejected_icons"]),
                "second_pass_used": bool(result["second_pass_used"]),
                "pass1_count": int(result["pass1_count"]),
                "pass2_count": int(result["pass2_count"]),
            }
        )

    skipped = [
        {
            "source_image": image_path,
            "source_image_rel": os.path.relpath(image_path, start=project_path),
            "reason": reason_by_image.get(image_path, "not_selected"),
        }
        for image_path in image_paths
        if image_path not in selected_set
    ]

    summary = {
        "project_path": project_path,
        "images_subdir": images_subdir,
        "model": model_id,
        "text_prompt": text_prompt,
        "second_pass_text_prompt": second_pass_text_prompt,
        "enable_second_pass": enable_second_pass,
        "min_raw_for_second_pass": min_raw_for_second_pass,
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "filter_config": {
            "min_confidence": filter_config.min_confidence,
            "min_width": filter_config.min_width,
            "min_height": filter_config.min_height,
            "min_aspect": filter_config.min_aspect,
            "max_aspect": filter_config.max_aspect,
            "dedupe_iou_threshold": filter_config.dedupe_iou_threshold,
        },
        "process_all_images": process_all_images,
        "used_fallback_all_images": used_fallback_all,
        "total_images": len(image_paths),
        "candidate_images": len(selected_images),
        "processed_images": len(image_results),
        "total_raw_detections": total_raw_detections,
        "usable_icons": total_usable_icons,
        "rejected_icons": total_rejected_icons,
        "second_pass_used_images": second_pass_used_images,
        "summary_json": summary_json,
        "review_report_md": review_report_md,
        "artifact_contract": layout,
        "images": image_results,
        "skipped": skipped,
    }

    with open(summary_json, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)
    with open(review_report_md, "w", encoding="utf-8") as file:
        file.write(build_project_review_report(summary))

    print(f"Project summary saved to: {summary_json}")
    print(f"Project review report saved to: {review_report_md}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for single-image and project modes."""
    parser = argparse.ArgumentParser(description="Detect icons in diagram images using Grounding DINO")
    parser.add_argument("--image", default=None, help="Path to input diagram image for single-image mode")
    parser.add_argument(
        "--project-path",
        default=None,
        help=(
            "Optional project root. If provided with --image, outputs default to "
            "<project>/icon_detection/{overlays,crops,metadata}. If provided without --image, "
            "project batch mode runs over project images."
        ),
    )
    parser.add_argument(
        "--images-subdir",
        default="images",
        help="Project images subdirectory for batch mode (default: images)",
    )
    parser.add_argument(
        "--process-all-images",
        action="store_true",
        help="Batch mode: process all images instead of filename-hint candidate filtering",
    )
    parser.add_argument(
        "--summary-json",
        default=None,
        help="Batch mode: path to project summary JSON (default: <project>/icon_detection/summary.json)",
    )
    parser.add_argument(
        "--review-report-md",
        default=None,
        help=(
            "Path to markdown review report. Defaults to <project>/icon_detection/review.md in batch mode "
            "or a per-image review markdown next to usable metadata in single-image mode."
        ),
    )

    parser.add_argument(
        "--text-prompt",
        default=DEFAULT_TEXT_PROMPT,
        help="Pass 1 prompt: broad icon detection prompt",
    )
    parser.add_argument(
        "--second-pass-text-prompt",
        default=DEFAULT_SECOND_PASS_TEXT_PROMPT,
        help="Pass 2 prompt: focused recovery prompt used when pass 1 is sparse",
    )
    parser.add_argument(
        "--disable-second-pass",
        action="store_true",
        help="Disable second-pass recovery detection",
    )
    parser.add_argument(
        "--min-raw-for-second-pass",
        type=int,
        default=DEFAULT_MIN_RAW_FOR_SECOND_PASS,
        help=(
            "Run pass 2 when pass 1 raw detections are below this count "
            f"(default: {DEFAULT_MIN_RAW_FOR_SECOND_PASS})"
        ),
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_BOX_THRESHOLD,
        help=f"Box detection confidence threshold (default: {DEFAULT_BOX_THRESHOLD})",
    )
    parser.add_argument(
        "--text-threshold",
        type=float,
        default=DEFAULT_TEXT_THRESHOLD,
        help=f"Text matching threshold (default: {DEFAULT_TEXT_THRESHOLD})",
    )

    parser.add_argument(
        "--usable-min-confidence",
        type=float,
        default=DEFAULT_USABLE_MIN_CONFIDENCE,
        help=f"Minimum confidence for usable icons (default: {DEFAULT_USABLE_MIN_CONFIDENCE})",
    )
    parser.add_argument(
        "--usable-min-width",
        type=int,
        default=DEFAULT_USABLE_MIN_WIDTH,
        help=f"Minimum usable crop width in px (default: {DEFAULT_USABLE_MIN_WIDTH})",
    )
    parser.add_argument(
        "--usable-min-height",
        type=int,
        default=DEFAULT_USABLE_MIN_HEIGHT,
        help=f"Minimum usable crop height in px (default: {DEFAULT_USABLE_MIN_HEIGHT})",
    )
    parser.add_argument(
        "--usable-min-aspect",
        type=float,
        default=DEFAULT_USABLE_MIN_ASPECT,
        help=f"Minimum usable aspect ratio (default: {DEFAULT_USABLE_MIN_ASPECT})",
    )
    parser.add_argument(
        "--usable-max-aspect",
        type=float,
        default=DEFAULT_USABLE_MAX_ASPECT,
        help=f"Maximum usable aspect ratio (default: {DEFAULT_USABLE_MAX_ASPECT})",
    )
    parser.add_argument(
        "--dedupe-iou-threshold",
        type=float,
        default=DEFAULT_DEDUPE_IOU_THRESHOLD,
        help=f"IoU threshold for duplicate suppression (default: {DEFAULT_DEDUPE_IOU_THRESHOLD})",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Single-image mode overlay output path",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_ID,
        help=f"HuggingFace model ID (default: {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--crops-dir",
        default=None,
        help="Single-image mode crops dir",
    )
    parser.add_argument(
        "--metadata-json",
        default=None,
        help="Backward-compatible alias for --usable-metadata-json",
    )
    parser.add_argument(
        "--raw-metadata-json",
        default=None,
        help="Single-image mode raw detections metadata output JSON",
    )
    parser.add_argument(
        "--usable-metadata-json",
        default=None,
        help="Single-image mode usable icons metadata output JSON",
    )

    return parser


def _filter_config_from_args(args) -> FilterConfig:
    return FilterConfig(
        min_confidence=args.usable_min_confidence,
        min_width=args.usable_min_width,
        min_height=args.usable_min_height,
        min_aspect=args.usable_min_aspect,
        max_aspect=args.usable_max_aspect,
        dedupe_iou_threshold=args.dedupe_iou_threshold,
    )


def cli_main() -> None:
    """CLI entrypoint for one-image and project batch detection."""
    args = build_parser().parse_args()
    filter_config = _filter_config_from_args(args)
    enable_second_pass = not args.disable_second_pass

    if args.image:
        detect_icons_for_image(
            image_path=args.image,
            project_path=args.project_path,
            text_prompt=args.text_prompt,
            second_pass_text_prompt=args.second_pass_text_prompt,
            enable_second_pass=enable_second_pass,
            min_raw_for_second_pass=args.min_raw_for_second_pass,
            box_threshold=args.threshold,
            text_threshold=args.text_threshold,
            model_id=args.model,
            output_path=args.output,
            crops_dir=args.crops_dir,
            metadata_json=args.metadata_json,
            raw_metadata_json=args.raw_metadata_json,
            usable_metadata_json=args.usable_metadata_json,
            review_report_md=args.review_report_md,
            filter_config=filter_config,
        )
        return

    if args.project_path:
        detect_icons_for_project(
            project_path=args.project_path,
            images_subdir=args.images_subdir,
            process_all_images=args.process_all_images,
            text_prompt=args.text_prompt,
            second_pass_text_prompt=args.second_pass_text_prompt,
            enable_second_pass=enable_second_pass,
            min_raw_for_second_pass=args.min_raw_for_second_pass,
            box_threshold=args.threshold,
            text_threshold=args.text_threshold,
            model_id=args.model,
            summary_json=args.summary_json,
            review_report_md=args.review_report_md,
            filter_config=filter_config,
        )
        return

    raise SystemExit("Either --image or --project-path is required")


if __name__ == "__main__":
    cli_main()
