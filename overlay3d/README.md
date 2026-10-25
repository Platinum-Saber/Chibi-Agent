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
- **Variants:** `godot:<this folder>#<file>.vrm` picks another model in `models/`. `teen_3d_ruby` is her ruby-eyed variant (`raphael_teen_ruby.vrm`), worn from tray → Outfit. Switching between 3D variants restarts the renderer (about 3 s), and switching back from 2D returns to the 3D variant she last wore.
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
- **Mixamo motion first:** `clip_sources.cfg` names the Mixamo FBX takes for each slot. They live in `anims/mixamo/`, which is out of git: they're Adobe content, fine to use in this project but not to redistribute as raw files. Kryo's downloads are in `D:\Projects\Chibi-Agent-Project\ChibiAgent\3d\anims\mixamo\`.
  - **Baking:** `mixamo.gd` retargets each take onto her skeleton and bakes it at load, about 1 s for all of them. It applies each bone's world-space change from the T-pose to her rest, then converts that to her local rotations. Only the hips' height carries over.
  - **Variety:** a slot with several takes plays a random one each time it starts or loops, which keeps talking and idling varied.
  - **Fallback:** a slot without takes plays its keyed clip.
  - **Adding a take:** download it from Mixamo (FBX, Without Skin, 30 fps, In Place for walks), copy it to `anims/mixamo/`, and list it under a slot.
  - **Comparing:** `--source=keyed` turns Mixamo off.
- **Keyed clips:** `clips.gd` holds the fallback clips, keyed in code:
  - moods: Idle, Talk, Think, Analyse, Notice, Happy, Surprised, Pout, Upset, Held, Fall, Land, Dizzy, Walk, Sleep, Sit, DanceVibe, DanceExcited;
  - idle moments: LookAround, Stretch, Wave.
- **Pose format:** degrees about the model axes per bone, applied Z, then Y, then X. Right-side bones mirror the left ones. `_drop` lowers her hips.
- **Blending:** `raphael.gd` crossfades between clips over 0.25 s (quaternion slerp). It sets only the humanoid bones; the spring-bone hair and scarf stay free. On top it layers breath, blinks, gaze, the overlay's params, and an expression mixer that reads godot-vrm's per-expression blend-shape tracks, so a mood, a blink and a mouth shape can mix.
- **Mood map:** `overlay/rigs/raphael_3d.toml` maps every brain mood and idle moment to a clip and a VRM expression (neutral, happy, angry, sad, relaxed, surprised). `height_dip` sets her size, which Customize can override.
- **Facing:** she turns 70° toward where she walks, and at rest faces the way Kryo last turned her.
- **Turning her:** hold the middle mouse button on her and drag left or right: 0.5° per px (`stage.py` `ROTATE_DEG_PER_PX`), drag right to turn her toward the screen's right. The turn lasts until restart. The 2D art ignores it.
- **Pose wheel:** right-click her for a ring of 8 poses beside her (to her right, or her left at the monitor's edge): Wave, Cheer, Think, Look around, Stretch, Dance (DanceExcited, Mixamo "Snake Hip Hop Dance", 15 s, no music needed), Sit (on the beanbag, 20 s) and Sleep (until you poke or drag her, or the agent needs her). Click one to play it; right-click her again, click its centre or anywhere else to close it, and it closes 8 s after the cursor leaves it. The icons in `overlay/icons/wheel/` are her silhouettes rendered with `--offscreen --screenshot`; the poses are mapped in `stage.py` `PERFORM`. It works for the 2D art too.
- **Walking pace:** `walk_speed` in `raphael_3d.toml` is in her heights per second, so it scales with her size. It's 0.5, 260 px/s at 520 px, which Kryo picked; the Mixamo walk's own stride would be 0.54.
  - **In the UI:** Customize → Look → Walking speed sets px/s per outfit (`walk_px_s` in `character.toml`).
  - **2D rigs:** they keep the stage's 90 px/s walk and 60 px/s wander unless set there.
- **Smooth movement:** each frame carries her velocity. Godot draws on its own vsync, out of step with the overlay's frames, so it carries her on at that velocity (up to 50 ms) instead of stepping unevenly.
- **Being held:** picked up at the waist or above, she hangs (`Held`, Mixamo "Hanging Idle"). Picked up below the waist, she's carried flat (`Carried`, "Being Carried"). The overlay decides this when the drag starts (`stage.py` `GRAB_LOW`, half her height) through the rig map's `held_low` entry; rigs without one, like the 2D art, always use `held`.
  - **Dropped while carried:** she falls face down (`falling_flat` → `FallFlat`, Mixamo "Falling-facedown"), hits the floor flat (`hard_landing` → `FlatImpact`, "Falling Flat Impact" from touchdown) and after `stage.py` `FLAT_IMPACT_S` (1.6 s) gets up (`hard_landing_up` → `GetUp`, the end of "Hard Landing", from all fours). The brain's `HARD_LANDING` lasts 2.7 s whatever the speed: no dizziness or tears. `stage.py` `fall_flat` remembers the carried drop until she lands.

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
- **`clips.gd`:** the keyed clips, used where a slot has no Mixamo take.
- **`mixamo.gd`:** the Mixamo retarget and bake.
- **`clip_sources.cfg`:** which Mixamo takes play each slot.
- **`addons/`:** godot-vrm and its MToon shader, vendored (`addons/VENDORED.md`).
- **`tools/export_vrm.py`:** the Blender → VRM export and its check.

## What doesn't carry over from Blender
The Blender ragdoll, the coat cloth simulation and the volume-preserving skinning are Blender-only. Here the coat follows the skeleton, and hair and scarf use the VRM's own spring bones.

The scarf's Blender shader is unlit emission, which exports with no alpha. `raphael.gd` (`_fix_alpha`) rebuilds such materials at load as an unlit, alpha-cut texture.

## Measured (RTX 4060 Laptop, Compatibility renderer, 2560×1440 at 100 %)
- **3D body in the overlay** (Raphael v02, 2026-10-25):
  - CPU, steady: overlay about 17% of one core, Godot 33–37%.
  - CPU during a throw and landing: overlay about 27%.
  - Readings near 100% for the overlay come from running a second (test) overlay beside Kryo's: the 2D body shows the same there. That overlay holds 60 fps, but its main thread busy-waits about 15 ms per frame in the GL swap, a graphics-driver vsync wait. Measure the cost with only one overlay running.
  - Mixamo takes bake in about 1 s at renderer start; at runtime they're interpolated, with no extra cost seen.
  - Memory: overlay about 207 MB, Godot about 204 MB.
  - GPU memory: overlay 126 MiB, Godot 267 MiB, so **393 MiB, over the ~300 MiB overlay budget**.
  - Renderer start: about 3 s.
- **2D body in the same isolated setup:** overlay about 22% of one core.
- **For comparison:** the three-vrm spike used 60–97% of a core.


## Coat/hand clearance (25 October 2026)

`coat_clearance.gd` fits three hidden convex coat volumes to the loaded torso/hem mesh (sleeves/cuffs excluded), following Hips, Spine and UpperChest. Forty-eight spherical forearm, palm, finger-joint and fingertip probes feed a skeleton-local analytic collision/IK solve. It is called at the end of `raphael.gd` `_pose`, after Mixamo/keyed playback, crossfades and body layers, before spring hair/scarf. It changes upper/lower-arm and compensating wrist rotations only; hand orientation, finger articulation and limb lengths are preserved. It does not deform or simulate the coat.

Smooth release preserves small corrections across frames. The blended arm pose is projected back outside the fitted volumes to prevent smoothing from carrying hands through the coat. Corrections are bounded (`max_offset`, default 0.16 m at this model's scale); unsuitable/missing coat or bone mappings fail closed by leaving original animation alone, and active Godot physical-bone simulation bypasses this animation correction. `--coat-clearance=off` provides baseline comparison. The model, Mixamo files, Blender masters, app protocol and configuration are unchanged.

Verification evidence/backup is in `D:/Character Design/output/godot/coat-clearance-v01/`. Tests enumerate actual configured Mixamo takes sampled at 30 fps, plus 60 fps transitions, missing-bone/disable/T-pose/root-transform checks. Penetration numbers describe the fitted probe boundaries, not a universal triangle-level cloth guarantee. Very different outfits/animations may need refitting/tuning, and this module requires the loaded coat material name `Tops_01_CLOTH_01` and Godot humanoid bone names.

## Props (25 October 2026)
`props/` holds Character Design's `Raphael_Props_v01`: three GLBs, their scene wrappers and helper scripts, unchanged. `props.gd` shows each prop only while it's used, popping it in and out over 0.2 s:
- **Headset:** follows her Head bone.
  - **On with the mic** during a conversation: the agent's listening mood (the frame's `listening`), the Think and Talk clips, or her mouth moving.
  - **On without the mic** for slow music (DanceVibe, Mixamo "Listening To Music"). Not for DanceExcited.
  - DanceVibe is listening, not dancing: the overlay's dance sway (`ParamBodyAngleX`, `ParamAngleZ`) isn't layered over a Mixamo dance take (`raphael.gd`), only over the keyed fallback dances.
  - Both dances wear `smile` (`raphael.gd` `_add_smile`): the Joy brows and mouth with her eyes open. VRoid's `happy` (Fcl_ALL_Joy) shuts her eyes.
  - **Off** 5 s after either ends.
- **Slime beanbag:** under her while she sits (Sit). It squashes over 0.4 s as she settles. Sit plays the chair take "Sitting Idle", with her hips held at the squashed seat (`keep_height`, `lift=-0.415`).
- **Futon: switched off for now** (`SHOW_FUTON` in `props.gd`); she sleeps on the floor. When on, it lies under her while she sleeps (Sleep), laid feet-to-head along her body, with the pillow under her head.
  - **One take per sleep** (`vary=false`): Female Laying Pose (on her front), Female Laying Pose - 2 (propped up) or Sleeping Idle (on her side).
  - **Per-take fit:** each has its own lift (`per_file` in `clip_sources.cfg`), now fitted to the floor; the comment there keeps the mattress values for when the futon returns.
  - **Futon v02:** what a better-fitting futon needs (blanket shapes per pose, a longer head end) is in `D:\Character Design\output\3d\props\requests\futon-v02-requirements.md`.
- **Clicks:** they pass through the props; the click hull is her bones only.
- **Prop colours:** the props were made under Blender's soft multi-light studio and its AgX view, which lifts and greys colours. Under her single key light the same PBR colours came out vivid cyan with near-black undersides. So `props.gd` gives the beanbag (and the futon) a front fill and a low bounce light on render layer 2, which only props are on, and desaturates and softens their materials (`DESATURATE`, `VALUE`, `SPECULAR`, `FILL_ENERGY`, `BOUNCE_ENERGY`).
  - **Match:** measured against the delivery's preview: mid tone #A8CBDA against Blender's #AFCDDD, shade #86A2AE against #95BAD0.
  - **Her look is untouched:** a test with both lights at strength 10 blew the beanbag to white and left her unchanged. The headset keeps its original look.

Preview checks: `--take=<file>` plays one take of the slot, `--listen=S` pretends she's listening for S seconds, and `--pose-report` prints her extent in the futon's own space.

## Render quality
`[overlay] render_scale` (supersampling, 1.0–2.0) and `msaa` (0/2/4/8) in `config.toml` go to the renderer (`--render-scale`, `--msaa`).
- **Default: 2.0 and 2.** Her eyes, lashes and mouth read cleanly at her normal 520 px. At 1.0 her hair breaks into jagged noise and her mouth is a single harsh line.
- **Budget:** Kryo's limit for her render is 800 MB of GPU memory.
- **Measured** (Godot alone, 2560×1439 window, RTX 4060 Laptop, 25 October 2026):

| Supersampling | MSAA | GPU memory |
|---|---|---|
| 1.0 | off | 234 MiB |
| 1.0 | 2× | 295 MiB |
| 1.0 | 4× | 350 MiB |
| 1.5 | off | 298 MiB |
| 1.5 | 2× | 426 MiB |
| 1.5 | 4× | 554 MiB |
| 2.0 | off | 350 MiB |
| **2.0** | **2×** | **580 MiB** |
| 2.0 | 4× | 800 MiB |

- **CPU:** stays at about 45–50% of one core whatever the setting.
- **GPU used:** the renderer draws on whichever GPU drives the screen she's on; here that's the 4060.
