# vpn-console Design System — MASTER

**Direction**: 12 · Quiet Cloud HQ ("quiet chrome" — the Linear/Stripe school)
**Status**: Ratified 2026-10-10 by owner pick from the 20-direction gallery
**Source gallery**: `mockups/twenty-directions.html` (board 12) · UX rules: `../research/vpn-dashboard-ux.md` · Requirements: `../specs/001-unified-vpn-dashboard/spec.md`

Every screen MUST conform to this file. Deviations require an override file in
`design-system/overrides/<page>.md` stating what and why — never inline one-offs.

---

## 1. Design thesis

Calm, confident, dense-when-needed. White cards on a cool near-white ground, hairline
borders, one indigo accent, semantic color reserved for meaning. The dashboard is an
instrument, not a showpiece: quiet chrome, generous padding discipline, `⌘K` everywhere.
Dark mode is the same design re-stepped, not inverted.

## 2. Tokens

### Light (default)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#F7F8FA` | app ground |
| `--surface` | `#FFFFFF` | cards, tables, drawers, dialogs |
| `--surface-2` | `#F1F3F6` | hovered rows, inset wells, code blocks |
| `--border` | `#E5E8EC` | 1px card/table separators |
| `--border-strong` | `#D3D8E0` | inputs, interactive outlines |
| `--text` | `#0F172A` | primary ink |
| `--text-muted` | `#64748B` | secondary ink, labels |
| `--accent` | `#4F46E5` | primary actions, active nav, links, focus |
| `--accent-hover` | `#4338CA` | |
| `--accent-soft` | `rgba(79,70,229,.09)` | active-nav fill, selected rows |
| `--info` | `#0EA5E9` | tailnet-scoped exposures, informational |
| `--success` | `#16A34A` | healthy states |
| `--warning` | `#D97706` | caution (expiring, pending, stale) |
| `--danger` | `#DC2626` | errors, expired, internet-facing |
| `--ring` | `rgba(79,70,229,.35)` | focus ring halo |

### Dark (theme toggle; equal first-class citizen)

| Token | Value |
|---|---|
| `--bg` | `#0F1117` |
| `--surface` | `#161922` |
| `--surface-2` | `#1D212D` |
| `--border` | `#262B38` |
| `--border-strong` | `#333A4C` |
| `--text` | `#E6E8EF` |
| `--text-muted` | `#8B90A0` |
| `--accent` | `#818CF8` |
| `--accent-hover` | `#A5ACFA` |
| `--accent-soft` | `rgba(129,140,248,.13)` |
| `--info` | `#38BDF8` |
| `--success` | `#2FBF71` |
| `--warning` | `#F5A524` |
| `--danger` | `#EF4444` |
| `--ring` | `rgba(129,140,248,.4)` |

### Type

| Role | Face | Notes |
|---|---|---|
| Display / headings / tile values | **Manrope** 600–800 | `-0.01em` tracking; page title 20px/700 |
| Body / UI | **Inter** 400–600 | base 14px; table body 13px; line-height 1.5 |
| Data / mono | **Geist Mono** 400–500 | IPs, hostnames, IDs, timestamps, search queries, log lines; `tabular-nums` in numeric columns |

Scale: 11 (chips/labels, `+0.1em` uppercase for micro-labels) · 12.5 (secondary) · 13 (tables) ·
14 (body) · 16 (section titles) · 20 (page title) · 26 (tile values).

### Surface & space

- Radius: **12px** cards/drawers/dialogs · **8px** inputs/buttons/chips-pill · **999px** pills.
- Shadow: `0 1px 2px rgba(15,23,42,.05), 0 8px 24px -14px rgba(15,23,42,.14)` on floating
  layers only (drawer, dialog, dropdown) — flat cards carry borders, not shadows.
- Spacing: 4px base; card padding 16–20px; page gutter 24px; table rows 42–46px.
- Motion: 150–200ms ease-out on hover/focus/press; drawer 220ms slide; **no** decorative
  animation; respect `prefers-reduced-motion`.
- Icons: Lucide SVG, 1.5px stroke, 16px inline / 18px nav. Never emoji as icons.

## 3. Status system (binding — spec FR-052)

Status is **always icon/dot + text label**, never color alone. Only these five states:

| State | Token | Dot/icon | Label | Examples |
|---|---|---|---|---|
| Healthy | `--success` | ● | `Online` `Valid` `Running` `Applied` | device online, cert > 14d |
| Info/tailnet | `--info` | ◐ globe icon | `Tailnet` | Serve/Taildrive entries |
| Caution | `--warning` | ● triangle | `Expiring in 6d` `Needs approval` `Stale` | ≤ 14d expiries, pending routes, restarts |
| Error/internet | `--danger` | ● octagon | `Expired` `Failed` `Parse error` `Public` | expired certs/keys, failed units, **Funnel** |
| Inert | `--text-muted` | ○ | `Offline` `Disabled` `Unexposed` | offline devices, disabled profiles |

