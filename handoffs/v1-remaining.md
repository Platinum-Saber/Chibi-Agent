# Handoff: finishing v1 after M5

**Goal:** close the last v1 scope items (`docs/scope.md`) and pass its v1 success criteria.

## Decisions
- Kryo is the user ("Sir" when serious, never "Master"). Code words briefings and warnings; the 4B model only labels one item at a time.
- Google OAuth stays in **Testing** (Production needs public home page and privacy URLs). Sign-ins expire after 7 days and that account is dropped until Kryo re-adds it from the tray. Three accounts; the university one is Workspace.
- Mail and calendar text is untrusted. The store keeps sender name, subject and label only; logs record untrusted results as a length only.
- Morning briefing: first start after 06:00, or 07:30. Urgent warnings: 07:00–23:00, not gaming or mid-turn, mail under 2 h old (`[briefing]` in `config.toml`).
- Kryo's user env sets `OLLAMA_MODELS=F:\ChibiAgent\ollama`, because the Ollama tray app's server owns port 11434.
- From the Claude app, writes to `%APPDATA%` land in the MSIX cache, so give Kryo commands to run. `git push` is blocked here, so Kryo pushes.

## Files
- `agent/chibi_agent/google_auth.py`: per-account sign-in; keyring `google:<email>` plus the `google:accounts` index.
- `agent/chibi_agent/tools/{_google,calendar,gmail}.py`: parallel per-account fetch; `calendar_events`, `mail_list`, `read_mail`.
- `agent/chibi_agent/{mail_labels,briefing,mailwatch}.py`: labeller, pure composer, polling, Briefer, MorningBriefing.
- `agent/chibi_agent/orchestrator.py`: turn loop, `report()`, regex commands (form, "briefing").
- `agent/chibi_agent/persona.py`: the prompt is **2,953/3,000** characters (a test in `test_gmail.py` checks it); a new tool needs shorter descriptions elsewhere.
- `handoffs/m5-and-m6-followups.md`: M5 and M6 details.

## State (branch `v1` at dca3d88, pushed)
- **Works and tested:** M1–M6; Calendar and Gmail across 3 accounts; labelling, urgent warnings, the briefing on demand and in the morning. Tests: 158 agent, 32 shared, 74 overlay, 18 voice.
- **Left for v1:**
  1. ~~Windows notifications~~: done (`notifywatch.py`, Spike 4 in `docs/spikes.md`). Kryo tested it live 2026-10-17. The overlay ignores `cloud` until item 2. The spoken command is now **"status report"** (Whisper heard "briefing" as "breathing"); "report" and "briefing" still work.
  2. The thought cloud on the overlay (not started).
  3. Her own Live2D rigs: the overlay still uses the Haru/Mao samples (`[overlay]` in config; pipeline in `docs/character.md`). This is art work Kryo drives.
  4. Acceptance pass against scope.md's success criteria: add calendar and mail cases to `spikes/brain/cases.yaml`, run 10 warm latency turns, check next-day memory recall.
  5. Untested by hand: drag and throw onto a title bar and onto monitor 2.
- **Optional:** Moodle deadlines; Spotify playlists (Web API + Premium); battery saver; re-time a calendar question and a gaming-mode turn; watch whether Moodle notices get labelled `promo`.

## Next step
The acceptance pass (item 4), then the thought cloud (item 2).
