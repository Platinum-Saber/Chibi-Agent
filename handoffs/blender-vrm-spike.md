# Handoff: Blender → VRM spike (3D route for Raphael)

**Goal:** find out in about a day whether a 3D Raphael, built by scripting Blender from a
licensed base model, looks good enough to use. The output is a VRM that three-vrm renders.
This runs alongside the Live2D plan (`handoffs/live2d-rigs.md`: Kryo is learning to draw
the chibi). Kryo hasn't decided yet whether 3D replaces Live2D or only backs it up.

## Why Blender
Blender is fully scriptable with `bpy`, so a session can do the work headless and repeatably.
VRoid Studio only offers a GUI, and it isn't installed. Sessions can't model an attractive
anime face or paint good textures, so start from a base model and change it: proportions,
the chibi variant, added bones and meshes (hood, robe, halo, orb), and expressions.

## Ready (set up 2026-10-17)
- **Blender 5.2.2 LTS:** `X:\Blender\blender.exe`.
- **VRM add-on 4.10.2** (saturday06, MIT/GPL), from extensions.blender.org with the sha256
  checked. It's unpacked into the **System** extensions folder,
  `X:\Blender\5.2\extensions\system\vrm\`.
  - Why there: `%APPDATA%` writes from the Claude app are virtualized and would never
    reach Kryo's real Blender profile.
  - Headless scripts enable it themselves, *after* any `read_factory_settings` call:
    `addon_utils.enable("bl_ext.system.vrm", default_set=True)`.
  - In the Blender GUI, Kryo ticks **VRM format** once under Preferences → Add-ons (System).
- **Sample models** in `D:\Projects\Chibi-Agent-Project\ChibiAgent\3d\samples\`. Both are under the VRM Public License 1.0,
  and both have `modification: allowModificationRedistribution` in their meta:
  - `VRM1_Constraint_Twist_Sample.vrm`: pixiv Inc., a VRoid-made anime girl, credit not
    required. It has 167 bones (`J_Bip_*` VRoid skeleton), 3 meshes, 58 shape keys, and the
    standard expressions (`aa ih ou ee oh`, `happy angry sad relaxed surprised`, blink, lookAt).
    **Use this one as the base.**
  - `Seed-san.vrm`: VirtualCast, credit required.
- **Folders:**
  - `D:\Projects\Chibi-Agent-Project\ChibiAgent\3d\blend\`: `.blend` work files.
  - `D:\Projects\Chibi-Agent-Project\ChibiAgent\3d\export\`: exported `.vrm` files.
  - Model files are git-ignored (`*.vrm`, `*.blend`).
- **Round trip:** `spikes/vrm/blender/roundtrip.py` imports a VRM, prints its rig and
  exports it again. It's verified on the pixiv sample, and the re-export renders with
  working expressions:
  `X:\Blender\blender.exe -b --factory-startup --python spikes/vrm/blender/roundtrip.py -- IN.vrm OUT.vrm`
- **Viewer:** `spikes/vrm/`, with three 0.186.1 and @pixiv/three-vrm 3.5.5 (`npm install`
  is done; `node_modules` is git-ignored).
  - `node spikes/vrm/serve.mjs`, or the preview config `vrm-viewer` in the project root's
    `.claude/launch.json`. It serves on http://127.0.0.1:5179 and maps `/models/` to
    `D:\Projects\Chibi-Agent-Project\ChibiAgent\3d\`.
  - `?model=export/x.vrm` picks the model, and `&bg=transparent` matches the overlay.
  - Keys: 1–9 / 0 for expressions, `m` for a fake lip sync, `r` to reset the camera.
  - It also does blink, breath and gaze at the cursor.
- **Overlay:** its venv already has PySide6 6.12 with QtWebEngine. That's what an overlay
  version would use (a transparent `QWebEngineView`).

## Look to aim for
`docs/character.md` → "Visual design":
- light sky-blue hair, ruby-red eyes;
- the hooded white robe draped toga-style (default outfit) and the coat-dress;
- the golden sunburst halo and the cyan orb;
- the chibi at about 2.5 heads.

References are in `D:\Projects\Chibi-Agent-Project\ChibiAgent\references\{serious,chibi}\`. Use them as a guide; never trace them.

## Next steps (the spike)
1. Recolour the pixiv base: hair to the palette's blues, eyes to ruby, using the
   textures/materials (MToon). Check it in the viewer.
2. Build the halo (a gold ring with spikes) and the orb as meshes parented to new bones.
   Add a `ringGlow`-style custom expression if it's cheap.
3. Make a first robe with a hood, either from a cloth-simulated sheet or by reshaping the
   sample's clothes. Judge it honestly.
4. Make the **chibi variant**: scale the head up and shorten the limbs and torso, apply it
   to the mesh, fix the spring bones, and export it as a second VRM.
5. Map her 9 expressions (neutral, happy, surprised, pout, upset, sleepy, thinking,
   focused, warning) onto presets plus custom shape-key mixes.
6. Measure the frame rate: open the viewer in a transparent frameless `QWebEngineView`
   on the iGPU vs the dGPU. The overlay budget is in `docs/scope.md`, and the Live2D
   numbers are in `docs/spikes.md`.
7. Write the results in `docs/spikes.md`: screenshots, fps, what looked good and what
   didn't. Then Kryo decides: 3D, Live2D, or both.

Put every Blender step in a script under `spikes/vrm/blender/` so it can be re-run on a
new base model.

## Progress (2026-10-17, paused at Kryo's request)
Data moved: everything that was in `F:\ChibiAgent` now lives in `D:\Projects\Chibi-Agent-Project\ChibiAgent`
(paths in this file above still say F:). Build: `X:\Blender\blender.exe -b --factory-startup --python
spikes/vrm/blender/build.py -- NAME STEPS` (see the docstring), about 30–45 s per model.
- **Done:** steps 1–5 scripted (`s1_recolour` … `s5_expressions`, shared `rlib.py`).
  `export/raphael_serious.vrm` (recolour, halo, orb, robe + hood, expressions) and `export/raphael_chibi.vrm`
  (2.48 heads). Screenshots in `ChibiAgent\3d\shots\` (`contact.html?p=serious_expr_` shows the 9 faces).
- **Not rebuilt yet:** the stronger pout/thinking/focused mixes in `s5_expressions.py` (rebuild both models).
- **What looked good:** palette recolour (hair, ruby eyes), halo + `ringGlow`/`haloAmber`, orb, the chibi
  proportions, happy/surprised/upset/sleepy/warning. **Weak:** the robe is a plain column with a diagonal
  neckline (no real toga drape or sleeves); hood edges step and look lumpy; some hair clips the chest;
  the chibi hood is tall and pointed; pout/thinking/focused were too subtle; there's no tear mesh for "teary".
- **fps (step 6, `spikes/vrm/fps_qt.py`, run with `cd overlay; uv run --with psutil python ../spikes/vrm/fps_qt.py`):**
  transparent frameless `QWebEngineView`, ANGLE D3D11 on the RTX 4060 in every run, even with
  `--force_low_power_gpu`. Serious 420×600, chibi 300×400 and serious fullscreen all hold
  **59.9 fps p50, p95 17.7–19.0 ms**, but use **60–97 % of one core** (Live2D: ~20 %). Raw rows are in
  `spikes/vrm/out/fps.csv`. Still to run: the screen-1 (780M display) runs E/F, and a CPU check with the viewer's
  HUD/fps work stripped out.
- **Left:** step 7, the `docs/spikes.md` write-up (Spike 5), plus the items above.
