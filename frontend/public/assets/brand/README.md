# NetBox Sync brand

Native SVG paths interpret the operator-provided linked-node / sync-arrow concept.
They do not embed the raster reference or copy the NetBox logo. `mark.svg` and
`favicon.svg` are text-free; `logo-light.svg` and `logo-dark.svg` are wordmarks.
The application uses the same mark with accessible HTML text and its local Inter font.
Standalone wordmark SVG uses Inter when available and a sans-serif fallback.

From `frontend/`, `node scripts/export-brand.mjs` regenerates 16/32/180 px PNGs
using the existing Playwright Chromium runtime. ICO contains 16/32 px versions.
The exports retain transparency and were inspected at small sizes. No external CDN.
