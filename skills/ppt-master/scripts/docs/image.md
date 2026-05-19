# Image Tools

Image tools cover prompt-based generation, image inspection, icon extraction, and Gemini watermark removal.

## `image_gen.py`

Unified image generation entry point.

```bash
python3 scripts/image_gen.py "A modern futuristic workspace"
python3 scripts/image_gen.py "Abstract tech background" --aspect_ratio 16:9 --image_size 4K
python3 scripts/image_gen.py "Concept car" -o projects/demo/images
python3 scripts/image_gen.py "Beautiful landscape" -n "low quality, blurry, watermark"
python3 scripts/image_gen.py --list-backends
```

Backends are grouped into Core / Extended / Experimental tiers. Run `python3 scripts/image_gen.py --list-backends` for the current list.

Backend selection:

```bash
python3 scripts/image_gen.py "A cat" --backend openai
python3 scripts/image_gen.py "A cinematic portrait" --backend minimax
python3 scripts/image_gen.py "A product launch hero image" --backend qwen
python3 scripts/image_gen.py "科技感背景图" --backend zhipu
python3 scripts/image_gen.py "A product KV in cinematic style" --backend volcengine
```

Configuration sources:

1. Current process environment variables
2. Repo-root `.env` as a fallback

The active backend must always be selected explicitly via `IMAGE_BACKEND`.

Example `.env`:

```env
IMAGE_BACKEND=gemini
GEMINI_API_KEY=your-api-key
GEMINI_BASE_URL=https://your-proxy-url.com/v1beta
GEMINI_MODEL=gemini-3.1-flash-image-preview
```

Example process environment:

```bash
export IMAGE_BACKEND=gemini
export GEMINI_API_KEY=your-api-key
export GEMINI_MODEL=gemini-3.1-flash-image-preview
```

Current process environment wins over `.env`.

Use provider-specific keys only (e.g. `GEMINI_API_KEY`, `OPENAI_API_KEY`). See `.env.example` for the full list per backend.

`IMAGE_API_KEY`, `IMAGE_MODEL`, and `IMAGE_BASE_URL` are intentionally unsupported.

If you keep multiple providers in one `.env` or environment, `IMAGE_BACKEND` must explicitly select the active provider.

Recommendation:
- Default to the Core tier for routine PPT work
- Use Extended only when you need a specific model style
- Treat Experimental backends as opt-in

Example `.env` for MiniMax image backend:

```env
IMAGE_BACKEND=minimax
MINIMAX_API_KEY=your-api-key
# Optional: override base URL (defaults to https://api.minimaxi.com, domestic China endpoint)
# Use https://api.minimax.io for overseas access
# MINIMAX_BASE_URL=https://api.minimax.io
# MINIMAX_MODEL=image-01
```

## `analyze_images.py`

Analyze images in a project directory before writing the design spec or composing slide layouts.

```bash
python3 scripts/analyze_images.py <project_path>/images
```

Use this instead of opening image files directly when following the project workflow.

## `detect_icons.py`

Detect reusable embedded icons in original user-provided images using Grounding DINO.

Single-image mode:

```bash
python3 scripts/detect_icons.py --image diagram.png
python3 scripts/detect_icons.py --image diagram.png --project-path projects/demo
python3 scripts/detect_icons.py --image diagram.png --text-prompt "logo. icon." --second-pass-text-prompt "architecture icon. cloud icon. server icon."
```

Project batch mode:

```bash
python3 scripts/detect_icons.py --project-path projects/demo
python3 scripts/detect_icons.py --project-path projects/demo --process-all-images
python3 scripts/detect_icons.py --project-path projects/demo --images-subdir images
```

Output contract:

- `project/icon_detection/overlays/` — detection preview images
- `project/icon_detection/crops/` — exported usable icon crops
- `project/icon_detection/metadata/*.raw_detections.json` — raw model detections
- `project/icon_detection/metadata/*.usable_icons.json` — filtered reusable icon candidates
- `project/icon_detection/summary.json` — project-wide batch summary
- `project/icon_detection/review.md` — project-level manual review and acceptance checklist
- `project/icon_detection/metadata/<image-stem>.review.md` — single-image review report when running per image

Important tuning knobs:

- `--threshold` / `--text-threshold` — model detection thresholds
- `--second-pass-text-prompt` — focused recovery prompt for sparse first-pass results
- `--disable-second-pass` — force single-pass mode
- `--usable-min-confidence` — minimum confidence for reusable icons
- `--usable-min-width`, `--usable-min-height` — reject tiny crops
- `--usable-min-aspect`, `--usable-max-aspect` — reject extreme aspect ratios
- `--dedupe-iou-threshold` — duplicate suppression threshold

Runtime notes:

- First run downloads Grounding DINO weights from Hugging Face and caches them locally.
- The script auto-selects `cuda` when available, otherwise falls back to CPU.
- CPU mode is supported but may be slow for large project batches.
- For repeatable project use, run inside the workspace environment after installing `transformers` and `torch`.

Workflow recommendation:

1. Run `analyze_images.py` first for user-provided images.
2. Run `detect_icons.py --project-path <project_path>` when diagrams or screenshots may contain reusable embedded icons.
3. Review `review.md`, overlay previews, and `*.usable_icons.json` before handoff.
4. Use `*.usable_icons.json` and `summary.json` as Strategist / Executor handoff inputs only after review.

Acceptance rule:

- Do not treat extracted icons as ready for Strategist / Executor handoff until the markdown review checklist has been inspected and weak crops have been rejected conceptually.

## `gemini_watermark_remover.py`

Remove Gemini watermark assets after manual download.

```bash
python3 scripts/gemini_watermark_remover.py <image_path>
python3 scripts/gemini_watermark_remover.py <image_path> -o output_path.png
python3 scripts/gemini_watermark_remover.py <image_path> -q
```

Notes:
- Requires `scripts/assets/bg_48.png` and `scripts/assets/bg_96.png`
- Best used after downloading “full size” Gemini images

Dependencies:

```bash
pip install Pillow numpy transformers torch
```
