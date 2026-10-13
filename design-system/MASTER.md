# vpn-console Design System — MASTER

**Direction**: D · Topology, orange accent, quiet pass (anti-slop)
**Status**: Ratified 2026-10-11 by owner pick (replaces 12 · Quiet Cloud HQ, ratified 2026-10-10).
Quiet pass the same day: owner found the orange logo mark and glows "too vibey" and asked to
apply `miqdadbadjuber/anti-slop` + `Leonxlnx/taste-skill` (installed in `.claude/skills/`).
**Source**: restyle comparison (directions A Signal · B Fieldnote · C Rack · D Topology); owner chose D with orange in place of cobalt
**Implementation**: `server/static/styles.css` (tokens are binding) · UX rules: `../research/vpn-dashboard-ux.md`

Every screen MUST conform to this file. Deviations require an override file in
`design-system/overrides/<page>.md` stating what and why — never inline one-offs.

---

## 1. Design thesis

Quiet and modern: flat white panels with hairline borders on a cool off-white ground.
One burnt-orange accent, used only where it means "act here": primary buttons, links,
keyboard focus, toggles and checkboxes. Everything else is ink and gray. Semantic color
marks *state* and is never the accent. Dark mode is the same design re-stepped.

### Anti-slop rules (binding)

- **No glow**: no colored outer shadows on buttons, dots, nodes or icons; no radial orbs.
- **No invented logo**: the mark is Firezone's logo (owner's choice, 2026-10-11), stored
  verbatim as `server/static/firezone-mark.svg`. It is used flat (no shadow or glow) at
  26px beside the "VPN Console" wordmark, 32px on sign-in, and as the favicon.
- **Shadow only for things that float** (dialogs, drawers, toasts, ⌘K palette). Panels
  and tiles sit on the page: border only.
- **Accent is scarce**: never on nav state, meters, wires, counts or hover fills. Active
  nav = neutral fill + ink text.
- **Sentence case** labels; no uppercase tracked eyebrows.
- **Status tags are square** (4px radius), no capsule + dot + tint stacks.
- **Copy**: no em dashes in UI text; plain, specific sentences. "—" survives only as the
  empty-cell placeholder in tables.
- **Fonts, with reasons**: Schibsted Grotesk for UI (legible, has character without
  being the default); JetBrains Mono only for machine values (IPs, versions, unit
  names, audit actions) where tabular, unambiguous glyphs matter.

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
| `--accent` | `#EA580C` | focus outline, toggles, checkboxes |
| `--accent-strong` | `#CC4A0C` | primary button fill + link text (white text ≥4.5:1) |
| `--accent-soft` | `#FDF1EA` | rarely: selected states only |
| ok / warn / err / info | `#12A150` / `#D4A20B` / `#E5484D` / `#2E6FD8` | dots, bars |
| `*-text` variants | `#0E7A3D` / `#8A6800` / `#C4232F` / `#2559B0` | semantic text on light |

Warning is **mustard**, not amber: it must stay ~25° of hue away from the orange accent
so a "Due" pill never reads as a brand mark.

### Dark

`--bg #0E1014`, `--surface #15181E`, `--surface-2 #1C2027`, accent `#FF8A4C` (button
text uses `--accent-ink #1A0B02`), semantics re-stepped brighter. Applied both under
`prefers-color-scheme: dark` (theme = System) and `[data-theme="dark"]`.

### Shape and type

- Radii: card 12px · item/input/button 8px · tags 4px. Controls are 38px tall (`.sm` 32px).
- Shadow: `--shadow-card` is `none`; `--shadow-overlay` only on dialogs, drawers, toasts, palette.
- Type: **Schibsted Grotesk** (UI + display), **JetBrains Mono** (addresses, units, versions,
  audit actions). Both vendored in `server/static/fonts/` — no runtime font CDN.
- Scale: h1 26 · h2 15 · body 14 · labels/meta 12.5 · group labels 12 (sentence case).

## 3. Layout rules

- Sidebar grouped by domain: Overview · **OpenVPN** · **Tailnet** · **This host** · **Admin**.
- Top bar: page name · search (⌘K) · subsystem health as dot + label (dots only on phones).
- Overview order: Network path (public → host → Tailscale / OpenVPN tunnels; neutral 1px
  wires, host marked by an ink border) → five stat tiles (equal height, values never wrap,
  no progress meters) → Needs attention | Recent activity.
- Grids collapse: 5 tiles → 3 (≤1240px) → 2 (≤900px) → 1 (≤340px); splits stack ≤1080px;
  sidebar becomes an off-canvas drawer ≤900px. No horizontal page scroll at any width;
  wide tables scroll inside their own wrapper.
- Tabs are segmented controls (white thumb on a `--surface-3` track).
- Filter fields are full-width search fields with the icon inside the field.

## 4. Status language (unchanged)

State is always dot + label, never color alone. Red is reserved for broken or
internet-facing (Funnel). Blue (info) marks tailnet scope.

### Server tunnels (profiles)

A profile with a tunnel on this server shows the tunnel's state in the Status column in
place of its library status: **Connected** (green, with the tunnel address under it),
**Connecting** and **Stopping** (amber), **Failed** (red). Profiles without a tunnel keep
Valid, Expiring, Expired, Disabled or Parse error. A certificate badge (Expired, Expiring)
sits next to the date so a Disabled profile cannot hide a lapsed certificate.

Enable and Disable act on the real machine, so they always open a confirm dialog. Scripts
in a profile raise it to type-to-confirm with the profile name, and so does the first
Enable of a profile that signs in with a username and password: the Enable dialog collects
the credentials in the same step (a password is landing in a root-only file on the server),
with the username prefilled when the console already holds one. Credentials have their own
small section in the drawer; the password itself is never shown anywhere. A slow action shows one
flat progress line above the table (and inside the drawer for a save or revert); its
outcome is a toast when it worked and a dialog when it did not, because failures name
lines and log output that a 4 s toast cannot hold.
