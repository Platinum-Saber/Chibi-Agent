# Chibi-Agent

Desktop version of the chibi Saber mascot from the Android launcher
Saber-Theme. Saber lives on the Windows desktop as a transparent,
always-on-top window and acts as an agent. The agent is a local LLM on the
RTX 4060 with tool calls, memory, and voice in and out. Greenfield: nothing
is built yet. Budget: keep this file under ~500 tokens.

## Read first
- `DEVIATION.md`: the reference to the Android mascot, what is carried over,
  changed or dropped, the target machine's specs, the VRAM budget, the
  suggested shape and the first spikes. **Start here.**
- Reference repo (read-only, copy from it, never edit it):
  `D:\Projects\Mobile Applications\Saber-Theme`
  - Mascot code: `feature/mascot/src/main/java/com/sabertheme/feature/mascot/`
    (`Pose.kt`, `SaberRig.kt`, `MascotBrain.kt`, `MascotPhysics.kt`, tests).
  - Docs: `docs/architecture.md` (sections "Mascot" and "Briefing"),
    `docs/plans/m4-mascot*.md`, `handoffs/m4-mascot-and-polish.md`,
    `handoffs/mascot-followups.md`, `handoffs/briefing-phase1.md`.
  - Never read its signing material or `local.properties`.

## Direction (confirm in plan mode before building)
- `app/`: Kotlin + Compose Multiplatform Desktop. Window, rig, brain,
  physics, input, plus Win32 glue (click-through, taskbar floor) via JNA.
- `agent/`: a Python 3.12 venv (uv; not the system 3.14). Runs the
  llama.cpp CUDA server, the agent loop with tools, Whisper STT, Kokoro TTS
  (bf_emma) and SQLite memory. It talks to `app/` over a local WebSocket.
- The brain owns her body: the agent only requests moods.
- Models: 4–8B Q4 only (8 GB VRAM, single-channel RAM). Model files go on
  E: or F:, never in the repo.

## Output
- No preamble, no recap. Lead with the answer or the diff.
- Plan mode for anything touching more than ~3 files.
- Broad sweeps go to the `explorer` agent.

## House rules
- Test on this laptop (Windows 11, RTX 4060 Laptop + Radeon 780M). Render
  her window on the iGPU; leave the dGPU to the model.
- Side-effectful agent tools (files, apps, messages) ask the user first.
- Keep model weights, venvs and audio caches out of git.
- Once commands exist (build, run, test), add them here.
