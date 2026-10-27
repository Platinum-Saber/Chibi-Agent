# Release 0.1.1: installer and launcher

**Goal:** the first installable Raphael. A per-user Inno Setup installer, a `Raphael.exe` launcher with her emblem icon, the 2D sprite chibi by default with the 3D body as her serious form, Kokoro as the shipped voice. Commit 89f0162 on `svg-rig`; tag `v0.1.1` once the scratch install passes. Saber pushes.

## Decisions (Saber, 2026-10-27)
- **Ships:** code, the casual-coat sprite pack, Kokoro (downloaded by setup), the UI sounds, the 3D props, the icon, Godot 4.7.2, uv.
- **Never ships:** the F5 clone and references; the two VRMs, because 27 of 28 textures and the face mesh are rurune's "Rimuru Tempest (fanmodel)" (`Redistribution_Prohibited`), so their metadata stays rurune's and is not rewritten; the Electroharmonix font; Mixamo takes; the robe, ANIYA and sample outfits. `build.ps1` refuses these.
- **Outfits:** `chibi` (sprites, serious = `raphael.vrm`), `rimuru` (was teen_3d), `raphael` (was teen_3d_ruby). Without a VRM she's chibi-only.
- **Release:** a local build plus a git tag; nothing is published.
- **No 2D serious rig:** the 3D body is her serious form.

## Saber's machine (to do by hand)
1. Copy his settings (writes from the Claude app to AppData are virtualized):
   ```
   copy D:\Projects\Chibi-Agent-Project\ChibiAgent\config-saber.toml %APPDATA%\ChibiAgent\config.toml
   ```
2. Rename the VRMs in `overlay3d\models\`: `raphael_teen.vrm` → `rimuru.vrm`, `raphael_teen_ruby.vrm` → `raphael.vrm` (along with their `.import` files, or just delete those and Godot re-imports).
3. Voice venv: `uv sync --extra f5` in `voice\` (plain `uv sync` now removes torch/F5). The venv still has torch; the new nvidia wheels come with that sync.
4. Restart Raphael.

## Files
- `launcher/raphael.py`: Raphael.exe.
- `packaging/setup.ps1`: first-run setup.
- `packaging/build.ps1`: the build.
- `packaging/raphael.iss`: the installer.
- `shared/chibi_shared/config.py`: path expansion.
- `overlay/chibi_overlay/outfits.py`: `usable`, `Outfit.chibi_only`.
- `stage.py`: `chibi_only` property.
- `window.py`: `_drawn_body_only`.
- `godot3d.py`: `needs_import`/`run_import`, `DEFAULT_EXE`.
- `character.py`: `RENAMED`.
- `voice/chibi_voice/env.py`: `cuda_dll_dirs`.
- `tts.py`: F5 fallback.
- Docs: `README.md`, `CHANGELOG.md`, `docs/custom-voice.md`, `docs/add-3d-model.md`, `docs/architecture.md` → Packaging.

## Untested
- The mixed outfit live: the transform from the sprite chibi to the 3D Raphael and back (unit tests only; no live overlay beside Saber's).
- Godot's `--import` on a fresh install with a dropped-in VRM.
- Raphael.exe starting the whole app on a clean PC (the agent mutex stops a second instance on this laptop).
