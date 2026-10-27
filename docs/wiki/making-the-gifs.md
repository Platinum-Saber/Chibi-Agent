# Making the GIFs

[Wiki home](README.md)

The GIFs in `media/` were rendered offscreen, not recorded from the screen. A second live overlay would knock Saber's running Raphael off the agent, so none was started. Instead:
- **2D:** `tools/render_gifs.py` drives the overlay's own classes in an offscreen Qt app: `SpriteModel` (the sprite pack), `Brain`, `Physics`, the rig maps, `PoseWheel` / `paint_wheel`, the HUD `Painter`, `CoreFX` and the transform `Particle`s. A fake clock replaces `time.monotonic`, so every frame is deterministic, and a scripted cursor stands in for Saber's mouse. Clicks, drags and throws go through the same brain and physics calls the stage makes, so the moods, landings and timings are the real ones.
- **3D:** `tools/record_3d.py` runs the Godot preview (`--clip`, `--expr`, `--turn`, `--listen`, `--offscreen`) with Godot's Movie Maker (`--write-movie`, `--fixed-fps 15`). It writes transparent PNG frames of each clip slot with the Raphael model. `render_gifs.py` then puts those frames on the desktop strip, moving them along the same physics as the 2D scenes for the 3D interaction GIFs.
- **Encoding:** Pillow, 15 fps (30 fps for the transform and the body switch), one palette per GIF, on a flat background to keep the files small.

The scenes are close to the live overlay but not identical:
- the wallpaper and taskbar are plain rectangles;
- the 3D body is a recording placed by its feet, not a live Godot window, so it doesn't turn toward where it walks;
- the 3D thinking/answer scene uses the AnswerPoint recording throughout.

## Making them again
Needs the overlay venv (`uv sync` in `overlay/`), the deployed app (for Godot and the sprite pack), the VRMs and the Mixamo takes. Give the scripts their own empty `APPDATA` and `LOCALAPPDATA` anyway, so nothing can touch Saber's settings.

1. Copy `overlay3d` to a work folder and import its models once (the copy keeps the repo's `.godot` cache untouched):

   ```powershell
   $work = "$env:TEMP\raphael-gifs"
   robocopy overlay3d "$work\o3d" /E /XD tools
   & "D:\Projects\Chibi-Agent-Project\Deployments\Raphael\godot\Godot_v4.7.2-stable_win64.exe" --headless --path "$work\o3d" --import
   ```

2. Record the 3D clips (about 6 minutes; frames go to `$work\g3d\<clip>\`):

   ```powershell
   overlay\.venv\Scripts\python.exe docs\wiki\tools\record_3d.py
   ```

3. Render the GIFs into `docs/wiki/media/`:

   ```powershell
   $env:APPDATA = "$env:TEMP\raphael-empty\Roaming"; $env:LOCALAPPDATA = "$env:TEMP\raphael-empty\Local"
   overlay\.venv\Scripts\python.exe docs\wiki\tools\render_gifs.py docs\wiki\media
   ```

   Pass scene names to render only some of them: `poses2d`, `poses3d`, `drag2d`, `drag3d`, `drop2d`, `drop3d`, `carried`, `pokes2d`, `pokes3d`, `longpress`, `wheel2d`, `wheel3d`, `talk2d`, `talk3d`, `confirm`, `gaze`, `walk2d`, `walk3d`, `transform`, `switch`, `turn`. Any other word limits `poses2d` / `poses3d` to those clips (for example `poses2d wave sit`).

`RAPHAEL_GIF_WORK` moves the work folder. The sprite pack and fonts are read from Saber's machine paths at the top of `render_gifs.py`.

## Rules for the media
- No VRM, Mixamo take, font or voice clip goes into git, only the rendered GIFs. Saber decided on 2026-10-27 that GIFs showing the 3D models may be in this repo.
- The GIFs are silent: her cloned voice is never published.