Red appears ONLY on error/internet-facing states; the Exposures tile's public count is the
one red number on Overview. Severity striping uses tinted backgrounds at 8–10% of the state
color, never saturated fills. Chips: 11px mono, 1px state-tinted border, transparent fill.

## 4. Components

**Buttons** — `Primary` (accent fill, white text) for the one main action per view
(`Import profiles`, `Apply policy`); `Secondary` (surface fill, 1px border) for the rest;
`Danger` (danger fill, white) only inside destructive dialogs; `Ghost` (no fill) for row
actions. Row-level dangerous actions live behind a `⋯` menu — never naked red icon buttons.

**Inputs & search** — 36px, 8px radius, `--border-strong` border, focus = 2px `--ring`
halo. The global search accepts `key:value` tokens (`os:` `tag:` `is:expiring` `!` negation);
rendered query tokens as mono chips with an ✕ each; `⌘K` opens the command palette.

**Tables** — the page. Surface card, hairline row separators, 42–46px rows, header row in
11px mono uppercase muted. Status column first, name second, `⋯` menu last. Sort on click;
filters as saved-query chip row above; count + refresh state in the table footer
("23 devices · updated 4s ago"). `tabular-nums` for dates/IPs. Copy-on-click cells flash
a ✓ and toast nothing.

**Stat tiles** — label (11 mono uppercase muted) / value (26 Manrope 700, secondary part
in muted 13px) / sub-row of chips. Click-through to the filtered list. Badge chips on
top-right when attention is needed.

**Drawer** (profile/device detail) — right-side, 480px, surface, 24px padding, slides
220ms; header = name (editable) + status chip + close; sections separated by hairlines;
actions pinned in the footer bar.

**Dialogs — friction tiers (spec FR-051)** — Confirm modal: specific body naming the
target and consequence, outcome-labeled buttons (`Delete profile` / `Keep it`), no default
focus. Type-to-confirm: input must match the target name / `DELETE` before the danger
button enables; used for delete device, bulk delete, tailscaled disconnect (adds the
self-lockout warning + "I am connected via LAN" checkbox), danger zone. No confirm at all
for undoable local ops — those get **toasts**: bottom-left, 10s, neutral with green dot,
`Undo` button; failures red with `Retry`.

**Command palette** (`⌘K`) — fuzzy jump-to-page/action/profile/device; lists recent
actions; `↵` runs, `esc` closes.

**Empty states** — one sentence of explanation + exactly one primary CTA ("No profiles
yet. Drop `.ovpn` files here or **Import**."). Attention queue empty = "All clear."

**Health banner** — per-subsystem: reachable (no banner), stale ("Tailscale API
unreachable — showing data from 2 min ago", warning tint, mutations disabled), unavailable
(danger tint, empty panel with Retry).

## 5. Shell

Left sidebar 224px: brand dot + `vpn-console`; the ten sections in spec order (Overview,
Profiles, Devices, Access Control, Local Node, Exposures, Services, Logs, Audit Log,
Settings) with Lucide icons + count pills; active = `--accent-soft` fill + accent text +
3px left indicator; admin chip + health dots pinned bottom. Topbar 52px: search (flex-1,
max 420px), subsystem health dots (`ts api · local · host`), theme toggle, sign out.
Content column max 1240px. Responsive: sidebar collapses to icon rail < 1024px, hidden
behind hamburger < 720px; tables scroll horizontally inside their card; nothing else
changes order.

Page rhythm: title row → **attention/action block** → tables/tiles → secondary. Overview
order is fixed by spec FR-030.

## 6. Accessibility & pre-delivery checklist

Text contrast ≥ 4.5:1 (large 3:1) in BOTH themes · visible `:focus-visible` ring on every
interactive element · hit targets ≥ 36px (44px on touch) · status never color-alone ·
`aria-label` on icon-only controls · tables have real `<th>` scope · live regions announce
toast/health changes · reduced-motion honored · keyboard path for every action including
dialogs (focus trap + `esc`) · tabular data readable at 375px via in-card scroll.

Pre-delivery: no emoji icons · cursor:pointer on clickables · 150–300ms transitions ·
4.5:1 in light AND dark · visible focus · reduced-motion · 375/768/1024/1440 checked ·
live data labeled with update time and stale state.

## 7. Overrides

Per-page exceptions go in `design-system/overrides/<page>.md` — what, why, and the
master rule it bends. No page may redefine tokens, status semantics, or friction tiers;
those are constitutional (Principles III & IV, V).
