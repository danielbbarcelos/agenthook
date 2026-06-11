# agenthook · design system

Reference design for the terminal interface (TUI), delivered by Claude Design and
distilled here as the implementation source of truth.

## Chosen direction — **Variant A · Guided**

The design was explored in three takes per screen: **A · Guided** (menu + status,
single column), **B · Cockpit** (live Textual dashboard, dense two-pane), and
**C · Minimal** (command palette, airy). **We go with A · Guided.**

Guided stays close to what exists today (arrow-key menus, single column, calm
spacing) and fixes the five real pains without forcing a Textual rewrite:
getting lost in deep menus, no live view of a running job, an intimidating
instance/auth setup, weak state feedback, scrollback turning to soup. Cockpit
ideas (live tables, split panes) are kept as **future Textual candidates** —
flagged per screen, not built now.

## Files

| File | What it is |
|------|------------|
| `agenthook-tui-design.html` | **The spec** (Guided). 15 sections: palette, patterns, nav map, every screen as an ASCII mockup with interaction + microcopy notes. Open in a browser. |
| `agenthook-tui-variations.html` | A/B/C comparison per screen. ⚠️ Renders blank — depends on `variation-screens.js`, which came over empty. Re-export from Claude Design if the comparison is needed. |
| `design-canvas.jsx` · `terminal.css` | Render scaffolding for the HTML mockups. |
| `variation-screens.js` | **Empty (0 bytes)** — the `window.VS` screen bodies were not exported. |

---

## Palette — ANSI roles

Warm amber on near-black earth. Color always pairs with a glyph or word, so
meaning survives on a no-color terminal. **Brand shifts from lilac to amber**;
lilac is now reserved for plan/session only.

| Role | Hex | Name | Use |
|------|-----|------|-----|
| highlight / brand | `#d9a441` | amber | selection, pointer `●`, focused field, "you are here / act here" |
| ok / success | `#a3be8c` | sage | completed jobs, logged-in auth, confirmations, passing checks |
| info / response | `#88c0d0` | cyan | agent replies in chat, hints, neutral values, links |
| warning / awaiting | `#d08770` | clay | `awaiting_approval`, `blocked`, `failed-checks` — needs a human |
| error / failed | `#bf616a` | rust | `error`, `timeout`, destructive confirms, missing auth |
| plan / session | `#b48ead` | lilac | plans awaiting review, durable sessions/threads — the "thinking" hue |
| muted | `#6f6a5d` | stone | back `←`, quit, secondary labels, separators, nav hints, queued |
| foreground | `#e8e3d8` | bone | default body text on `#15140f` background |

## Glyphs & affordances

```
●  selected option (pointer, amber bold)     ←  back (muted, always last)
?  question / prompt (cyan)                   ✓  done / success (sage)
▲  needs attention (clay)                     ✗  failed / error (rust)
▸  running step (amber)                       ·  pending step (stone)
◷  awaiting (clay/lilac)                       ◆  agent action / reply (cyan)
↑↓ / j k move · ↵ select · esc back · / filter · q quit (main only) · ctrl-c cancel
```

## Status vocabulary — one set of colors everywhere

```
instance   ● active        ⏸ paused        ⚠ no auth
job        queued · running · awaiting_approval · success
           failed-checks · blocked · error · timeout · interrupted
auth       logged in   via api-key   not logged in
```

---

## Interaction patterns (cross-cutting)

- **Two levels, always.** Every screen is reachable by a dry command (for
  automation/CI) and a friendly menu path. Bare `agenthook` opens the main menu;
  any required arg omitted opens a **picker** for it. Pickers are searchable (`/`).
- **Screen-clear rule.** Clear+redraw on *big* transitions (entering a top
  section, opening view/edit, launching chat/shell). Keep+append on *small* ones
  (wizard pages, sequences of prompts, confirmations) so context stays visible.
- **Breadcrumb.** First line after every clear, dimmed:
  `agenthook ▸ instances ▸ api-bot ▸ edit`.
- **Box style:** rounded `╭─╮`. Tables: header + rule, no vertical borders (light
  at 80 cols). Target responsive 120 → 80 cols.

## Navigation map

```
agenthook                  (bare → main menu; clears once on entry)
├─ instances
│   · interact:     chat · shell
│   · manage:       add (wizard) · view · edit
│   │     edit → deliverable · engine · model · branch base
│   │            authentication ► · repositories ► · env vars ► · pause/resume
│   · list/remove:  list · remove (⚠ confirm)
├─ jobs             list [--watch] · view · approve · logs [--follow] · cancel
├─ sessions         list · view <thread-key>
├─ serve            [--port 8080]   (promoted to the main menu)
└─ quit
```

---

## Screens (see the HTML for full mockups) & gap vs current code

| # | Screen | Status vs `agenthook/tui.py` |
|---|--------|------------------------------|
| 04 | Entry banner + main menu | **Change**: new chain logo `●─╮ / ╰─●─╮ / ╰─●`; amber brand; status line (`N instances · running · queued · server ● up`); add `serve` item. |
| 05 | Instances submenu (grouped) | Mostly built; align labels/microcopy, add descriptions per item. |
| 06 | Add instance — **guided wizard** | **New**: progress rail (`step N/8`), one decision per page, completed steps collapse to chosen values; framed one-time encryption-key step that blocks until confirmed. |
| 07 | View instance | Built; restyle to sectioned single column + header status line + recent-jobs strip. |
| 08 | Edit instance | Built; show current value beside each field; group config / connections / state; `pause ⇄ resume` toggle; `← done`. |
| 09 | Instance authentication | Built; add framed status panel with `scope: this instance only`; verbs: switch / relogin / logout. |
| 10 | Env vars editor | Built; restyle; `Secret?` default **Y**. |
| 11 | Repo pool editor | Built; restyle; validate repo against auth on add. |
| 12 | Jobs — live list | **New** (`--watch`, 2s refresh, row actions). Prime **Textual** candidate. |
| 13 | Job runner + plan approval | **New**: stepped rail (clone→plan→edit→checks→deliver), stats line (elapsed·cost·tokens), agent-log tail, inline approve/edit/reject. **Textual** candidate. |
| 14 | Sessions — list + thread view | **New**: thread view with context + job history + **resume in chat**. |
| 15 | Chat REPL & shell | Built; restyle banners (`ephemeral container`, isolation note), agent replies cyan `◆`. **Textual** candidate. |

**Net-new work** the design introduces beyond today's TUI: amber palette + new
logo, breadcrumbs, `serve` in the menu, the add-wizard progress rail, the jobs
live list, the job runner / plan approval, and the sessions thread view.
