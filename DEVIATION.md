# Deviation from Saber-Theme

Chibi-Agent is the desktop version of the chibi Saber mascot from the
Android launcher **Saber-Theme**. That project is the reference for how she looks, moves
and behaves. This file lists what carries over, what changes on the desktop
and where the original code lives. Read it before you design or port anything.

- Reference repo (local): `D:\Projects\Mobile Applications\Saber-Theme`
- Mascot source: `feature/mascot/src/main/java/com/sabertheme/feature/mascot/`
- Mascot docs: `docs/architecture.md` sections "Mascot" and "Briefing";
  plans `docs/plans/m4-mascot.md`, `docs/plans/m4-mascot-followups.md`;
  handoffs `handoffs/m4-mascot-and-polish.md`, `handoffs/mascot-followups.md`,
  `handoffs/glass-pill.md`, `handoffs/briefing-phase1.md`
- Treat Saber-Theme as **read-only** from this project. Copy code over; don't
  edit it in place. Never read its signing material (`*.jks`, `*.keystore`,
  `keystore.properties`) or `local.properties`.

## What Saber-Theme's mascot is
On Android she is an original vector drawing of chibi Saber (Fate). She stands on the Home
search bar and animates all the time.

| File | Lines | Role | Platform-bound? |
|---|---|---|---|
| `Pose.kt` | 133 | `Pose` data class (angles, squash, lift, eyes/brows/mouth/prop variants, effects), `lerp`/`approach`, 23 named gallery poses, `Outfit` (Armor/Winter/Casual) | Pure Kotlin |
| `SaberRig.kt` | 637 | `DrawScope.drawSaber(pose, time, outfit)`: the full rig in a 100 x 140 box (feet at 50,138), palette, sword glow, effects (tears, zzz, stars, notes, hearts, sparkles, sweat) | Compose `DrawScope` only, so it **runs unchanged on Compose Desktop (Skia)** |
| `MascotBrain.kt` | 265 | Mood state machine: Idle, Surprised, Pout, Crying, Happy, Held, Falling, SoftLanding, Dizzy, Walking, Moment, Wander, Sleeping, Dancing, Duel, Point, Chase, Leap, Talking. Poke counting, sleep timer, finger reactions | Pure Kotlin, tested |
| `MascotPhysics.kt` | 114 | Gravity 2600, max speed 4200, wall bounce 0.55, floor bounce 0.32, friction 0.6, settle 260 (dp/s units); landing impact classes; `leapTo` | Pure Kotlin, tested |
| `MascotLayer.kt` | 626 | Frame loop, `Motion.animate` (procedural breathing, blinks, ahoge sway, walk cycle, dangle, squash, dance bob ~110 bpm, tilt lean, gaze and arm aiming by `atan2`), touch boxes, mood → pose mapping | Android/Compose glue: rewrite |
| `MascotSurface.kt` | 89 | Full-window z-on-top `SurfaceView` so Home's glass never redraws | Android only: replace |
| `MessageCloud.kt` | 338 | WhatsApp thought cloud + preview, `StaticLayout` text | Android only: redesign |
| `GlassPill.kt` | 215 | Pill around the camera cutout that she chases and slashes | Phone only: drop or rethink |
| Tests | 358 | `MascotBrainTest`, `MascotPhysicsTest`, `PoseTest` | Port with the pure code |

Key look: big head, braided bun with blue ribbon, ahoge, green eyes (white
sclera, `IrisTop #13735A` → `IrisBottom #7FE0BC`), blue dress `#2F4FA8`,
silver armour `#D9DEE5`, gold trim `#E2B94B`, outline `#4A2A1C` at 1.3 units.
The full palette is at the top of `SaberRig.kt`.

The Briefing feature (`:core:briefing`) is the closest thing to an agent so far:
- Gemma 4 E2B through LiteRT-LM (GPU) labels mail, one mail per conversation.
  One big prompt failed in testing (memory `on-device-llm-benchmark`).
- A pure `BriefingComposer` writes terse sage lines ("Notice." … "End of report.").
- Kokoro TTS (`kokoro-int8-multi-lang-v1_0`, speaker **bf_emma**) speaks
  them. The audio drives her `Talking` mood and lip flap.
- `SpeakGuard` decides when she may speak aloud.

## Deviations on the desktop

### Carried over as is
- `Pose`, `SaberRig`, `MascotBrain`, `MascotPhysics` and their tests, copied
  into a Compose Multiplatform Desktop module. Only the package name changes.
  `SaberRig` needs nothing Android-specific; check its imports
  (`androidx.compose.ui.graphics.*`) still resolve under
  `org.jetbrains.compose`.
- Her personality: poke escalation (1 surprise, 3 pout, 5 cry), long-press
  happy, drag-and-throw with landing reactions, idle moments every 8–20 s,
  sleep after 60 s of quiet, and dancing while media plays.
- The voice: Kokoro bf_emma with a faint reverb, and the sage wording style.

