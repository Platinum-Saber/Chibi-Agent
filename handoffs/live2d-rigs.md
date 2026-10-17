# Handoff: her own Live2D rigs (v1 item 3)

**Goal:** replace the Haru/Mao sample models with Raphael's own chibi and serious Live2D rigs, without changing overlay code.

## Decisions
- Live2D Cubism, 2D (VRoid 3D is after v1). The runtime is live2d-py 1.0.0, already working in the overlay.
- **Chibi** (~2.5 heads, full body, ~140 px): 40–60 layers, must fit Cubism FREE (1 texture ≤ 2048 px, ≤ 100 meshes, ≤ 30 deformers, ≤ 100 params). Do it first.
- **Serious** (~7 heads, bust/half-body, 360–420 px): 80–120 layers; may need PRO, so rig it in a trial or keep it lean.
- Use the standard Cubism parameter names so lip sync and the rest work as-is (`ParamMouthOpenY` from audio RMS, `ParamAngleX/Y/Z`, eyes, brows, `ParamBreath`), plus the custom `ParamRingGlow`, `ParamEyeGlow`, `ParamArmL/R` and `ParamLegSwing`.
- The overlay handles movement, throws, squash, facing and the 0.6 s transform particles; the rig doesn't.
- Final art is hand-split layers; AI is for concept exploration only. Rig art stays out of git; rigs live on `F:\ChibiAgent\rigs\{chibi,serious}\`.
- Kryo drives the art (draws it or commissions it); sessions do checklists, mapping files and testing.

## Files
- `docs/character.md`: the source of truth.
  - "Visual design": hair, gold eyes, coat-dress, glyph ring, palette.
  - "Art pipeline": steps 1–5.
  - "Required coverage": 9 expressions and the motion table for each form.
- `config.toml` `[overlay]`: `chibi_rig` / `serious_rig` (`.model3.json` paths) and `chibi_map` / `serious_map`.
- `overlay/rigs/haru.toml`, `mao.toml`: map each mood and moment to `{motion, index, expression}` plus `height_dip`. Copy one for each real rig.
- `overlay/chibi_overlay/body/motion.py`: the mood names the maps must cover; missing moods fall back to `idle`.
- `handoffs/v1-remaining.md`: the other v1 items (thought cloud; acceptance checks by hand).

## State
- **Works:** the whole pipeline runs on the samples (Haru = chibi, Mao = serious): moods, expressions, lip sync, form switch.
- **Not started:** concept sheets, PSDs, rigs, mapping files for her.
- **Committed on `v1`, not pushed yet:** `remember`, `set_reminder` and `cancel_reminder` now ask for confirmation. All tests pass (158 agent).

## Next step
1. Kryo picks the art source (self or commission) and makes the **chibi concept sheet**: front, ¾ view and the 9 expressions, in the character.md palette.
2. In parallel, a session writes:
   - `docs/rig-checklist.md`: PSD layer names, the parameter list and the exp3/motion3 files the chibi needs, taken from "Required coverage";
   - a stub `overlay/rigs/raphael_chibi.toml` using the motion group names that checklist sets.
