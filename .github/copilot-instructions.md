# GitHub Copilot — PPT Master Workspace Instructions

This workspace is the **PPT Master** AI-driven presentation generation system.
It converts source documents (PDF/DOCX/URL/Markdown/Images) into natively editable PPTX via DrawingML through a multi-role pipeline.

---

## Core Pipeline (always follow this order)

```
Source → Project Init → Template Choice → Strategist (Eight Confirmations)
       → [Image_Generator] → Executor (SVG generation) → Post-processing → Export PPTX
```

Steps **must** be executed serially. Never bundle or parallelize steps.

---

## Role Definitions (read before switching roles)

| Role | Reference File | Trigger |
|------|---------------|---------|
| Strategist | `skills/ppt-master/references/strategist.md` | After project init & template choice |
| Image_Generator | `skills/ppt-master/references/image-generator.md` | When AI image generation is needed |
| Executor | `skills/ppt-master/references/executor-base.md` + style file | After design spec confirmed |

Always read the role's reference file before acting as that role.

---

## Key Scripts

```bash
# Convert source documents
python3 skills/ppt-master/scripts/source_to_md/pdf_to_md.py <file>
python3 skills/ppt-master/scripts/source_to_md/doc_to_md.py <file>
python3 skills/ppt-master/scripts/source_to_md/ppt_to_md.py <file>
python3 skills/ppt-master/scripts/source_to_md/web_to_md.py <URL>

# Project management
python3 skills/ppt-master/scripts/project_manager.py init <name> --format ppt169
python3 skills/ppt-master/scripts/project_manager.py import-sources <path> <files> --move

# Image analysis (NEVER open image files directly — always use this script)
python3 skills/ppt-master/scripts/analyze_images.py <project_path>/images

# AI image generation
python3 skills/ppt-master/scripts/image_gen.py "prompt" --aspect_ratio 16:9 -o <project_path>/images

# Post-processing (run ONE AT A TIME, confirm each succeeds before next)
python3 skills/ppt-master/scripts/total_md_split.py <project_path>
python3 skills/ppt-master/scripts/finalize_svg.py <project_path>
python3 skills/ppt-master/scripts/svg_to_pptx.py <project_path> -s final
```

---

## SVG Canvas Dimensions

| Format | viewBox |
|--------|---------|
| PPT 16:9 | `0 0 1280 720` |
| PPT 4:3 | `0 0 1024 768` |

---

## SVG Absolute Prohibitions

`mask` · `<style>` · `class` · `<foreignObject>` · `textPath` · `@font-face` · `<animate*>` · `<script>` · `<iframe>` · `<symbol>+<use>` (outside defs)

Use `fill-opacity`/`stroke-opacity` instead of `rgba()`. Never use group opacity.

---

## Image Embedding Rule

During SVG generation (`svg_output/`), reference images externally:
```xml
<image href="../images/photo.png" x="0" y="0" width="640" height="360"
       preserveAspectRatio="xMidYMid slice"/>
```
`finalize_svg.py` will auto-embed to base64 in `svg_final/`.

---

## Icon Library (6700+ icons)

```xml
<!-- Use placeholder syntax — finalize_svg.py auto-embeds -->
<use data-icon="chunk/home" x="100" y="200" width="48" height="48" fill="#005587"/>
<use data-icon="tabler-filled/chart-bar" x="100" y="200" width="48" height="48" fill="#1976D2"/>
<use data-icon="tabler-outline/arrow-right" x="100" y="200" width="48" height="48" fill="#333"/>
```

Search icons: `ls skills/ppt-master/templates/icons/chunk/ | grep <keyword>`

---

## Projects Workspace

All user projects live in `projects/`. Never modify `examples/` or `skills/`.
