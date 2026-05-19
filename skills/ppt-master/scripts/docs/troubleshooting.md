# Troubleshooting

## Validation Failed

1. Run:

```bash
python3 scripts/project_manager.py validate <project_path>
```

2. Fix missing files or invalid directories reported by the validator.
3. Re-run validation before post-processing or export.

## SVG Preview Looks Wrong

1. Check the file path and filename.
2. Confirm naming conventions are consistent.
3. Preview via a local server if browser file loading is inconsistent:

```bash
python3 -m http.server --directory <svg_output_path> 8000
```

## Speaker Notes Do Not Split

Check `total.md`:
- headings must start with `# `
- heading text must match SVG filenames
- sections must be separated by `---`

Then rerun:

```bash
python3 scripts/total_md_split.py <project_path>
```

## PPT Export Quality Issues

Preferred sequence:

```bash
python3 scripts/total_md_split.py <project_path>
python3 scripts/finalize_svg.py <project_path>
python3 scripts/svg_to_pptx.py <project_path> -s final
```

Do not export directly from `svg_output/` when `svg_final/` exists.

## Dependency Checklist

Most tools use the standard library. Install extra dependencies only when needed:

```bash
pip install -r requirements.txt
```

Important optional packages:
- `python-pptx` for PPTX export
- `Pillow` for image utilities
- `numpy` for watermark removal
- `PyMuPDF` for PDF conversion
- `google-genai` / `openai` for image generation backends
- `transformers` + `torch` for Grounding DINO icon detection

## `detect_icons.py` Fails To Start

Typical cause: missing ML dependencies.

Install:

```bash
pip install transformers torch Pillow
```

Then retry:

```bash
python3 scripts/detect_icons.py --image <image_path>
```

If `torch` installation fails, use the platform-specific install guidance from PyTorch first, then install the remaining requirements.

## `detect_icons.py` Is Very Slow

Common causes:

- first run downloading the model,
- CPU fallback instead of CUDA,
- processing all project images instead of filtered candidates.

Checks:

1. Confirm the first run has finished downloading the model.
2. Check whether the script logs `Using device: cpu`.
3. Prefer candidate filtering over `--process-all-images` unless needed.

Ways to reduce runtime:

- process only likely diagram images,
- keep the default tiny model unless quality requires a larger one,
- tune thresholds to reduce noisy detections,
- rerun after model cache is warm.

## `detect_icons.py` Downloads The Model Every Time

Grounding DINO weights should be cached by Hugging Face after the first successful run.

Checks:

1. Ensure the process can write to the default Hugging Face cache directory.
2. If your environment uses a custom cache path, keep it stable between runs.
3. Avoid clearing the model cache between executions unless necessary.

Symptom meaning:

- first download on a new machine: expected
- repeated download every run: cache path or permissions issue

## Batch Run Produces Too Many Bad Icon Crops

Tune the quality gate instead of disabling filtering.

Useful controls:

- `--usable-min-confidence`
- `--usable-min-width`
- `--usable-min-height`
- `--usable-min-aspect`
- `--usable-max-aspect`
- `--dedupe-iou-threshold`

Recommendation:

1. Increase `--usable-min-confidence` first.
2. Then increase min width and height.
3. Tighten dedupe only after confidence and size are reasonable.

## Review Report Looks Good But Handoff Still Feels Risky

Use the review artifacts as a gate, not just as logs.

Check:

1. Open `icon_detection/review.md`.
2. Cross-check a few overlay previews against `*.usable_icons.json`.
3. Confirm generic icons are not being kept only because they were detected.
4. Confirm every fidelity-critical extracted icon has a fallback recommendation.

If the batch is still noisy after review:

- rerun with stricter quality thresholds,
- process a smaller subset of images,
- or accept only a manually chosen subset of extracted icons into the design spec.
