# Handoff: finishing v1 after M5

**Goal:** close the last v1 scope items (`docs/scope.md`) and pass its v1 success criteria.

## Decisions
- Kryo is the user ("Sir" when serious, never "Master"). Code words briefings and warnings; the 4B model only labels one item at a time.
- Google OAuth stays in **Testing** (Production needs public home page and privacy URLs). Sign-ins expire after 7 days and that account is dropped until Kryo re-adds it from the tray. Three accounts; the university one is Workspace.
- Mail and calendar text is untrusted. The store keeps sender name, subject and label only; logs record untrusted results as a length only.
- Morning briefing: first start after 06:00, or 07:30. Urgent warnings: 07:00–23:00, not gaming or mid-turn, mail under 2 h old (`[briefing]` in `config.toml`).
- Kryo's user env sets `OLLAMA_MODELS=D:\Projects\Chibi-Agent-Project\ChibiAgent\ollama`, because the Ollama tray app's server owns port 11434.
- From the Claude app, writes to `%APPDATA%` land in the MSIX cache, so give Kryo commands to run. `git push` is blocked here, so Kryo pushes.

## Files
- `agent/chibi_agent/google_auth.py`: per-account sign-in; keyring `google:<email>` plus the `google:accounts` index.
- `agent/chibi_agent/tools/{_google,calendar,gmail}.py`: parallel per-account fetch; `calendar_events`, `mail_list`, `read_mail`.
- `agent/chibi_agent/{mail_labels,briefing,mailwatch}.py`: labeller, pure composer, polling, Briefer, MorningBriefing.
- `agent/chibi_agent/orchestrator.py`: turn loop, `report()`, regex commands (form, "briefing").
- `agent/chibi_agent/persona.py`: the prompt is **2,953/3,000** characters (a test in `test_gmail.py` checks it); a new tool needs shorter descriptions elsewhere.
- `handoffs/m5-and-m6-followups.md`: M5 and M6 details.

## State (branch `v1` at 405e062; Kryo pushes)
- **Works and tested:** M1–M6; Calendar and Gmail across 3 accounts; labelling, urgent warnings, the briefing on demand and in the morning. Tests: 158 agent, 32 shared, 74 overlay, 18 voice.
- **Left for v1:**
  1. ~~Windows notifications~~: done (`notifywatch.py`, Spike 4 in `docs/spikes.md`). Kryo tested it live 2026-10-17. The overlay ignores `cloud` until item 2. The spoken command is now **"status report"** (Whisper heard "briefing" as "breathing"); "report" and "briefing" still work.
  2. The thought cloud on the overlay (not started).
  3. Her own Live2D rigs: the overlay still uses the Haru/Mao samples (`[overlay]` in config; pipeline in `docs/character.md`). This is art work Kryo drives; see `handoffs/live2d-rigs.md`.
  4. Acceptance pass against scope.md's success criteria (started 2026-10-17):
     - **Voice commands ✅** (by text, model only): "Open Spotify", "What's on today?" and "Look at this." each went 10/10. "Look at this" was 1/10 until the `look_at_screen` description named the phrase (prompt now 2,977/3,000). `cases.yaml` has calendar, mail, reminder and a mail-injection case, and scores 30/30 (`test_cases_live.py`).
     - **Confirmation ✅:** registry and gate tests pass. Only `media` and `set_volume` skip the yes, as scope.md says; `remember`, `set_reminder` and `cancel_reminder` ask first now (Kryo's call).
     - **Kryo by hand:**
       - **Latency:** 10 warm voice turns. Count the "first audio X s after release" lines in `agent.log`; the target is ≤ 1.5 s in 8/10.
       - **Memory:** tell her a fact today, then check tomorrow that she brings it up unprompted when it's relevant.
       - **Overlay:** 60 fps, clicks pass through next to her, no stolen focus. Spike 1 / M6 numbers exist; re-check with the real app.
       - **Gaming mode:** measured in M6 (0.3 s); one spot check with a real game is enough.
  5. ~~Drag and throw onto a title bar and monitor 2~~: Kryo tested every case, 2026-10-17.
- **Optional:** Moodle deadlines; Spotify playlists (Web API + Premium); battery saver; re-time a calendar question and a gaming-mode turn; watch whether Moodle notices get labelled `promo`.

## Next step
Finish item 4's by-hand checks (memory recall needs a second day), then the thought cloud (item 2).

## Status check (2026-10-27, `svg-rig` at 8edff57)
Docs brought up to date with the commits since 833cdd1 (script tools, Customize window, sprite-pack chibi, panels and core, music detection, restart, reset_memory, voice start-up, protocol rows). Tests: shared 40, agent 198, voice 37 pass; overlay 225 pass (the font-picker failure was the offscreen test platform finding no fonts, fixed in f40b867; not the `hud.py` work).

**Success criteria (scope.md):**
| Criterion | State |
|---|---|
| Voice commands ≥ 9/10 | ✅ 10/10 each by text (2026-10-17); live cases 32/33 with tool selection |
| Confirmation | ✅ registry and gate tests pass |
| Latency ≤ 1.5 s in 8/10 warm | ❌ not met in real use. `agent.log` "first audio" lines: 52/170 under 1.5 s overall, 7/17 on 2026-10-26 (several 2–3 s, outliers 14–21 s that look like cold F5 loads, e.g. after memory relief drops it). The log doesn't mark warm turns, so a dedicated 10-warm-turn run is still owed |
| Memory recalled next day | ❓ not checked; `reset_memory.py` cleared the store on 2026-10-26, so start the two-day check fresh |
| Overlay 60 fps, click-through, no focus steal | ❓ vsync on AC / 30 fps on battery in `overlay.log`; no measurement with the real app. The 3D body costs ~580 MiB VRAM (Saber allowed 800 MB) against the ~300 MiB budget |
| Gaming mode VRAM ≈ 0 in 5 s | ⚠️ 0.3 s measured in M6; "freeing VRAM" fires live (also for fullscreen Edge), but no spot check with a real game |

**Scope items still open:**
- Thought cloud: the agent sends `cloud`, the overlay doesn't draw it (the "…" text cloud is gone too).
- Her own rigs: chibi done (robe v21 Live2D, casual-coat sprite pack); the **serious form is still the Mao sample** in every 2D outfit.
- Optional, not started: Moodle deadlines, battery saver (only the 30 fps cap exists).

**Built beyond v1 scope:** the 3D body (scope said after v1), memory relief, voice reactions and UI sounds, the pose wheel, the Recycle Bin and network tools, the Customize window.

**Verdict:** v1 is not complete. Left: latency (fix or re-measure), the memory and overlay checks, the thought cloud, the serious rig.
