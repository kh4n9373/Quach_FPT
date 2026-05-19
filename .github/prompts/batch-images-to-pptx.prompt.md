---
agent: agent
description: Convert multiple images or a PDF into a PPTX where each image or page becomes one slide while preserving layout, colors, and reusable source-specific icons when reconstruction is needed
---

# Workflow: Batch Images / PDF → PPTX (1 input = 1 slide)

Convert a collection of images or a multi-page PDF into a PPTX presentation where:
- each image file becomes one PPTX slide,
- each PDF page becomes one PPTX slide.

## Two Modes

### Mode A: Multiple images → PPTX
Each image is analyzed and then either embedded directly or reconstructed as a native SVG slide.

### Mode B: PDF → PPTX
PDF is first converted to Markdown and extracted images, then each page becomes one slide.

---

## Mode A: Images → PPTX

### Step 1 — Set up the project
```bash
python3 skills/ppt-master/scripts/project_manager.py init <project_name> --format ppt169
python3 skills/ppt-master/scripts/project_manager.py import-sources projects/<project_name> <img1> <img2> <img3> ... --move
```

### Step 2 — Analyze imported images
```bash
python3 skills/ppt-master/scripts/analyze_images.py projects/<project_name>/images
```
Use the output to:
- extract a shared color palette across slides,
- note each image's broad layout type,
- separate likely photo slides from diagram or infographic slides.

If the batch contains diagrams, screenshots, architecture slides, or infographics with reusable embedded icons, run icon detection once for the whole project:

```bash
python3 skills/ppt-master/scripts/detect_icons.py --project-path projects/<project_name>
```

Before generating reconstruct-mode slides, review:
- `projects/<project_name>/icon_detection/review.md`
- overlay previews under `projects/<project_name>/icon_detection/overlays/`
- `projects/<project_name>/icon_detection/metadata/*.usable_icons.json`

### Step 3 — Define the shared reconstruction context
Define a minimal shared design context:
- Canvas: `0 0 1280 720`
- Colors: extracted shared palette
- Font: system sans-serif matching the source set
- Layout: each image determines its own slide layout
- Built-in icon replacement library: lock one library if fallback icons are needed

### Step 4 — Generate one SVG per image sequentially
For each image `<N>_<name>.png` in `projects/<project_name>/images/`:
1. reference that file's image-analysis output,
2. decide between embed mode and reconstruct mode,
3. write `projects/<project_name>/svg_output/<N>_<name>.svg`.

Use embed mode when the image is a photograph, dense illustration, or other fidelity-first visual.

Embed-mode SVG template:
```xml
<svg viewBox="0 0 1280 720" xmlns="http://www.w3.org/2000/svg">
  <image href="../images/<filename>" x="0" y="0" width="1280" height="720"
         preserveAspectRatio="xMidYMid slice"/>
</svg>
```

Use reconstruct mode when the image is a diagram, flowchart, architecture visual, or infographic.

Reconstruct-mode rules:
- follow the same process as `.github/prompts/image-diagram-to-slide.prompt.md` for each image,
- use reviewed extracted icon crops for fidelity-critical source-specific icons when they are clear and legible,
- fall back to the locked built-in icon library or native redraw for generic or weak crops.

### Step 5 — Export
```bash
python3 skills/ppt-master/scripts/finalize_svg.py projects/<project_name>
# ✅ Confirm success, then:
python3 skills/ppt-master/scripts/svg_to_pptx.py projects/<project_name> -s final
```

---

## Mode B: PDF → PPTX

### Step 1 — Convert PDF to Markdown
```bash
python3 skills/ppt-master/scripts/source_to_md/pdf_to_md.py <pdf_file>
```

### Step 2 — Initialize project and import source artifacts
```bash
python3 skills/ppt-master/scripts/project_manager.py init <project_name> --format ppt169
python3 skills/ppt-master/scripts/project_manager.py import-sources projects/<project_name> <pdf_file> <generated_md_file> --move
```

### Step 3 — Analyze extracted images
```bash
python3 skills/ppt-master/scripts/analyze_images.py projects/<project_name>/images
```

If extracted page images contain reusable icons inside diagrams or screenshots, also run:

```bash
python3 skills/ppt-master/scripts/detect_icons.py --project-path projects/<project_name>
```

### Step 4 — Generate one SVG per PDF page
Using both the Markdown text content and the extracted page images, generate one SVG per page:
- use the page's text content for the slide body,
- use the page's extracted image as `<image href="../images/page_N.png" .../>` or reconstruct it when editability is important,
- number files `01_page1.svg`, `02_page2.svg`, and so on.

### Step 5 — Export
Use the same export sequence as Mode A Step 5.

---

## Tips
- For diagrams and architecture slides, use reconstruct mode and reuse reviewed extracted icon crops only when they improve fidelity.
- For photo or illustration slides, use embed mode for fidelity.
- Mix modes freely within the same presentation.
- Run `python3 skills/ppt-master/scripts/svg_quality_checker.py projects/<project_name>` before export to catch SVG issues.

## What to provide
Either a list of image files, or a PDF file path.
