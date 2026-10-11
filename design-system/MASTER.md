# vpn-console Design System — MASTER

**Direction**: D · Topology, orange accent
**Status**: Ratified 2026-10-11 by owner pick (replaces 12 · Quiet Cloud HQ, ratified 2026-10-10)
**Source**: restyle comparison (directions A Signal · B Fieldnote · C Rack · D Topology); owner chose D with orange in place of cobalt
**Implementation**: `server/static/styles.css` (tokens are binding) · UX rules: `../research/vpn-dashboard-ux.md`

Every screen MUST conform to this file. Deviations require an override file in
`design-system/overrides/<page>.md` stating what and why — never inline one-offs.

---

## 1. Design thesis

Airy and modern: white panels with soft shadows on a cool off-white ground, generous
radii, one orange accent. The orange marks *where you are and what you can do* (active
nav, primary buttons, focus, meters, the network-path wires). Semantic color marks *state*
and is never the accent. Dark mode is the same design re-stepped, not inverted.

## 2. Tokens

### Light (default)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#F6F7F9` | app ground |
| `--surface` | `#FFFFFF` | cards, tables, drawers, dialogs, sidebar |
| `--surface-2` | `#F2F4F7` | table headers, wells, search field |
| `--surface-3` | `#E9EDF2` | segmented-tab track, meter track |
| `--border` / `--border-strong` | `#E4E7EC` / `#D0D5DD` | separators / inputs |
| `--text` / `--muted` / `--faint` | `#101828` / `#475467` / `#667085` | ink levels (all ≥4.5:1 on white) |
| `--accent` | `#EA580C` | marks: active icons, focus ring, meters, wires |
| `--accent-strong` | `#CC4A0C` | primary button fill + link text (white text ≥4.5:1) |
| `--accent-soft` | `#FFF1E8` | active nav background, selected rows |
| ok / warn / err / info | `#12A150` / `#D4A20B` / `#E5484D` / `#2E6FD8` | dots, bars |
| `*-text` variants | `#0E7A3D` / `#8A6800` / `#C4232F` / `#2559B0` | semantic text on light |

Warning is **mustard**, not amber: it must stay ~25° of hue away from the orange accent
so a "Due" pill never reads as a brand mark.

### Dark

`--bg #0E1014`, `--surface #15181E`, `--surface-2 #1C2027`, accent `#FF8A4C` (button
text uses `--accent-ink #1A0B02`), semantics re-stepped brighter. Applied both under
`prefers-color-scheme: dark` (theme = System) and `[data-theme="dark"]`.

### Shape and type

- Radii: card 16px · item/input 10px · pill 999px. Controls are 38px tall (`.sm` 32px).
- Shadow: `--shadow-card` on cards/tiles; `--shadow-overlay` on dialogs, drawers, toasts.
- Type: **Schibsted Grotesk** (UI + display), **JetBrains Mono** (addresses, units, versions,
  audit actions). Both vendored in `server/static/fonts/` — no runtime font CDN.
- Scale: h1 26 · h2 15 · body 14 · labels/meta 12.5 · eyebrow 10.5 uppercase +0.09em.

## 3. Layout rules

- Sidebar grouped by domain: Overview · **OpenVPN** · **Tailnet** · **This host** · **Admin**.
- Top bar: page name · search (⌘K) · subsystem health as dot + label (dots only on phones).
- Overview order: Network path (public → host → Tailscale / OpenVPN tunnels) → five stat
  tiles (equal height, values never wrap) → Needs attention | Recent activity.
- Grids collapse: 5 tiles → 3 (≤1240px) → 2 (≤900px) → 1 (≤340px); splits stack ≤1080px;
  sidebar becomes an off-canvas drawer ≤900px. No horizontal page scroll at any width;
  wide tables scroll inside their own wrapper.
- Tabs are segmented controls (white thumb on a `--surface-3` track).
- Filter fields are full-width search fields with the icon inside the field.

## 4. Status language (unchanged)

State is always dot + label, never color alone. Red is reserved for broken or
internet-facing (Funnel). Blue (info) marks tailnet scope.
