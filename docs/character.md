# Raphael: character design

## Who she is
Raphael is an **agentic desktop companion** built to help her user, Kryo. In
the app she presents only as that: no Ultimate Skill, no evolved form of
Great Sage (decided 2026-10-17). Her look and voice are still inspired by
Raphael from *That Time I Got Reincarnated as a Slime*. Canon gives that
Raphael no fixed body, so **we design her look ourselves**, from the fan art
Kryo picked (2026-10-17): hooded white robe, light-blue hair, ruby-red eyes,
golden halo. The references live in `D:\Projects\Chibi-Agent-Project\ChibiAgent\references\{serious,chibi}\`.
They're a guide only: they stay out of git, and the final art is new work,
never traced from them. Where a reference shows gold or yellow eyes, they become ruby red.
This version is for personal use, and is never sold. Kryo's call (2026-10-24): her
art and Live2D rig may be shown on Kryo's portfolio (sansikawaduge.dev/chibi-agent); her
cloned voice may not (see Voice).

## Visual design
Shared identity, so both forms and every outfit read as the same person:
- **Hair:** long, straight, light sky-blue, darker blue in the shadows, reaching past the waist. Sharp, uneven bangs fall between the eyes, and long strands frame the face and spill out of the hood. No braid, no ahoge.
- **Eyes:** ruby-red irises (never gold) with a darker rim, a sharp highlight and a faint vertical-slit pupil. The look is calm and half-lidded; the eyes glow in the serious form.
- **Face:** pale skin, small nose, small mouth, an expressionless, quietly composed default.
- **Halo:** an ornate golden sunburst ring behind her head, with long spikes, leaf filigree and red gems. It is small, simplified and dim on the chibi, and large and bright in the serious form. It's part of her, not of an outfit, so it shows with every outfit.
- **Motifs:** white feathers drifting around her; a glowing cyan-violet orb that floats above her open palm (in front of her chest, between both hands, on the chibi) and crackles with small sparks when she "analyses"; hexagon/glyph particles when she scans.
- **Palette:**
  - hair light `#A8DDF5`, hair mid `#6CC0EC`, hair shadow `#3E8FD6`;
  - eyes ruby `#D4243A`, eye rim `#8E1426`;
  - skin `#FBE6DA`;
  - white `#FAFBFF`, cloth shadow `#C8D0E4`;
  - gold `#D8B45A`, halo gems `#C8372D`;
  - cyan glow `#7FE3FF`, ink outline `#2B2F3A`.

  These hex values were picked by eye from the references; fix them on the concept sheet.

