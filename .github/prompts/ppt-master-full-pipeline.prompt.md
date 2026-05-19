---
mode: agent
description: Full PPT Master pipeline — converts any source (PDF/DOCX/URL/Markdown/Images) into a designed PPTX presentation
---

# PPT Master — Full Pipeline

Converts source documents into a polished PPTX presentation via AI-driven SVG generation.

## Pipeline Steps (always serial)

```
Step 1: Convert source → Markdown
Step 2: Initialize project
Step 3: Template selection (user confirms)
Step 4: Strategist — Eight Confirmations + design_spec.md (user confirms)
Step 5: Image_Generator (if AI images needed)
Step 6: Executor — SVG slides generation
Step 7: Post-processing — export PPTX
```

---

## Start Instructions

Tell me what you want to present. You can provide:
- A PDF, DOCX, or other file path
- A URL to scrape
- A PPTX to re-style
- Plain text or Markdown
- A collection of images

I will follow the full pipeline from `skills/ppt-master/SKILL.md` automatically, stopping only at the two required user confirmation points:
1. **Template selection** (Step 3)
2. **Eight Confirmations** (Step 4)

After your second confirmation, everything runs automatically through to PPTX export.

---

## Format Options

| Code | Canvas | Use For |
|------|--------|---------|
| `ppt169` | 1280×720 (16:9) | Standard presentations |
| `ppt43` | 1024×768 (4:3) | Older projectors |
| `xhs` | 1242×1660 | Xiaohongshu / RED |
| `story` | 1080×1920 | TikTok / Instagram Story |
| `wechat` | 1080×1080 | WeChat Moments |

Default: `ppt169`

---

## SVG Constraints Summary (absolute rules)

**Banned**: `mask` · `<style>` · `class` · `<foreignObject>` · `textPath` · `@font-face` · `<animate*>` · `<script>` · `<iframe>` · `<symbol>+<use>` (outside defs) · `rgba()` · group `opacity`

**Use instead**: `fill-opacity` / `stroke-opacity` for transparency

**Icons (6700+)**:
```xml
<use data-icon="chunk/home" x="0" y="0" width="48" height="48" fill="#333"/>
```
Search: `ls skills/ppt-master/templates/icons/chunk/ | grep <keyword>`
