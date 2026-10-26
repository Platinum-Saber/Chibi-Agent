# Pose wheel and 3D body polish

**Goal:** let Kryo trigger her animations by hand (a right-click pose wheel) and polish the 3D body's look. Everything below is committed on `svg-rig` (5a4dc12, 8033f2c), not pushed.

## Decisions
- **Where the wheel lives:** in the Python overlay, not Godot. That way it works for both bodies, and the protocol is unchanged.
- **Wheel layout and look:** 8 poses, clockwise from the top: Wave, Cheer, Think, Look around, Stretch, Dance, Sit, Sleep. The style is a game emote wheel in frosted transparent glass, not black (Kryo's call).
- **Pose timing:**
  - Sit lasts 20 s.
  - Dance lasts 15 s and needs no music.
  - Sleep lasts until a poke, a drag or an agent mood.
  - The wheel refuses a pose while she's held, falling or dizzy.
- **`Brain.perform` sets `performing`:**
  - While it's set, the cursor-near rule and the "music stopped" rule don't cut her short.
  - Any `_set` clears it.
  - Sleep doesn't refresh `last_touch`.
- **Wheel placement:** `HUG = 0.68` of her measured half width plus `GAP_DIP`. Kryo confirmed this spacing; the measured half width is generous because of the scarf swing.
- **Dances:**
  - The wheel's Dance plays DanceExcited (Mixamo "Snake Hip Hop Dance").
  - Slow music still plays DanceVibe ("Listening To Music").
  - The overlay's dance sway (`ParamBodyAngleX`, `ParamAngleZ`) is skipped for Mixamo dance takes in `raphael.gd`.
- **"smile" expression:** built from Fcl_BRW_Joy and Fcl_MTH_Joy, so her eyes stay open; both dances use it. VRoid's `happy` (Fcl_ALL_Joy) shuts her eyes. Other moods still use `happy` (Cheer, Wave, soft landing, cursor near); Kryo hasn't asked to change those.
- **Beanbag colour:** it gets prop-only fill and bounce lights (render layer 2) and desaturated albedo to match Blender. She isn't lit by them.

## Files
- `overlay/chibi_overlay/wheel.py`: `PoseWheel` holds the state and geometry; `paint_wheel` draws it with Qt.
- `overlay/chibi_overlay/stage.py`: `PERFORM` maps poses to moods; also `open_wheel`, `close_wheel`, `toggle_wheel`, `perform`, the wheel hit in `press_at`, and outside-click and timeout closing in `tick`.
- `overlay/chibi_overlay/window.py`: right-click toggles the wheel; `paint_wheel` is called after `Painter`.
- `overlay/chibi_overlay/body/brain.py`: `perform()` and the `performing` flag.
- `overlay/icons/wheel/*.png`: white silhouettes, max 128 px, from `--offscreen --screenshot` renders.
- `overlay3d/raphael.gd`: `_add_smile`, and the sway skip for dances.
- `overlay3d/props.gd`: the prop studio lights and desaturation.
- `overlay/rigs/raphael_3d.toml`: mood → clip and expression.
- `overlay/tests/test_wheel.py`: the wheel tests.
- `overlay3d/README.md`: user docs for the wheel, dances and props.

## State
- **Verified by Kryo after restarts:** the wheel, the Snake Hip Hop dance and the spacing work live.
- **Tests:** 207 pass. `test_customize.py::test_font_picker...` fails because of Kryo's uncommitted `hud.py` font work, not ours.
- **Never commit:** `overlay/chibi_overlay/hud.py`, `overlay/tests/test_hud.py`, `electroharmonix.zip` (Kryo's).
- **Untested:**
  - the wheel on the 2D art (`HUG` was tuned on the 3D body);
  - the wheel on a second monitor or at mixed DPI.
- **Testing rule:** no live test overlays beside Kryo's Raphael (they knock it off the agent). Use `--offscreen` Godot previews and off-screen QImage renders instead.

## Next step
None pending. Wait for Kryo's next request. Possible follow-up: switch the eyes-shut `happy` to `smile` for Cheer and Wave, if Kryo wants.