### Changed
| Saber-Theme (phone) | Chibi-Agent (desktop) |
|---|---|
| Lives on the Home search bar; the bar is the floor | Lives on the desktop. The floor is the **taskbar top edge** or the top edge of the focused window's title bar. She can walk along windows and be thrown across monitors |
| `SurfaceView` over Home, ~30 fps cap | Transparent, undecorated, always-on-top window. Target is the monitor's refresh rate (60 Hz here, both screens) |
| Touch: tap, long-press, drag; finger near/far → Duel/Point | Mouse: click, long-press, drag. **Cursor proximity** replaces the finger, with no touch-down needed. Hover counts as "near". Right-click opens a menu |
| Click-through outside her bounds via Compose hit-testing | Win32 `WS_EX_TRANSPARENT \| WS_EX_LAYERED`, switched per frame from her hit box. Do this through JNA or a native sidecar |
| Phone tilt → lean | Window drag velocity and the cursor position drive lean and gaze |
| Music → `MediaState.playing` | Windows media sessions (`GlobalSystemMediaTransportControlsSessionManager`) |
| Charging → glowing Guard pose | Same idea, from the AC-power state (`GetSystemPowerStatus`) |
| WhatsApp message cloud | A thought cloud fed by the agent: tasks, reminders, Windows toast notifications if allowed |
| Gemma 4 E2B, one narrow prompt per item, no tools | A **real agent loop** on the RTX 4060: tool calls, memory, voice in and out (see below) |
| Kokoro on the S23 CPU, ~1.2x real time | Kokoro on GPU or CPU, far faster than real time, streamed sentence by sentence |
| No speech input | Push-to-talk / wake word → VAD → Whisper STT |
| `EffectsPolicy` power saving → ~8 fps | On battery: cap at 30 fps and unload or shrink the model; while a fullscreen app or game runs, hide her and free VRAM |

### Dropped
- `GlassPill` (no camera cutout). `GlassBlobPainter` and the AGSL glass, unless
  the thought cloud needs a glass look; Skia `RuntimeEffect` (SkSL) can host
  a port.
- One UI workarounds (top touch band, `transferTouchGesture`).

## Target machine
Lenovo 83EG, Windows 11 Home (26300).
- **CPU:** Ryzen 7 7840HS, 8 cores / 16 threads.
- **iGPU:** Radeon 780M. Use it for her window, so the dGPU stays free for the model.
- **dGPU:** RTX 4060 Laptop, 8 GB GDDR6, compute 8.9 (Ada), driver 610.62. About 1.7 GB of it is in use at the desktop.
- **RAM:** 16 GB DDR5-5600 in **one DIMM**, so it runs single-channel: CPU/RAM offload of a model is slow.
- **Storage:** three NVMe SSDs (D: 97 GB free, E: 420 GB, F: 610 GB). Put models on E: or F:.
- **Tooling:** Python 3.14, Node 24, git, gh. Many CUDA wheels lag behind 3.14, so use a **Python 3.12 venv (uv)** for the ML sidecar.

## Agent budget (8 GB VRAM)
| Piece | Choice | VRAM | Note |
|---|---|---|---|
| LLM | Qwen3-8B or Llama-3.1-8B, Q4_K_M, llama.cpp CUDA server (OpenAI-compatible, tool calls) | ~5 GB + ~1 GB KV at 8k ctx | ~40–55 tok/s generation |
| LLM (light) | Gemma-class 4B, Q4 | ~3 GB | ~70–90 tok/s; frees room for vision |
| STT | faster-whisper small / distil-large-v3, int8 | 0.5–1.5 GB (or CPU) | Silero VAD in front |
| TTS | Kokoro (ONNX) bf_emma | <0.5 GB (or CPU) | stream per sentence |
| Vision (optional) | small VLM for screen awareness, loaded on demand | 3–5 GB | can't stay resident next to the 8B model |

Don't use 14B+ models: they spill into single-channel RAM and drop to around
10 tok/s, which breaks the "live" feel. Expect about 0.6–1 s from the end
of speech to her first spoken word: VAD end → STT → first LLM tokens → first
TTS sentence. She shows Thinking/Curious poses while she waits, so the delay
reads as character, not lag.

## Suggested shape (to confirm in the new project's plan)
- `app/` (Kotlin, Compose Desktop): the window, rig, brain, physics and input,
  plus Win32 glue through JNA. It talks to the sidecar over a local WebSocket:
  JSON events in (`say`, `mood`, `cloud`, `viseme`), user events out.
- `agent/` (Python 3.12): llama.cpp server management, the agent loop with
  a tool registry (each side-effectful tool asks for confirmation), STT,
  TTS and memory (SQLite).
- The brain stays the authority on her body. The agent only *requests* moods
  (Talking, Thinking, Happy…), and the brain may refuse while she's Held or
  Falling, the same rule as `MascotBrain.busy`.

## First spikes before building
1. A transparent always-on-top Compose Desktop window on Windows. Confirm that per-pixel
   alpha, GPU rendering and click-through hold 60 fps. Fallback: Tauri/WebView2 with
   the rig ported to Canvas 2D.
2. Port `drawSaber` and run the pose gallery on the desktop.
3. llama.cpp + Qwen3-8B Q4_K_M: measure tok/s and VRAM with Whisper and
   Kokoro loaded too.
