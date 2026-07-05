# North Bay Digital Foundry — Style Guide

A practical reference for building new pages that match the existing site.
Written for future contributors and AI coding assistants (Claude, Codex, etc.).

**The source of truth is the code.** All design tokens live in
`assets/css/styles.css` (`:root`); the two existing pages are the reference
implementations:

- `index.html` — the homepage (all shared components in use)
- `excavator-wind-run.html` + `assets/css/excavator-wind-run.css` +
  `assets/js/excavator-wind-run.js` — the reference for a tool/game subpage

When this document and the code disagree, follow the code.

---

## 1. Site identity and tone

- **What it is:** a digital workshop — concepts, prototypes, experiments, and
  tools for AI, automation, engineering, and municipal technology, "shared in
  the open."
- **Tone:** modern engineering workshop. Clear, honest, unhyped. Nothing is
  sold; everything is framed as something being built, tested, and documented.
  Status labels (`PROTOTYPE`, `CONCEPT`, `EXPERIMENT`, `TOOL`) keep that honesty
  visible.
- **Design direction:** "Systematic Grid" (Variant C of the original Claude
  Design wireframe) — a rigid, modular, bordered grid in the spirit of
  Cloudflare/Vercel dashboards, on a warm paper palette.
- **Stack:** plain HTML, CSS, and JavaScript. **No frameworks, no build step.**
  The files served are the files in the repository. Do not introduce React,
  Tailwind, bundlers, or CSS preprocessors unless explicitly requested.

## 2. Page layout conventions

Every page is a bordered "shell" card centered on the paper background:

```html
<body>
  <a class="skip-link" href="#main-section-id">Skip to content</a>
  <div class="shell">
    <header class="rail"> … sidebar … </header>
    <main class="content"> … numbered sections … </main>
  </div>
  <footer class="colophon"> … © line … </footer>
  <script src="assets/js/main.js" defer></script>
</body>
```

- `.shell`: max-width `1100px` (`--shell-max`), `2px` ink border,
  `14px` radius, offset shadow `7px 7px 0 rgba(26,26,24,0.13)`, two-column grid
  (`230px` rail + content).
- `.content` sections use `.section` (padding `--pad-section`, `2px` ink
  bottom border between sections).
- The hero is a two-column grid: `.hero__main` (kicker, title, lede, actions)
  plus a `.spec` block (dashed left border, label/value rows) on the right.
- `.colophon` footer sits **outside** the shell: copyright + a one-line motto.
- **Asset paths are relative** (`assets/css/styles.css`, `index.html`) so pages
  work both opened from disk and served from a web root. Exception: `404.html`
  keeps root-absolute paths because Cloudflare serves it at any route depth.

Head conventions (copy from an existing page): `meta description`, Open Graph
tags, the inline-SVG NBDF favicon, Inter loaded from Google Fonts with
`preconnect`, then `assets/css/styles.css`, then the page's own CSS (if any).

## 3. Sidebar / navigation conventions

- `.rail`: `--surface-alt` background, `2px` ink right border. Contains, in
  order: brand row (`.brand-mark` square + `NBDF` wordmark + mobile
  `.rail__toggle` "Menu" button), the numbered nav, and `.rail__meta` pinned to
  the bottom (`North Bay · est. 2024` on the homepage; `Prototype · v0.1` on
  the game page).
- Nav is an ordered list of `NN · Label` links. The homepage lists site
  sections `01 · Overview` … `06 · Contact` plus cross-page entries
  (`07 · Excavator Wind Run`). Subpages list their **own** sections starting
  again at `01 ·` and add a `.rail__home` "← Back to the foundry" link above
  the nav.
- `aria-current="true"` marks the active link (styled ink-on-dark);
  `assets/js/main.js` provides the scroll-spy and the mobile menu toggle —
  include it on every page.

## 4. Section numbering conventions

- Every section starts with an `.eyebrow` label: `NN · Section name`
  (uppercase, 11px, letter-spaced) followed by an `h2.section__title`.
- Numbers are per-page, zero-padded, and must match the rail nav.
- Use `.section__head` when a section pairs its title with a right-aligned
  `.link-accent` (e.g. "Concepts, prototypes & tools →").

## 5. Color palette and accent use

All colors are CSS custom properties in `:root` of `styles.css`. Never
hard-code hex values in page markup; use the tokens.

| Token            | Value     | Role                                    |
|------------------|-----------|-----------------------------------------|
| `--paper`        | `#E9E7DF` | Page background                         |
| `--surface`      | `#FCFBF7` | Card / content surface                  |
| `--surface-alt`  | `#F4F2EA` | Rail, spec block, tinted panels         |
| `--surface-tint` | `#F0EEE6` | Icon chips, thumbnails                  |
| `--ink`          | `#1A1A18` | Primary text **and** structural borders |
| `--muted`        | `#6B675C` | Secondary text                          |
| `--faint`        | `#8A867A` | Metadata, eyebrows                      |
| `--line`         | `#E5E2D9` | Hairline dividers                       |
| `--line-strong`  | `#1A1A18` | Structural borders                      |
| `--dash`         | `#C4C0B5` | Dashed dividers                         |
| `--accent`       | `#DC5B26` | Site accent (ember orange)              |
| `--status-wip`   | `#C4C0B5` | Grey "work in progress" status dot      |

