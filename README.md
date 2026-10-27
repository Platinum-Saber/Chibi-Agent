# Raphael (Chibi-Agent)

Raphael is a desktop companion for Windows that runs entirely on your PC. She lives on your taskbar as a chibi, talks with you by voice or text, remembers what you tell her, reads your calendar and mail when you ask, looks at your screen on request, and uses desktop tools (always asking before anything with side effects).

Current version: **0.1.1** ([changelog](CHANGELOG.md)).

## Install
1. Run `Raphael-0.1.1-setup.exe`. It installs for your Windows account only (no admin) into `%LOCALAPPDATA%\Programs\Raphael`.
2. Leave **"Download her models now"** ticked. Setup opens a console and:
   - builds her Python environments (uv brings its own Python 3.12);
   - installs [Ollama](https://ollama.com) with winget if it isn't there, then pulls `qwen3.5:4b` and `nomic-embed-text`;
   - downloads the Kokoro voice and Whisper `small.en`.

   That's about 4.5 GB and needs internet once. If it stops, run **Start → Raphael setup (repair)**; every step skips what's already done.
3. Start **Raphael** from the Start menu or the desktop icon.

### Requirements
- Windows 10 (2004) or 11, 64-bit.
- An NVIDIA GPU with 8 GB is recommended (her language model, speech recognition and the 3D body use it); she works slower on CPU only.
- About 10 GB of free disk space, and 16 GB of RAM.

## Using her
- **Talk:** hold **Alt+1** anywhere, speak, release. Or type in her text panel.
- **Look at the screen:** say "look at this", or press **Ctrl+Alt+S**.
- **Right-click her** for the pose wheel; drag and throw her; **Alt+drag** sets her home spot.
- **Tray icon:** show/hide, mute, gaming mode, outfit, Customize Raphael (moods, look, behaviour, voice), memory, Google accounts, restart, quit.
- **Settings:** `%APPDATA%\ChibiAgent\config.toml` overrides the defaults in the app's `config.toml` (copy a `[section]` and the keys you want to change).

## What ships, and what you can add
| Part | Shipped | Add your own |
|---|---|---|
| Chibi (2D sprite art) | yes | — |
| Voice | Kokoro (54 preset voices, Customize → Voice) | a custom F5-TTS voice: [docs/custom-voice.md](docs/custom-voice.md) |
| 3D serious form and the Rimuru / Raphael outfits | the renderer only, no models | a VRM: [docs/add-3d-model.md](docs/add-3d-model.md) |
| Panel font | system fonts | Customize → Look → Add font file |

Without a 3D model she stays in her chibi form: the task panel and confirm buttons show beside the chibi.

## Privacy
Everything runs locally. Nothing leaves the PC except the Google Calendar/Gmail reads you sign in to (read-only), web searches you ask for, and model downloads. Memory, chats and settings are in `%APPDATA%\ChibiAgent`; logs in `%LOCALAPPDATA%\ChibiAgent\logs`. Uninstalling keeps them.

## For developers
- Run from the repo: `uv sync` in `agent/`, `overlay/`, `voice/` (add `--extra f5` in `voice/` for F5), then `python chibi.py`.
- Tests: `uv run pytest` in each package.
- Build the installer: `powershell -ExecutionPolicy Bypass -File packaging\build.ps1` (needs Inno Setup 6, uv, the sprite pack and Godot 4.7.2; see the script's parameters).
- Design docs: `docs/scope.md`, `docs/architecture.md`, `docs/character.md`.

Licence: Apache 2.0 for the code ([LICENSE](LICENSE)).
