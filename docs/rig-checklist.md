# Rig checklist: chibi, white robe

What the chibi rig in her default outfit must contain so it drops into the
overlay with no code changes. It's built from `character.md` → "Visual design",
"Outfits" and "Required coverage". The mood map that uses these names is
`overlay/rigs/raphael_chibi.toml`. The serious rig and the coat-dress get their
own sections once this one works. Style references: `D:\Projects\Chibi-Agent-Project\ChibiAgent\references\chibi\` (07 and 08 are the robe).

## Budget (Cubism FREE)
| Limit | FREE | Target |
|---|---|---|
| Texture | 1 × 2048 px | 1 × 2048 px |
| Art meshes | ≤ 100 | ~69 (the layers below) |
| Deformers | ≤ 30 | ~24 (list below) |
| Parameters | ≤ 100 | ~33 (list below) |

On screen she's about 140 px tall, so the canvas can be small: about 1200 ×
1600 px for the full body is plenty, and that leaves room on the atlas.

## Starter files
Made by `uv run tools/make_rig_template.py` (they're art, so they go outside the repo):
- `D:\Projects\Chibi-Agent-Project\ChibiAgent\art\chibi\raphael_chibi_robe_template.psd`: 1200 × 1600, with every layer below already created, empty, named and grouped in draw order. Paint into them.
  - `_guide` (top) holds the front construction at 60 % opacity, and `_paper` (bottom) is a white background. **Delete both before importing into Cubism.**
  - Written by our own small writer and checked with psd-tools; open it in Clip Studio or Krita once to make sure it loads there too.
- `D:\Projects\Chibi-Agent-Project\ChibiAgent\art\chibi\proportion_guide.png`: the front and ¾ construction (2.5 heads, a 520 px head, eyes low), nine expression blanks and the palette.

## PSD layers
- Every moving part is on its own layer, with the hidden parts painted underneath.
- Names are lowercase, use `_`, and end in `_L` / `_R` for her left and right.
- Groups are listed in draw order, back to front.

**Halo** (behind everything):
- `halo_glow` (soft cyan-gold blur)
- `halo_ring` (gold, simplified filigree)
- `halo_spikes`
- `halo_gems` (red)

**Back:**
- `hood_back` (the inside of the hood, behind the head)
- `hair_back` (the long back hair, waist length)
- `sleeve_R_back` (the far trailing sleeve)

**Body:**
- `leg_L`, `leg_R`, `foot_L`, `foot_R` (bare legs and feet under the robe; they show when she stands, sits or dangles)
- `robe_skirt` (the lower drape, split at the hem so it can swing)
- `robe_tail` (the loose end of the sheet that trails at her side)
- `torso` (skin under the drape)
- `shoulder_bare` (the bare shoulder; which side is bare is fixed by the concept sheet)
- `robe_body` (the wrap across the chest)
- `robe_drape` (the loose fold over the shoulder)
- `neck`, `neck_shadow`

**Arms:**
- `arm_L`, `arm_R`
- `sleeve_L`, `sleeve_R` (long, trailing)
- `hand_L`, `hand_R`
- `hand_R_chin` (the hand-to-chin pose for think; switched by `ParamArmR`)
- `hand_L_analyse`, `hand_R_analyse` (open palms either side of the orb for analyse; hidden by default)

**Head:**
- `face`, `face_shadow` (the hood's shadow on the forehead)
- `ear_L`, `ear_R` (painted, even though the hood mostly hides them)
- `nose`, `blush`

**Eyes**, the same layers for `_L` and `_R`:
- `eye_L_white`
- `eye_L_iris` (ruby red, darker rim, faint slit pupil)
- `eye_L_highlight` (separate from the iris, so it doesn't slide when she looks around)
- `eye_L_lid` (skin-coloured upper lid that covers the eye white as `ParamEyeLOpen` goes to 0, with the closed-eye line)
- `eye_L_lash_upper`
- `eye_L_lash_lower`
- `eye_L_blank` (the white "blank eyes" for surprised)
- `tear_L`

**Brows:** `brow_L`, `brow_R`

**Mouth:**
- `mouth_inner` (also the triangle mouth for surprised, through `ParamMouthForm`)
- `mouth_upper`
- `mouth_lower`

**Hair front:**
- `hair_side_L`, `hair_side_R`
- `hair_strand_L`, `hair_strand_R` (the long strands that spill out of the hood in front)
- `hair_front_1` … `hair_front_4` (sharp, uneven bangs, one falling between the eyes)
- `hair_shine` (white shine spots on the hair, on top of it)

**Orb** (in front of her chest; hidden unless `ParamOrb` > 0):
- `orb_glow`
- `orb_core` (cyan-violet)
- `orb_sparks` (small violet lightning)

**Hood front:**
- `hood_rim` (the edge that frames the face)
- `hood_fold` (the cloth over the shoulders)

That's 69 layers.

**Outfit layers:** the hood, robe and sleeve layers are the outfit. Another
outfit replaces only those layers and keeps every other name, so the
parameters, expressions, motions and map all carry over.

## Parameters
Use these IDs exactly. The overlay and live2d-py drive some of them by name.

| ID | Range | Driven by |
|---|---|---|
| `ParamAngleX` / `Y` / `Z` | −30…30 | gaze at the cursor (live2d-py drag); the overlay sets Y for think and sleep, and Z for the dance bob |
| `ParamBodyAngleX` / `Y` / `Z` | −10…10 | the overlay sets X for the dance bob and the swing while held; motions |
| `ParamBreath` | 0…1 | idle breathing |
| `ParamEyeLOpen` / `ParamEyeROpen` | 0…1 | blink (`EyeBlink` group); the overlay closes them for sleep |
| `ParamEyeLSmile` / `ParamEyeRSmile` | 0…1 | expressions |
| `ParamEyeBallX` / `Y` | −1…1 | gaze |
| `ParamBrowLY` / `ParamBrowRY` | −1…1 | expressions |
| `ParamBrowLAngle` / `ParamBrowRAngle` | −1…1 | expressions (pout, warning) |
| `ParamMouthOpenY` | 0…1 | **lip sync from audio RMS** (`LipSync` group) |
| `ParamMouthForm` | −1…1 | expressions; −1 is the surprised triangle |
| `ParamCheek` | 0…1 | blush |
| `ParamHairFront` / `ParamHairSide` / `ParamHairBack` | −1…1 | physics outputs |
| `ParamHoodSway` / `ParamRobeSway` / `ParamSleeveSway` | −1…1 | physics outputs (custom) |
| `ParamRingGlow` | 0…1 | halo brightness; brighter while listening |
| `ParamRingFloat` | −1…1 | the halo bobs up and down in idle |
| `ParamEyeGlow` | 0…1 | the eye-light ring (0 on the chibi except while analysing) |
| `ParamArmL` / `ParamArmR` | −1…1 | arm poses; R = 1 is hand to chin |
| `ParamLegSwing` | −1…1 | walk cycle and dangling while held |
| `ParamEyeBlank` | 0…1 | blank eyes for surprised |
| `ParamTear` | 0…1 | tears for upset |
| `ParamOrb` | 0…1 | orb appears and grows, sparks flicker (analyse) |

That's 33 parameters.

**model3.json groups:**
- `EyeBlink` = `ParamEyeLOpen` and `ParamEyeROpen`
- `LipSync` = `ParamMouthOpenY`

## Deformers (~24)
- **Root:** body rotation and body warp (breath, lean).
- **Head:** head rotation, face warp (`ParamAngleX/Y`), eye L, eye R, brow L, brow R, mouth.
- **Hair:** front, side L, side R, back, strands.
- **Clothes:** hood, robe skirt, sleeve L, sleeve R.
- **Limbs:** arm L, arm R, hand R (chin pose), leg L, leg R.
- **Halo:** one rotation deformer (float plus a slow spin).
- **Orb:** one warp deformer (pulse).

## Physics (physics3.json)
- **Inputs:** `ParamAngleX`, `ParamAngleZ`, `ParamBodyAngleX`. The overlay drives `ParamBodyAngleX` from the drag speed while she's held, so the hair and robe swing when she's carried or thrown.
- **Outputs:**
  - hair front, side and back;
  - hood (heavy, slow);
  - robe skirt and sleeves (light, trailing).

## Expressions (`.exp3.json`)
Each expression's `Name` in model3.json must match these exactly. They're lowercase.

| Name | Look |
|---|---|
| `neutral` | calm, half-lidded, small closed mouth |
| `happy` | eye smile, soft open mouth, light blush |
| `surprised` | blank eyes (`ParamEyeBlank`), triangle mouth |
| `pout` | brows angled in, puffed cheek, small mouth |
| `upset` | teary (`ParamTear`), brows up, wobbly mouth |
| `sleepy` | eyes nearly shut, head tilted |
| `thinking` | eyes up and to the side, one brow raised |
| `focused` | narrowed eyes, `ParamEyeGlow` up, halo bright |
| `warning` | stern brows, flat mouth, eyes lit |

## Motions (`.motion3.json`)
- Each group holds a single motion at index 0, so it can be swapped without touching the map.
- Talk has no motion. Lip sync drives `ParamMouthOpenY` live over whatever motion is playing.

| Group | Loop | Length | Content |
|---|---|---|---|
| `Idle` | yes | 4–6 s | breath, a blink or two, a slow halo float |
| `Think` | yes | 3 s | hand to chin (`ParamArmR`), eyes up |
| `Analyse` | yes | 3 s | both arms out, palms up; the orb fades in between them and pulses (`ParamOrb`), eyes lit (ref 07) |
| `Notice` | no | 0.8 s | small start, then looks up and to the side (toward the thought cloud) |
| `Happy` | no | 1.5 s | bounce, eye smile |
| `Pout` | no | 1.5 s | turns away, cheek puff |
| `Surprised` | no | 1 s | jump, arms up |
| `Upset` | no | 2 s | shoulders drop, sniffle |
| `Held` | yes | 1 s | dangle: legs swing (`ParamLegSwing`), arms loose |
| `Fall` | yes | 0.5 s | arms and legs out, robe flutter |
| `Land` | no | 0.4 s | knees dip, recover (the overlay adds the squash) |
| `Dizzy` | yes | 2 s | head circles, wobble |
| `Walk` | yes | 0.8 s | one step cycle facing right (the overlay flips it) |
| `Sit` | yes | 4 s | seated on an edge, legs dangling gently |
| `Sleep` | yes | 5 s | slow breath, head nodding |
| `LookAround` | no | 2.5 s | looks left, then right |
| `Stretch` | no | 2 s | arms up, stretch |
| `Wave` | no | 1.5 s | waves at the cursor |

## Export
- **Files:** `.moc3`, `texture_00.png`, `physics3.json`, the `.model3.json`, `exp/*.exp3.json`, `motions/*.motion3.json`.
- **Location:** `D:\Projects\Chibi-Agent-Project\ChibiAgent\rigs\chibi\robe\`. It's outside the repo, and rig art never goes into git.
- **Model name:** `raphael_chibi_robe.model3.json`.

## Acceptance
1. Point the chibi rig at the export and the map at `rigs/raphael_chibi.toml`, then run `python -m chibi_overlay`.
2. Each mood and moment plays its clip. Pokes ×1 / ×3 / ×5, a drag and throw, and walking all look right.
3. Lip sync moves the mouth while she talks, she blinks on her own, and the hair, hood and robe swing when she's thrown.
4. Measure her real height on screen and set `height_dip` in the map to match.
