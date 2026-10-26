# Chibi-Agent

Raphael, an agentic desktop companion (look and voice inspired by Tensura's
Raphael, not the Great Sage lore), lives on the Windows desktop as a local agent
for Saber (the user's nickname, formerly Kryo; "Sir" when serious): voice in and out, memory, desktop tools with confirmation,
calendar/mail briefings and on-demand screen reading. She has two Live2D forms:
chibi (idle/chat) and serious (work, alerts, on command). Python, all local.
Budget: keep this file under ~500 tokens.

## Read first
- `docs/scope.md`: what v1 does and doesn't do, models, VRAM and latency budgets.
- `docs/character.md`: her look, the two forms, the rig pipeline (our own art, Live2D Cubism + live2d-py), moods, persona, voice.
- `docs/architecture.md`: the overlay / agent / voice / Ollama processes, the WS protocol, tools, memory, VRAM manager, safety, repo layout, spikes.
- `DEVIATION.md`: only for the Saber-Theme mascot behaviour logic to port (brain, physics, briefing). Its Kotlin and Saber parts are superseded.
- Prior art (read, don't copy; it has no licence): https://github.com/shogunyan12/The-GREAT-SAGE

## House rules
- Every side-effect tool goes through the confirmation gate. No file deletes in v1.
- The voice is cloned from Raphael's original voice lines, for personal use only. The reference clips, outputs and tuned models never go into git and are never shared, published or used to impersonate the actress (`docs/character.md` → Voice).
- The overlay renders on the dGPU (~300 MiB reserved: the 4060 drives the primary monitor); the rest is for Ollama, F5-TTS and Whisper.
- Results of the first spikes: `docs/spikes.md`.
- Model weights, venvs, rig art, voice references and audio caches stay out of git. They live in `D:\Projects\Chibi-Agent-Project\ChibiAgent\` (beside the repo; moved off F:, an external SSD that can disconnect).
- Test on this laptop (RTX 4060 Laptop 8 GB + Radeon 780M, two 60 Hz screens).
- Plan mode for anything touching more than ~3 files; broad sweeps go to `explorer`.

## Commands
- Run her: `python chibi.py` (agent starts Ollama, overlay, voice). One instance only (mutex).
- Setup: `uv sync` in `shared/`, `agent/`, `overlay/`, `voice/` (each has its own venv).
- Tests: `uv run pytest` in each package; `agent/tests/test_cases_live.py` needs Ollama.
- Google (M5): Kryo saves the Desktop OAuth client JSON as `%APPDATA%\ChibiAgent\google_client.json`, then tray → Google accounts → Add Google account… once per account. Refresh tokens in Credential Manager (`ChibiAgent`, `google:<email>` + `google:accounts`).
- Debug: `python -m chibi_agent --without voice|overlay`; `python -m chibi_overlay --debug-throw VX,VY`.
- 3D body (Godot 4.7 renderer driven by the overlay; tray switches 2D/3D): `overlay3d/README.md`. Test overlays get their own empty APPDATA/LOCALAPPDATA, or they knock the running overlay off the agent.
- Processes started from the Claude app write AppData into `Packages\Claude_*\LocalCache` (MSIX); the user's real logs are in `%LOCALAPPDATA%\ChibiAgent\logs`.