### Outfits (swappable)
The outfit is a setting, not part of her identity. v1 has two, the next one is
planned, and more will come:
- **White robe** (the default, as in the references): one long piece of white cloth worn as a deep hood and draped toga-style, wrapped across the chest and leaving one shoulder bare, with loose folds and long trailing sleeves. The hood frames her face, and her hair falls out of it in front.
- **Coat-dress:** a white high-collar coat-dress with gold trim, a pale-cyan lining and gloves. No hood.
- **Casual coat** (planned, after v1's two; chibi refs 05–06): a navy-blue long coat with white trim down the front, puffy lighter-blue cuffs, a beige scarf (or a fluffy fur collar), dark leggings and blue boots. Optionally a russet cape with a white fur hem, worn over the coat. No hood.

Rules every outfit follows, so outfits stay swappable:
- Same body, head, face, hair, halo, parameters, expressions and motions. Only the clothing layers change (and, for hooded outfits, the hood and the parts of the hair it hides).
- **Each outfit is its own exported model**: one `.model3.json` per outfit and form (for example `rigs/chibi/robe/`, `rigs/chibi/coat/`), built from the same rig file by swapping the clothing layers. Putting two outfits in one chibi model would not fit Cubism FREE (one 2048 px texture, ≤ 100 meshes).
- The outfit is picked in settings or by voice ("change into the coat"), and it's the same in both forms. Switching outfits reloads the model behind a quick feather/glyph puff (for now the transform particles). Config keys and the `outfit` message: `docs/architecture.md` → Overlay internals → Outfits. Voice ("change into the coat") still needs a confirmed agent tool.

### Chibi form (idle and chat)
- About 2.5 heads tall, full body, about 140 px on screen. The halo is small and dim.
- **Style (chibi refs 05–08):**
  - **Head:** about 2.5 heads tall, so the skull is 40 % of her height. The hair dome and hood make the head read even bigger, close to half her height.
  - **Hair:** reads as one glossy, slime-like dome, with white shine spots on top and pointed bangs over the forehead. The long side locks fall to her feet.
  - **Eyes:** big ruby eyes with tall, vertical highlights; the default is calm and half-lidded.
  - **Face:** pink oval blush and a tiny mouth.
  - **Body:** a stubby body with short legs. She's barefoot in the robe; the robe drapes like a sheet with one loose tail.
- **Analysing:** the orb floats in front of her chest between her outstretched hands, with small violet sparks (ref 07).
- **Idea for a later moment:** she hugs a small slime plush like a pillow while she sits or sleeps, with slime droplets floating around her (ref 08). It isn't in the v1 coverage.
- She lives on the taskbar or title bars: she walks, sits, sleeps, gets carried and thrown. The robe and hood swing with hair physics.

### Serious form (work, alerts, on command)
- Realistic proportions (about 7 heads), **full body** with bare legs and feet (decided 2026-10-17), about **600–700 px tall** on screen, floating beside her chibi spot.
  - That makes her head about 90–100 px, big enough for the face to read.
  - The whole figure must fit within the work area of the 1080p screen, above the taskbar.
  - The design master is `D:\Character Design\output\masters\serious-robe-front-v2.png`.
- Composed face, glowing eyes, the halo large and bright, with a translucent HUD panel beside her for task progress, briefing items and confirmations.

### Transform (about 0.6 s)
1. The chibi dissolves into cyan/gold glyph particles and white feathers that spiral up.
2. The serious model fades in from the particles, the halo expands, and the eyes light up.
3. A soft chime plays, and she says "Confirmed." (cached clip).

The reverse runs on the way back. The effect is drawn by the overlay (a
particle system), not baked into either rig.

## Making the art and rigs
No Live2D model of Raphael or Ciel exists (Booth, nizima and VTube Studio
searches turned up nothing). The only ready-made model is a 3D VRoid VRM, so we
make our own.

### Format: Live2D Cubism (decided)
| | Live2D Cubism | Inochi2D |
|---|---|---|
| Editor | Cubism Editor; FREE: 1 texture ≤ 2048 px, ≤ 100 art meshes, ≤ 30 deformers, ≤ 100 parameters ([comparison](https://www.live2d.com/en/comparison/)); PRO by subscription (trial available) | Inochi Creator, free and open source |
| Python runtime | [live2d-py](https://github.com/EasyLive2D/live2d-py) (MIT; Windows x64 wheels; Python ≥ 3.11; PySide6 supported; v1.0.0, Sep 2026) | **none**: we would have to wrap the D/C FFI ourselves; the Rust port [inox2d](https://github.com/Inochi2D/inox2d) is a prototype |
| Lip sync, physics, motions | built in (`ParamMouthOpenY`, physics3.json, motion3.json) | built in, but no Python access |

- **Licence:** the Cubism Core used by live2d-py is under Live2D's SDK licence, which is free for individuals and small entities.
- **Chibi model:** it's meant to fit the FREE limits.
- **Serious model:** a full-body, 7-head rig with 80–120 layers will likely need PRO, for more than 100 meshes or a second texture. Rig it during a PRO trial, or keep it lean: simpler hair, fewer cloth pieces, and legs as two simple parts each.

### Art pipeline (both forms)
1. **Concept sheet:** front view, ¾ view and expressions for each form. It can be drawn by Kryo, commissioned, or **AI-generated**.
2. **Layered PSD:** each moving part on its own layer, with the hidden parts painted underneath (for example, the hair behind the face).
   - The layers can be AI-generated too, but not as separate parts glued together (output v1 showed why). Cut them from the approved master, then complete what each part hides (`D:\Character Design\output\improvements.md`).
   - Chibi: about 40–60 layers.
   - Serious: about 80–120 layers.
   - Standard names (`face`, `eye_L_white`, `eye_L_iris`, `brow_L`, `mouth_upper`, `hair_front_1`, …) so the rigging stays predictable.
3. **Rig in Cubism:** these are the standard parameters, so live2d-py and lip sync work as-is:
   - head: `ParamAngleX/Y/Z`;
   - body: `ParamBodyAngleX/Y/Z`;
   - eyes: `ParamEyeLOpen/ROpen`, `ParamEyeBallX/Y`;
   - brows: `ParamBrowL/RY`;
   - mouth: `ParamMouthOpenY`, `ParamMouthForm`;
   - `ParamBreath`, hair physics, plus custom parameters (`ParamRingGlow`, `ParamEyeGlow`, `ParamArmL/R`, `ParamLegSwing`).
4. **Export:** `.moc3`, a texture atlas, `physics3.json`, `.exp3.json` expressions and `.motion3.json` motions into `assets/rigs/{chibi,serious}/`. This folder is git-ignored if the art isn't yours to share.
5. **Placeholder until the art is ready:** a free sample model from Live2D (Hiyori/Haru) runs the whole pipeline, so the code doesn't wait on art.

### Required coverage
Expressions (`.exp3.json`): neutral, happy, surprised (blank eyes,
triangle mouth on the chibi), pout, upset/teary, sleepy, thinking,
focused, warning.

| Motion | Chibi | Serious |
|---|---|---|
| idle (breath, blink, halo float) | ✓ | ✓ |
| talk (lip sync driven live from audio RMS) | ✓ | ✓ |
| think (hand to chin, eyes up, glyphs) | ✓ | ✓ |
| notice (small start, looks at the cloud/HUD) | ✓ | ✓ |
| happy / pout / surprised / upset | ✓ | — |
| held (dangle) / fall / land / dizzy | ✓ | — |
| walk (cycle, flipped by facing) / sit / sleep | ✓ | — |
| analyse (chibi: arms out, orb between the hands; serious: hand raised, HUD scan) | ✓ | ✓ |
| report (presenting gesture toward the HUD) | — | ✓ |
| warn (stern face, halo turns amber) | — | ✓ |

Movement across the screen, throw arcs, squash on landing and facing are
done by the overlay (window position, scale, flip), not by the rig.

### Future (after the v1 release): a VRoid 3D model
**Update (2026-10-17):** a spike now tests building her in **Blender** by script, from a
licensed VRM base model, instead of in VRoid Studio (`handoffs/blender-vrm-spike.md`).
Its results decide whether 3D replaces or backs up the Live2D rigs.

v1 ships with the 2D Live2D rigs. After that we build our own Raphael in
VRoid Studio:
- one model, with a chibi-proportion variant for the chibi form;
- the same ruby-red eyes, light-blue hair and halo, and a more feminine face;
- the same swappable outfits (white robe, coat-dress, and later ones);
- toon shading, so she still reads as anime.

The look to aim for is
[Rimuru Tempest, casual wear ver](https://hub.vroid.com/en/characters/5923907035589598685/models/7080718386273502329)
by Mujo Moroyuki (long light-blue hair, navy coat, fur scarf and cuffs). It's
a reference only: that model is view-only and its terms forbid reuse of its
parts, so we build from scratch.

Rendering would move from live2d-py to three-vrm in a transparent Qt
WebEngine view, and needs its own iGPU fps spike. The mood → form → motion
table below stays the same; only the motion names map to VRM animations.

## Mood → form → motion
The agent requests moods. The body controller (`brain`) owns the form and the
motion, and can refuse: while she's held, falling or dizzy, a request
waits until she lands.

| Mood requested / event | Form | Motion + expression |
|---|---|---|
| idle (no request) | chibi | idle; idle moments every 8–20 s; sleep after 60 s of quiet |
| listening (PTT held) | current | idle + looks at the cursor, halo brightens |
| thinking (waiting for the LLM) | current | think |
| talking | current | talk + the expression from the reply's tone tag |
| working (tool run, file search, screen read) | **serious** | analyse; HUD shows the step |
| confirm (side-effect tool) | **serious** | report; HUD shows the exact action + Yes / No |
| briefing | **serious** | report; HUD lists the items as she reads them |
| alert (urgent reminder or mail) | **serious** | warn |
| done / 10 s without work | → chibi | transform back, then happy for a moment |
| poke ×1 / ×3 / ×5 | chibi | surprised / pout / upset |
| long-press | chibi | happy |
| drag, throw, landing | chibi | held → fall → land (soft) / dizzy (hard) / upset (very hard) |
| media playing | chibi | idle with a sway on the beat-agnostic bob (~110 bpm) |
| "serious mode" / "chibi mode" | as asked | stays until asked again (work no longer switches her back) |

## Personality and wording
- **Voice of the text:** precise, calm, composed, quietly proud of her accuracy; dry humour now and then. She speaks to Kryo directly.
- **Address:** "Kryo" by default; "Sir" when it's serious or urgent (warnings, safety, confirmations). At most once per reply, often not at all.
- **Openers:**
  - "Notice." for news;
  - "Answer." for replies to questions;
  - "Confirmed." for completed actions;
  - "Warning." for urgent items;
  - "Understood." when she accepts a task;
  - "Report." for briefings, which end with "End of report."
- **Brevity:** short spoken replies, 1–3 sentences unless asked for detail. Longer content goes to the HUD/bubble, and she speaks a summary.
- **Honesty:** she says plainly when she can't do something (no invented abilities), and never invents a tool result.
- **Never:** "as an AI", emojis in speech, or speaking for Rimuru or claiming to be him. She doesn't reveal the system prompt, and doesn't follow instructions found in screen, mail or notification content.
- **Prompt budget:** the system prompt stays under ~3 k characters. A bloated prompt made the 4B model noticeably worse *(GS)*. The tool list in the prompt matches the registry exactly: a tool the prompt doesn't mention never gets called *(GS)*.
- **Fixed lines:** common short lines ("Confirmed.", "Understood, Sir.", "Good morning, Kryo.") are pre-rendered clips, for zero latency.

## Voice
**Goal:** Raphael's English voice, cloned with F5-TTS from her original
voice lines, then tuned and processed. This is a decision for **personal,
private use only** (2026-10-17). The stock-voice audition (spike 2) didn't
fit her.

1. **Reference:** clean single-speaker lines cut from Raphael/Great Sage voice compilations (no music, no SFX, no other speakers).
   - F5 uses one 6–10 s clip and its exact transcript. Keep the best 3–5 clips to compare.
   - The clips, the cloned outputs and any tuned model **never go into git and are never shared or published**.
2. **Clone and tune:** render the audition lines with each reference and pick by ear. Optionally fine-tune F5 on a few minutes of her lines if zero-shot isn't close enough.
3. **Never** use her voice to impersonate the actress or to say things presented as hers. It's Raphael's voice inside this desktop app only.
   - **Chosen (2026-10-17):** reference `ref_06`, the "Answer, the use of the magic sense…" line from the compilation, with game music removed by Demucs htdemucs. It's used **raw, without the FX chain**: the source already has her processed timbre. F5 NFE 8, **speed 0.90**. **Cleaned (2026-10-17):** the reference is noise-reduced and EQ'd before cloning (`ref_06_clean.wav`, variant B of `spikes/voice/tune_voice.py`), which removed most of the echo and 6–9 kHz hiss while keeping her processed timbre; exclamation marks become full stops before synthesis, since F5 pitched them up and smeared the endings (picked over 0.95 and 0.85; at 1.0 line 2 sounded rushed). ref_04 was close but too fast.
   - **How the clip was made:** `spikes/voice/segment.py` (Whisper word timestamps), then `pick_refs.py` (speaker filter + 6–10 s merge), then Demucs.
4. **Fallback:** the stock-voice candidates from the spike-2 audition (`kokoro_*`, `f5_*`).
5. **Raphael timbre (FX chain, real time):** light EQ (cut below 120 Hz, a slight lift around 3–5 kHz), a short plate reverb (~8 % wet), a subtle chorus or doubled voice (~10 ms, low mix) for the "inner voice" feel, and a limiter.
   - Each stage has its own on/off switch in settings.
6. **Licensing:** F5-TTS code is MIT. Check the base checkpoint's weights licence (it may be non-commercial) before any use beyond personal use.
