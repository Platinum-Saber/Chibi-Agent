# overlay3d: Raphael's full-size 3D body (Godot 4.7)

Her 3D body, one of her two bodies alongside the 2D art; she shows one at a time. To switch, use tray → **Switch to 3D model** / **Switch to 2D art**, or Customize → Look → Body. The choice is remembered.

The Python overlay (`overlay/`) stays her only connection to the agent, and it keeps everything that isn't drawing:
- brain and physics;
- input: poke, long press, drag and throw;
- her panels: speech, HUD and confirm buttons, and the thinking core;
- tray, fullscreen hiding, and the 30 fps cap on battery.

This Godot project only draws her. The agent and its protocol don't change.

## How it fits together
```
agent ──WS (unchanged)── overlay (Python, Qt)                     Godot overlay3d (renderer)
                          Stage.tick → GodotModel.Update  ──TCP──▶  clip, expression, params, gaze
                          hit test (point in her hull)    ◀──TCP──  hull of her bones, window handle
```
- **The 3D body is a body kind:** an outfit whose rig path is `godot:<this folder>` (`[overlay.outfits.teen_3d]` in `config.toml`; `[overlay] bodies` names the 2D and 3D outfits).
- **`overlay/chibi_overlay/godot3d.py`:**
  - **Starting the renderer:** it starts Godot (`[overlay] godot_exe`) with `--renderer=PORT --token=T`.
  - **Taking the calls:** `GodotModel` accepts the same calls `Puppet` makes on a Live2D model.
  - **Sending frames:** it sends one JSON line per tick: her feet and height in window px, the clip and expression names, the Live2D-style params (mouth, body and head angles, eyes) and the gaze point.
- **The renderer's window belongs to the overlay:**
  - **Placement:** it covers her monitor (1 px short at the bottom), directly under the overlay's window.
  - **Never in the way:** it is permanently click-through (`WS_EX_LAYERED | WS_EX_TRANSPARENT`), never takes focus and has no taskbar button.
  - **Why 1 px short:** a window that covers the whole monitor counts as a fullscreen app (a game) to any overlay's fullscreen watcher, and the agent would free its VRAM. It is also registered as the overlay's own window the moment it says hello.
  - **Clicks:** they keep landing on the overlay's window, which asks `GodotModel.hit()`, a point-in-hull test against the hull Godot sends each frame.
- **Lifetime:**
  - one renderer per overlay;
  - switching to 2D hides its window at once and ends it after 0.5 s (Godot is slow to quit by itself);
  - it sits in a kill-on-close job, so it never outlives the overlay, even after a crash;
  - it quits by itself if the link drops.
- **If it can't start:** if the renderer doesn't come up (missing exe, no hello within 30 s), the overlay goes back to the 2D body and tells the agent through `outfit_state`.
- **Renderer log:** `%LOCALAPPDATA%\ChibiAgent\logs\godot3d.log`.

## Licence: personal use only
The model is "Rimuru Tempest (fanmodel)" by rurune, with Kryo's edits. Its VRM metadata says **Redistribution_Prohibited** and **commercial use: Disallow**. Therefore:
- `models/` and every `*.vrm` stay out of git;
- no exported build of this project may include the model;
- unlike the 2D art, it can't go on the portfolio.

## Export the model
The master is Kryo's Blender file in `D:\Character Design\output\3d\teen\vrm-appearance\v01\source\Raphael_VRM_Appearance_v01.blend`. Check that project's handoff (`docs/handoff/CURRENT.md`) for the current version first.

```bash
X:/Blender/blender.exe -b "D:/Character Design/output/3d/teen/vrm-appearance/v01/source/Raphael_VRM_Appearance_v01.blend" --python overlay3d/tools/export_vrm.py -- D:/Projects/Chibi-Agent-Project/ChibiAgent/3d/export/raphael_teen_vNN.vrm
```