**Accent rules:**

- The site-wide accent is **ember orange** (`#DC5B26`). Use it sparingly —
  links, the primary button, live status dots, the hero kicker. It must read
  as a signal, not decoration.
- A subpage may re-theme itself by overriding `--accent` in its **own** CSS
  file (loaded after `styles.css`). The game page does this with blue
  `#2563EB`. Never change the accent in `styles.css` itself — that re-themes
  the whole site.
- Single-purpose colors get their own scoped token (e.g. the game page's
  `--machine-yellow: #F0C232`, used only for the canvas excavator).

## 6. Typography conventions

- **One typeface: Inter** (weights 400–800), from Google Fonts. There is no
  monospace font — data/code contexts use Inter's OpenType features via the
  `.tnum` utility (`'tnum' 1, 'zero' 1` → tabular figures + slashed zero).
- Root: 16px, line-height 1.5, letter-spacing `-0.006em`, `'cv05' 1` for a
  clearer lowercase l / capital I / 1.
- **Negative tracking scales with size:** hero `-0.03em` → section titles
  `-0.022em` → small semibolds `-0.014em`. Large type reads tight.
- Eyebrows/labels: uppercase, weight 600, tracking `+0.06em`, 10–11px.
- Fluid sizes via `clamp()` (hero `clamp(2rem, 5vw, 2.75rem)`, section titles
  `clamp(1.35rem, 3vw, 1.625rem)`).
- Dates in ISO `YYYY-MM-DD` inside `.tnum` contexts so columns align.

## 7. Border / grid / card conventions

The bordered grid is the signature of the site:

- **Structural borders:** `2px solid var(--line-strong)` (shell, sections,
  cards, tables, stat matrices). Buttons use `2.5px`.
- **Hairline dividers:** `1.5px solid var(--line)` (rows inside components).
- **Dashed dividers:** `2px dashed var(--dash)` (the hero/spec boundary).
- **Radii:** shell `14px` (`--radius`), components `10px`, buttons/small chips
  `8px` (`--radius-sm`).
- **Cell matrices** (e.g. `.matrix`, `.conditions`): one outer `2px` border,
  internal `2px` borders on cells, with `:nth-child` rules removing the last
  column's right border and last row's bottom border. Copy the existing
  pattern, including its responsive overrides.
- **Offset shadows, never blur:** hover states translate `-1px/-2px` and add a
  hard shadow like `4px 4px 0 rgba(26,26,24,0.15)`.

## 8. Button and link styling

- `.btn`: inline-block, weight 600, `2.5px` ink border, radius `8px`,
  transparent background, ink text. Hover: translate `(-1px,-1px)` + hard
  shadow; active: reset.
- `.btn--primary`: accent background, `--accent-ink` (paper-white) text.
  One primary button per view, for the main action.
- `.btn--sm`: 14px / `8px 18px` padding — used for in-page controls (game
  buttons).
- Links inherit ink by default (`a { color: inherit }`). Accent links use
  `.link-accent` (13px, weight 600, accent color, underline on hover).
- Never invent new button variants; compose from these.

## 9. Project card conventions

Cards live in the homepage `.projects` grid (3 columns desktop). Structure:

```html
<a class="card" href="page.html">            <!-- <article> if not a link -->
  <div class="card__thumb" aria-hidden="true"></div>
  <div class="card__body">
    <p class="card__cat">CATEGORY · TAGS</p>
    <h3 class="card__title">Title</h3>
    <p class="card__desc">One–two sentence description.</p>
    <div class="card__foot">
      <span class="status"><span class="dot" aria-hidden="true"></span>PROTOTYPE</span>
      <span class="card__arrow" aria-hidden="true">↗</span>
    </div>
  </div>
</a>
```

- Status vocabulary: `PROTOTYPE`, `CONCEPT`, `EXPERIMENT`, `TOOL` (the game
  card uses `GAME · CANVAS` as its category). Accent `.dot` = live/active;
  `.dot--wip` = grey work-in-progress.
- `.card__thumb` is a CSS placeholder (tinted panel with an X of dashed
  lines) — swap for a real `<img>` when a screenshot exists.
- The grid auto-flows: adding a card requires **no CSS changes**.
- When a card links to a real page, also add a numbered rail entry on the
  homepage (see §3) so both routes exist.

## 10. Tool / game page conventions

`excavator-wind-run.html` is the template for interactive subpages:

- **Same shell.** Reuse `.shell`, `.rail` (with `.rail__home` back link and
  page-local numbered nav), hero + `.spec` briefing block, and `.colophon`.
- **Page CSS in its own file** (`assets/css/<page>.css`), loaded after
  `styles.css`. Page-scoped `:root` overrides (accent re-theme, new
  single-purpose tokens) go here — never in `styles.css`.
- **Page JS in its own file** (`assets/js/<page>.js`), vanilla, wrapped in an
  IIFE, `defer`red, no dependencies. Also include the shared `main.js`.
