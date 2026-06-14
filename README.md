# North Bay Digital Foundry

A single-page website for **North Bay Digital Foundry** — a digital workshop where
useful tools for **AI, automation, engineering, and municipal technology** are
designed, prototyped, tested, and shared in the open.

The work is presented as **concepts, prototypes, experiments, and tools** — not
commercial products. The tone is that of a modern engineering workshop:
clarity, craftsmanship, experimentation, and practical utility.

---

## Purpose

The site is a portfolio and lab log for a one-person (or small) engineering
practice. Its goals, in order:

1. **Establish technical credibility** with engineering and public-sector peers.
2. **Show the work** — a structured grid of projects, each tagged with a status
   (`PROTOTYPE`, `CONCEPT`, `EXPERIMENT`, `TOOL`).
3. **Stay honest** — nothing is sold; everything is framed as something being
   built, tested, and documented.

It is intentionally a **static site** with no build step, no framework, and no
runtime dependencies, so it stays cheap to host, fast to load, and trivial to
maintain.

This implements the **"Systematic Grid"** direction (Variant C) from the
[Claude Design](https://claude.ai/design) wireframe handoff — the
Cloudflare/Vercel-like rigid modular grid that best fits a tools-and-portfolio
focus.

---

## Structure

The page is a single document organized into six numbered sections, mirrored by
the left index rail:

| #  | Section       | Content                                                        |
|----|---------------|----------------------------------------------------------------|
| 01 | Overview      | Hero statement + a spec block of "at a glance" stats           |
| 02 | Capabilities  | A bordered matrix of the five practice areas                   |
| 03 | Projects      | A uniform grid of six project cards                            |
| 04 | Lab log       | A table of recent experiments (date / experiment / tag / status) |
| 05 | Writing       | A two-column list of posts                                     |
| 06 | Contact       | A call-to-action panel                                         |

### Projects featured

- **Project Management Code** — engineering / automation · `PROTOTYPE`
- **As-Built Plan Retrieval System** — municipal · `CONCEPT`
- **Agenda Report AI Tool** — AI / automation · `PROTOTYPE`
- **AI Fleet Maintenance Prediction** — AI · `EXPERIMENT`
- **GIS Export CLI** — tools · `TOOL`
- **Offline Model Evaluation Kit** — AI · `EXPERIMENT`

### Semantic HTML

The markup uses landmark elements (`<header>`, `<nav>`, `<main>`, `<section>`,
`<footer>`), a real `<table>` for the lab log, heading levels in order
(`h1` → `h2` → `h3`), a skip link, `aria-current` on the active nav item, and
`aria-labelledby` on each section. Decorative elements (icons, thumbnails,
status dots) are marked `aria-hidden`.

---

## Typography

The entire site uses **[Inter](https://rsms.me/inter/)** (weights 400–800),
loaded from Google Fonts with `preconnect` hints. There is **one typeface** —
data and code contexts are unified onto Inter using its OpenType features rather
than a separate monospace font.

Key type decisions (from the refined design system):

- **Negative tracking that scales with size** — `-0.03em` on the hero down to
  `-0.014em` on small semibolds, so large type reads tight and intentional.
- **Root letter-spacing** `-0.006em` and `font-feature-settings: 'cv05'` for a
  clearer lowercase `l`, capital `I`, and `1`.
- **Eyebrow labels** — uppercase, `600` weight, `0.06em` tracking.
- **Data / numeric contexts** (`.tnum`) use **tabular figures + slashed zero**
  (`'tnum' 1, 'zero' 1`) so numbers align in the spec block, lab log, and rail
  index.
- **Fluid sizing** via `clamp()` for the hero, section titles, and CTAs.

Font stack fallback: `'Inter', system-ui, -apple-system, Segoe UI, Roboto, sans-serif`.

---

## Color palette

A warm, paper-toned palette with a single ember accent. All colors are defined
as CSS custom properties in `:root` (see `assets/css/styles.css`).

| Token            | Value     | Role                                   |
|------------------|-----------|----------------------------------------|
| `--paper`        | `#E9E7DF` | Page background                        |
| `--surface`      | `#FCFBF7` | Primary card / content surface         |
| `--surface-alt`  | `#F4F2EA` | Rail, spec block, tinted panels        |
| `--surface-tint` | `#F0EEE6` | Icon chips, thumbnails                 |
| `--ink`          | `#1A1A18` | Primary text **and** structural borders|
| `--muted`        | `#6B675C` | Secondary text                         |
| `--faint`        | `#8A867A` | Metadata, eyebrows                     |
| `--line`         | `#E5E2D9` | Hairline dividers                      |
| `--dash`         | `#C4C0B5` | Dashed dividers                        |
| `--accent`       | `#DC5B26` | Ember accent (links, primary buttons)  |
| `--status-wip`   | `#C4C0B5` | "Work in progress" status dot          |

The accent is used sparingly — links, the primary button, and "live" status
dots — so it reads as a deliberate signal rather than decoration.

> **Contrast note:** `--muted` and `--faint` are used only for secondary/large
> text. Primary copy uses `--ink` on light surfaces, which clears WCAG AA.

---

## Responsive behavior

The layout is a CSS Grid shell (`rail` + `content`) that reflows at three
breakpoints. No JavaScript is required for layout.

| Viewport            | Behavior                                                                 |
|---------------------|--------------------------------------------------------------------------|
| **> 860px**         | Full layout: left rail, 2-col hero, 3-col capabilities, 3-col projects.  |
| **≤ 860px** (tablet)| Capabilities and projects drop to 2 columns.                            |
| **≤ 760px** (mobile)| Rail collapses to a top bar with a **Menu** toggle; hero and spec stack. |
| **≤ 540px** (phone) | Capabilities, projects, and writing become single column; buttons stretch. |

The lab-log table is wrapped in a horizontally-scrollable container so it never
breaks the layout on narrow screens. Motion respects
`prefers-reduced-motion`.

---

## File organization

```
north-bay-digital-foundry/
├── index.html              # The single landing page (all content)
├── 404.html                # Custom not-found page (Cloudflare Pages)
├── _headers                # Cloudflare Pages response headers (security + cache)
├── README.md               # This file
└── assets/
    ├── css/
    │   └── styles.css      # All styles; design tokens in :root
    └── js/
        └── main.js         # Progressive enhancement (nav toggle, scroll-spy, year)
```

There is no build step. The files served are the files in the repository.

---

## Development & deployment

### Local preview

Any static file server works. For example:

```bash
# Python
python -m http.server 8000

# Node
npx serve .
```

Then open <http://localhost:8000>. Because asset paths are root-relative
(`/assets/...`), serve from the project root.

### Cloudflare Pages

This site is built to deploy on **Cloudflare Pages** with zero configuration:

- **Build command:** *(none)*
- **Build output directory:** `/` (the repository root)
- `_headers` is picked up automatically for security and cache headers.
- `404.html` is served automatically for unknown routes.

Connect the repository in the Cloudflare dashboard (or `wrangler pages deploy .`)
and every push deploys.

---

## Future maintenance & expansion

The site is deliberately simple so it can grow without a rewrite:

- **Add or edit a project** — copy one `.card` block in the Projects grid. The
  grid is uniform and auto-flows, so adding a seventh card needs no CSS changes.
  Use the `dot` (accent) / `dot--wip` (grey) status classes and a status label
  (`PROTOTYPE`, `CONCEPT`, `EXPERIMENT`, `TOOL`).
- **Real thumbnails** — the `.card__thumb` blocks are CSS placeholders. Swap in
  `<img>` screenshots when available; the card height adapts.
- **Add a lab-log entry** — add a `<tr>` to the table; keep dates in ISO
  `YYYY-MM-DD` format so tabular figures stay aligned.
- **Re-theme** — every color and key dimension is a CSS variable in `:root`.
  Changing `--accent` re-themes the whole site (this mirrors the wireframe's
  switchable accent control).
- **Grow into multiple pages** — when project or writing detail pages are
  needed, factor the rail and shared styles out; `styles.css` is already
  organized by component with section banners.
- **Contact** — the CTA currently points to a `mailto:` placeholder. Update the
  address in `index.html` (search for `mailto:`) or swap it for a form/handler.

### Design provenance

This implementation came from a Claude Design handoff bundle
(`North Bay Digital Foundry - Wireframes.dc.html`). The wireframe explored three
directions — Editorial, Lab-first, and Systematic Grid — and the **Systematic
Grid** direction was selected and built here. If the design is revised in Claude
Design, re-export the bundle and reconcile changes against this static
implementation.
