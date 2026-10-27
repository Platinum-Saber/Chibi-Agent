# Changelog

## 0.1.1 (2026-10-27)
The first installable release.

### Install
- `Raphael-0.1.1-setup.exe`: a per-user installer (no admin) with Start-menu and desktop shortcuts, her own icon, and an uninstaller that keeps your memory, settings and added 3D models.
- `Raphael.exe` launcher: runs first-run setup when needed, then starts her.
- First-run setup (`packaging/setup.ps1`): Python environments through uv, Ollama (winget) with `qwen3.5:4b` and `nomic-embed-text`, the Kokoro voice, Whisper `small.en`. Safe to re-run (Start → Raphael setup (repair)).

### Her bodies
- Default rigs: the 2D sprite chibi, with the 3D body as her serious form when a VRM is installed. Without one she stays chibi-only.
- Outfits are now **chibi**, **Rimuru** (was teen_3d) and **Raphael** (was teen_3d_ruby); saved Customize settings carry over. The robe, ANIYA and sample outfits are gone from the defaults.
- Outfits whose model files are missing are left out of the tray instead of failing.
- No 3D models ship ([docs/add-3d-model.md](docs/add-3d-model.md)).

### Voice
- Kokoro is the shipped voice. F5-TTS is an optional extra for a voice of your own ([docs/custom-voice.md](docs/custom-voice.md)); without it, or without a reference clip, she falls back to Kokoro.
- Whisper finds CUDA through NVIDIA's own wheels, so the voice no longer needs torch.

### Other
- The config's paths may use `%VARS%`, `~` and paths relative to the app folder.
- Quitting closes the 3D renderer cleanly (no more "renderer link closed" errors in the log).
- UI sounds ship; the panel font falls back to system fonts (add your own in Customize).

## 0.1.0
Development builds on the `v1` / `svg-rig` branches: the agent, voice, overlay, memory, tools, briefings, the 2D and 3D bodies (`docs/`).