- **Canvas pattern:** a `.stage` container (bordered, `aspect-ratio`,
  `touch-action: none`) holding the `<canvas>` plus a DOM `.hud` overlay for
  crisp text (chips, score, centered `.msg` overlays). The canvas reads its
  drawing palette from the CSS tokens via `getComputedStyle` so it stays
  in-system, and scales for high-DPI displays.
- **Telemetry as a stat matrix:** live readouts use the `.conditions` /
  `.stat` bordered grid, mirroring the homepage matrix language.
- **Controls:** keyboard + pointer + touch; visible buttons for pause/end/
  restart; construction-flavored copy (corridor, grade, crosswind, site
  conditions, furthest run — not flying/rocket language).
- **Persistence:** namespaced `localStorage` keys, e.g. `nbdf.excavator.best`.
- **Project status section** near the bottom: stage/version panel + a
  `.objectives` checklist of learning objectives (done ✓ / todo ☐).

## 11. Accessibility expectations

Every page must have:

- A `.skip-link` as the first element in `<body>`, targeting the main section.
- Landmark elements (`header`, `nav` with `aria-label`, `main`, `footer`) and
  heading levels in order (`h1` → `h2` → `h3`, one `h1` per page).
- `aria-labelledby` on sections; `aria-current` on the active nav link;
  `aria-expanded`/`aria-controls` on the mobile menu toggle.
- `aria-hidden="true"` on decorative elements (icons, thumbs, dots, arrows).
- `:focus-visible` outlines are provided globally (2.5px accent) — don't
  suppress them.
- `prefers-reduced-motion` is respected globally — don't add animations that
  bypass it.
- Interactive canvases get `role="img"` and an `aria-label` that names the
  controls; every pointer interaction needs a keyboard equivalent.
- Contrast: `--muted`/`--faint` are for secondary/large text only; primary
  copy is `--ink` on light surfaces (WCAG AA).
- Real `<table>`s for tabular data (see the lab log), wrapped in `.table-wrap`
  for horizontal scroll.

## 12. Responsive / mobile expectations

Breakpoints (max-width, in `styles.css` — extend, don't replace):

| Breakpoint | Behavior |
|------------|----------|
| `> 860px`  | Full layout: rail + content, 3-column grids |
| `≤ 860px`  | Matrix and projects drop to 2 columns |
| `≤ 760px`  | Rail collapses to a top bar with Menu toggle; hero stacks; spec's dashed border moves from left to top |
| `≤ 540px`  | Single-column grids; buttons stretch full width; game stage switches to 4:3 |

- Layout never requires JavaScript; the menu toggle is progressive
  enhancement.
- Cell-matrix components need their border `:nth-child` rules re-declared per
  breakpoint (copy the existing pattern).
- Test at 375px width (phone) before calling a page done.

## 13. Do / don't guidance for future AI assistants

**Do**

- Read `styles.css` and copy existing component markup before writing anything.
- Reuse shared classes; compose new UI from existing primitives.
- Put page-specific styles/tokens in a page-scoped CSS file loaded after
  `styles.css`.
- Use relative asset paths (`assets/...`), matching the existing pages.
- Keep copy in the workshop voice: plain, factual, status-labeled.
- Keep changes minimal and targeted; prefer editing one file over three.

**Don't**

- Don't introduce frameworks, build steps, npm, CDNs (other than Google
  Fonts), or external image assets when CSS/canvas shapes will do.
- Don't hard-code colors, fonts, or radii — use the tokens.
- Don't change `styles.css` `:root` values to restyle one page.
- Don't use blurred drop shadows, gradients, or rounded-pill buttons — the
  language is hard offset shadows, flat surfaces, and bordered rectangles.
- Don't renumber or reorder existing homepage sections when adding entries.
- Don't add a page without linking it from the homepage (rail entry and/or
  project card).
- Don't touch `404.html`'s absolute paths (they're intentional).

## 14. Checklist for creating a new page

1. [ ] Copy the head block from an existing page (meta, OG, favicon, fonts,
       `styles.css`, then your page CSS).
2. [ ] Build the skeleton: `.skip-link` → `.shell` → `.rail` + `main.content`
       → `.colophon` → `main.js` (defer) → page JS (defer).
3. [ ] Rail: brand row, `.rail__home` back link, page-local numbered nav
       (`01 · …`), `.rail__meta`.
4. [ ] Hero: `.hero__kicker` (`// something`), `h1.hero__title`, lede,
       `.hero__actions` (one `.btn--primary`), `.spec` briefing block.
5. [ ] Number every section with an `.eyebrow` and match the rail nav.
6. [ ] All asset paths relative; no hard-coded colors; tokens only.
7. [ ] Accessibility pass: skip link, landmarks, heading order, aria on nav
       and decoratives, keyboard support for anything interactive.
8. [ ] Responsive pass at 860 / 760 / 540 / 375 px.
9. [ ] Link the page from the homepage: rail entry `NN · Name` and (if it's a
       project) a `.card` in the Projects grid with an honest status label.
10. [ ] Test by opening the file directly from disk **and** via
        `python -m http.server 8000`.