- **What the script does:** exports scene `01_VRM_Appearance` without the hidden swap-fit guide. It never saves the .blend. It then re-imports the VRM and prints its bones, meshes, expressions, spring groups and height.
- **Then:**
  - copy the export to `overlay3d/models/raphael_teen.vrm`;
  - use the next version number (currently v02, from checkpoint 68);
  - record the lineage in `D:\Character Design\history\`.

## Her clips and expressions
- **Clips:** `clips.gd` holds her body clips, keyed in code for now:
  - moods: Idle, Talk, Think, Analyse, Notice, Happy, Surprised, Pout, Upset, Held, Fall, Land, Dizzy, Walk, Sleep, Sit, DanceVibe, DanceExcited;
  - idle moments: LookAround, Stretch, Wave.
- **Pose format:** degrees about the model axes per bone, applied Z, then Y, then X. Right-side bones mirror the left ones. `_drop` lowers her hips.
- **Blending:** `raphael.gd` crossfades between clips over 0.25 s. On top it layers breath, blinks, gaze, the overlay's params, and an expression mixer that reads godot-vrm's per-expression blend-shape tracks, so a mood, a blink and a mouth shape can mix.
- **Mood map:** `overlay/rigs/raphael_3d.toml` maps every brain mood and idle moment to a clip and a VRM expression (neutral, happy, angry, sad, relaxed, surprised). `height_dip` sets her size, which Customize can override.
- **Better clips later:** a Mixamo or VRMA clip can replace a keyed one under the same name.
- **Facing:** she turns 70° toward where she walks, and faces front again at rest.

## Run it on its own (preview)
```bash
Godot_v4.7.2-stable_win64.exe --path overlay3d -- --clip=Wave --seconds=2 --screenshot=wave.png
```
- **Window:** a 520×1000 preview, bottom-right. It never takes focus, so it has no keys.
- **Arguments:**
  - `--model=res://models/x.vrm`
  - `--clip=NAME`
  - `--expr=happy`
  - `--gaze=X,Y`
  - `--turn=DEG`: 90 shows her side, 180 her back
  - `--seconds=S`: prints the average fps
  - `--screenshot=PATH`: saves a transparent PNG, and reports drawn pixels outside the hull
- **Overlay test flags:**
  - `python -m chibi_overlay --outfit teen_3d` starts the overlay straight in the 3D body;
  - `--debug-throw=VX,VY` throws her;
  - `--debug-switch=S` switches body after S s and again after 2S s.
  - To keep a test overlay away from a running agent, give it its own empty `APPDATA` and `LOCALAPPDATA`. The agent keeps one overlay, and two would knock each other off.

## Files
- **`main.gd`:** the renderer's link (frames in, hull out), placement, the orthographic camera, and preview mode.
- **`raphael.gd`:** her body:
  - clips with crossfades;
  - breath, blinks, gaze and params;
  - the expression mixer;
  - the scarf alpha fix.
- **`clips.gd`:** the keyed clips.
- **`addons/`:** godot-vrm and its MToon shader, vendored (`addons/VENDORED.md`).
- **`tools/export_vrm.py`:** the Blender → VRM export and its check.

## What doesn't carry over from Blender
The Blender ragdoll, the coat cloth simulation and the volume-preserving skinning are Blender-only. Here the coat follows the skeleton, and hair and scarf use the VRM's own spring bones.

The scarf's Blender shader is unlit emission, which exports with no alpha. `raphael.gd` (`_fix_alpha`) rebuilds such materials at load as an unlit, alpha-cut texture.

## Measured (RTX 4060 Laptop, Compatibility renderer, 2560×1440 at 100 %)
- **3D body in the overlay** (Raphael v02, 2026-10-25):
  - CPU, steady: overlay about 17% of one core, Godot 33–37%.
  - CPU during a throw and landing: overlay about 27%.
  - One earlier run read 100% for the overlay; it didn't recur in four later runs.
  - Memory: overlay about 207 MB, Godot about 204 MB.
  - GPU memory: overlay 126 MiB, Godot 267 MiB, so **393 MiB, over the ~300 MiB overlay budget**.
  - Renderer start: about 3 s.
- **2D body in the same isolated setup:** overlay about 22% of one core.
- **For comparison:** the three-vrm spike used 60–97% of a core.
