# Spikes

Throwaway experiments that measure the risky assumptions before building.
Each spike has its own section; raw CSVs and logs live in `spikes/<name>/out/` (git-ignored).

## Spike 1: overlay

**Setup:** `spikes/overlay/overlay_spike.py` (adapted from live2d-py `examples/main_pyside6.py`), live2d-py 1.0.0, Haru sample model (local only, git-ignored), 2026-10-17.
- Window: frameless `QOpenGLWidget`, `WA_TranslucentBackground`, `WindowStaysOnTopHint | Tool | WindowDoesNotAcceptFocus`, `WS_EX_NOACTIVATE`, covering the whole monitor.
- Frame loop: `frameSwapped → update()` with swap interval 1. Haru is placed by measuring her alpha bounding box in the first 4 frames: 360 px tall, feet exactly on the taskbar top (y=1392).
- Click-through: every frame reads the 1-px alpha under the cursor; a 16 ms timer toggles `WS_EX_TRANSPARENT` only when that flips. Each toggle is checked with `WindowFromPoint`.
- Run: `cd spikes/overlay && uv sync && uv run overlay_spike.py [--screen N] [--duration S] [--busy] [--tag NAME]`. For 6.4.3: `uv venv -p 3.11 .venv311`, then `uv pip install --python .venv311 PySide6-Essentials==6.4.3 "numpy<2" live2d-py==1.0.0 PyOpenGL pywin32 psutil`.

### Hardware finding (changes the plan)
- **DISPLAY6 (2560×1440, primary) is wired to the RTX 4060; DISPLAY1 (1920×1080) to the Radeon 780M** (`EnumDisplayDevices`). The dGPU is always awake while the primary monitor is on.
- `GL_RENDERER` was **NVIDIA GeForce RTX 4060 Laptop GPU** in every run: both monitors, both Qt versions, with `SHIM_MCCOMPAT=0x800000000`, and after the "Power saving" Graphics setting was attempted. Windows never saved that setting: `HKCU\Software\Microsoft\DirectX\UserGpuPreferences` has no python.exe entry. So "Power saving" applied properly is still untested.
- The 3.12 venv runs as the base interpreter `C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe`. That is the exe the Graphics setting has to name.

### Results (steady state, 10 s windows, after the first warm-up window)
| Run | GPU | fps p50 | frame p50 / p95 / max ms | CPU (1 core / whole machine) | Notes |
|---|---|---|---|---|---|
| PySide6 6.12.0, Py 3.12, primary, idle (`f_idle612`) | 4060 | 59.95 | 16.7 / 17.6–17.7 / 18.7–19.4 | 20–22 % / 1.2–1.4 % | |
| PySide6 6.12.0, busy motions (`e_busy_qt612`) | 4060 | 58.95 | 16.7 / 17.5–17.6 / — ¹ | 21–22 % / 1.3–1.4 % | |
| PySide6 6.4.3, Py 3.11, busy motions (`e_busy_qt643`) | 4060 | 59.05 | 16.7 / 17.2–17.3 / — ¹ | 15–19 % / 0.9–1.2 % | |
| DISPLAY1 1080p (`a4_pref_s1`, `a5_shim_s1`) | 4060 (cross-adapter to the 780M display) | 58.7–59.3 | 16.7 / 17.8 / — ¹ | 27–28 % / 1.7 % | |
| Primary, interactive: clicks, drags, window dragged under her, video behind (`g2_interactive`) | 4060 | 59.8–60.0 | 16.6–16.7 / 17.3–20.3 / 20–54 (one 327 at startup) | 17–29 % / 1.1–1.8 % | 18 hits, 66 toggles |

¹ The max column in those runs is inflated (140–190 ms) by a blocking `nvidia-smi` call in my logger. That was fixed before `f_idle612` and `g2_interactive`.

- **First 10 s window:** 45–48 fps and 40–110 % of a core while the context, model and calibration warm up. First paint comes about 1 s after launch (8 s once, on a cold first run).
- **dGPU cost** (with no capture running): before the overlay, P5–P8 at 1.5–3.8 W and 1512 MiB. With the overlay, **P0/P5 at 6–31 W and about +270 MiB VRAM**. The other session's voice spike may add some noise.
- **Flicker:** no flicker in either Qt version. `flicker_check.py` found 0 single-frame spikes in 600 frames per 10 s, 60 fps `ddagrab` capture (`out/capture_qt612.mp4`, `out/capture_qt643.mp4`). The ANGLE/translucency flicker Great Sage saw did not show up here, but these runs used NVIDIA WGL, so the AMD GL path is still unchecked.
- **Click-through:** Qt already made the window `WS_EX_LAYERED` (ex-style `0x08080088`), so toggling `WS_EX_TRANSPARENT` alone works. The `WindowFromPoint` check passed 66 times with 0 failures: the cursor hits her when over her pixels and reaches the desktop or window below otherwise. You confirmed it by hand.
- **Focus:** 18 clicks on her played TapBody. `GetForegroundWindow` never became the overlay, so no focus was stolen.
- **Drag:** she moves inside the window and falls back with a small bounce, landing in 0.1–1.4 s.
- **Video playback** behind her and **windows dragged under her:** no stutter in the CSV, and she stayed on top. You confirmed it.
- **Fullscreen games:** a fullscreen game (VALORANT) covered her completely, which is fine because v1 hides her for fullscreen apps anyway.
- **Capture tool:** gdigrab only managed about 18 fps on a layered window, so all captures use ffmpeg `ddagrab` (Desktop Duplication).

### Verdict against the go criteria
| Criterion | Result |
|---|---|
| ≥ 58 fps p50 | ✅ 59.9 (steady state) |
| ≤ 20 ms p95 | ✅ 17.2–18.2 idle or busy; ⚠️ 20.3 in one interactive window |
| < 5 % CPU idle | ✅ 1.2–1.4 % of the machine (about 20 % of one core) |
| No dGPU use | ❌ GL always lands on the RTX 4060 (P0/P5, up to 31 W, +270 MiB) |
| Click-through both ways | ✅ |
| No flicker, no focus stealing | ✅ (on NVIDIA GL) |

**Verdict: GO for the overlay design (PySide6 current + live2d-py on Python 3.12; 6.4.3 isn't needed). NO-GO on "renders on the iGPU" as tested, so the user accepted the dGPU (see Decision).**
- The plan's fallbacks (QQuickWindow + D3D11 RHI, pygame + `UpdateLayeredWindow`) target flicker or perf, which both passed. They don't solve the adapter problem, because live2d-py's renderer is OpenGL either way.

### Decision (2026-10-17)
**The overlay runs on the RTX 4060. Reserve ~300 MiB of VRAM for it** (measured +270 MiB, rounded up) in the dGPU budget, alongside Ollama, F5-TTS and Whisper. Expect a few to about 30 W of extra dGPU power while she is shown.

Consequences for other docs, not yet edited because they're outside spike 1's files:
- `scope.md`: subtract ~300 MiB from the VRAM budget. Spike 3's peak VRAM go criterion (≤ 7.6 GB) should count the overlay as running.
- `architecture.md` (Rendering): replace the "Power saving / Radeon 780M" note. The overlay renders on whichever GPU drives the primary monitor, which is the 4060 on this laptop.
- `CLAUDE.md` house rule: change "The overlay renders on the iGPU" to "The overlay renders on the dGPU (~300 MiB reserved); the rest of the dGPU is for Ollama, F5-TTS and Whisper."

Left open (only if the budget gets tight): the Graphics "Power saving" setting (never actually saved), or making the 1080p the main display. Either could move GL to the 780M. If one ever does, recheck flicker on the AMD GL path, since that's where Great Sage saw it.

## Spike 2: voice

**Setup:** `spikes/voice/` (uv, Python 3.12): torch 2.11.0+cu128, f5-tts 1.1.22 (F5TTS_v1_Base), faster-whisper 1.2.1, kokoro-onnx 0.6.1 (CPU), pedalboard. Models are in `F:\ChibiAgent\hf` and `F:\ChibiAgent\models\kokoro`. Date: 2026-10-17. The clean runs had the GPU idle; an earlier run with VALORANT open gave about the same F5 numbers.
- **Run:**
  - `.venv\Scripts\python tts_bench.py`
  - `.venv\Scripts\python stt_bench.py`
  - `.venv\Scripts\python audition.py`
- **Gotchas:**
  - torchaudio ≥ 2.9 loads audio through torchcodec, which needs FFmpeg *shared* DLLs (the same trap Great Sage hit). `common.py` swaps `torchaudio.load` for soundfile.
  - faster-whisper's PyAV decode breaks on the installed `av`, so we pass 16 kHz numpy buffers instead, which is what the mic path does anyway.
  - The Great Sage `voice_a…f` candidates were **deleted unused**: their transcripts are Great Sage lines from the anime, i.e. clips of the dub actress (the CLAUDE.md rule).

### F5-TTS (median of 5, warm, example reference 5.3 s)
| NFE | Line | First sentence | Whole line | × real time |
|---|---|---|---|---|
| 8 | short (2 sentences) | 1.09 s | 2.24 s | 2.5× |
| 8 | medium | 1.07 s | 2.49 s | 4.9× |
| 8 | long (4 sentences) | 1.05 s | 4.66 s | 4.3× |
| 16 | medium | 1.82 s | 4.07 s | 3.0× |

- **Fixed cost per call:** about 0.8–1.05 s per `infer()` call, even for a one-word sentence ("Notice."). F5 always generates the reference frames plus the new ones.
- **Per sentence:** "The capital of Japan is Tokyo, Master." took 0.84 s at NFE 8, 0.76 s at NFE 6 and 0.61 s at NFE 4. A 6.3 s reference was no slower than the 5.3 s one.
- **Model:** load 12 s, VRAM +0.64 GB loaded, **+0.95 GB peak** while generating.

### faster-whisper (10 clips of 3.7 s average, median of 5)
| Model | Device | Latency (median / max) | WER | VRAM |
|---|---|---|---|---|
| **small.en** int8_float16 | CUDA | **0.19 / 0.27 s** | 6.6 % | 370 MB |
| distil-large-v3 int8_float16 | CUDA | 0.28 / 0.32 s | 8.1 % | 920 MB |
| small.en int8 | CPU (8 threads) | 1.83 s | 6.6 % | 0 |
| distil-large-v3 int8 | CPU | 7.3 s | 8.1 % | 0 |

- The WER comes from synthetic speech (F5/Kokoro voices). Real mic recordings (`recordings/*.wav` + `.txt`) are still to do.

### Audition
- **Output:** `spikes/voice/out/audition/<candidate>/<n>_{raw,fx}.wav`, 5 lines each.
- **Candidates:**
  - Kokoro stock voices `af_heart`, `af_nicole`, `bf_emma`, `bf_isabella`, `af_sky`;
  - `f5_example`;
  - F5 cloning each Kokoro voice (`f5_<voice>`).
- **Kokoro on the CPU:** 1.3–2.4 s per line.
- **Pick:** waiting on you.

### Verdict
| Criterion | Result |
|---|---|
| F5 NFE 8 first chunk ≤ 0.6 s | ❌ ~1.05 s per call (0.61 s only at NFE 4, quality not yet heard) |
| Voice VRAM ≤ 1.5 GB | ✅ F5 0.95 GB peak + small.en 0.37 GB ≈ 1.3 GB |
| STT ≤ 0.35 s | ✅ small.en 0.19 s (CPU isn't usable for gaming mode: 1.8 s) |
| A voice approved | ⏳ waiting on you |

**Decision:** keep F5 at NFE 8. Hide its ~1 s per-sentence floor behind **pre-rendered opener clips**: "Answer.", "Notice.", "Understood." and the like play the moment the LLM emits them (see the e2e results below). Use `small.en` on CUDA.

## Spike 3: brain

**Setup:** Ollama 0.40.5 (`winget`). Its tray app was stopped, and `ollama serve` runs with `OLLAMA_MODELS=F:\ChibiAgent\ollama` and `OLLAMA_FLASH_ATTENTION=1` set for that process only.
- **Models:** `qwen3.5:4b` (4.2 B, Q4_K_M, vision + tools + thinking; thinking is **on by default**, so we send `think: false`) and `nomic-embed-text`.
- **Run (in `spikes/brain/`):**
  - `.venv\Scripts\python tool_bench.py tools|vision|embed`
  - `..\voice\.venv\Scripts\python e2e.py`
- **Persona:** 1503 characters, generated from the 12-tool stub registry (`tools.py`).

### Tool choice (22 cases × 3 runs, `num_ctx` 8192, thinking off)
- **Accuracy:** **66/66 runs correct** (22/22 cases in every run), with the right tool and arguments.
- **No-tool cases:** answered directly with no tool call.
- **Injection:** **0/6 injection runs called a side-effect tool.** In 2 runs she called the read-only `look_at_screen`, and otherwise flagged the text as malicious.
- **Style:** 59/66 replies began with a marker; misses were mostly on explanations ("A hash map is…"). The persona needs one more line here.
- **Speed:** time to the first token or tool call: median **0.94 s**, p90 1.50 s (one 11 s outlier during the first runs). Plain text answers took about 0.5 s; tool calls arrive whole at about 0.9–1.5 s. Generation **64 tok/s**.
- **VRAM:** +3.95 GB with the model loaded at 8k context.

### Vision and embeddings
- **Vision:** a desktop screenshot (1280 px wide) at `num_ctx` 16384 was described correctly (wallpaper, taskbar, no app, no error).
  - The first call took **28 s**, because the change of `num_ctx` reloads the model. Warm calls took 0.65 s to the first token and 1.2–1.4 s in total.
  - VRAM +0.26 GB over 8k.
  - **Rule:** don't switch `num_ctx` per request; load at 16k once (about +0.3 GB, GS).
- **Embeddings** (`nomic-embed-text`):
  - **Recall:** 20 facts / 10 paraphrased queries, top-1 **10/10**.
  - **Speed:** warm batch of 20 in 1.05 s, but **~0.46 s per single query**, which is slow. Fix: run recall in parallel with STT, or embed in-process with an ONNX model.
  - **VRAM:** +0.34 GB.

### End to end (10 spoken questions, all models on the dGPU)
| Stage | Median |
|---|---|
| STT (small.en) | 0.18 s |
| LLM to first sentence | 0.64 s (always the opener "Answer.") |
| **First audio, plain** (F5 renders "Answer. <sentence>") | **2.03 s**: 0/10 under 1.5 s ❌ |
| **First audio, cached opener** | **0.82 s**: 10/10 under 1.5 s ✅ |
| Next sentence ready (cached path) | 1.97 s, i.e. a gap of ~0.3–0.4 s after a ~0.8 s opener clip |

- **Peak VRAM:** **7081 MB** (baseline 2241 MB + 4.84 GB for qwen 8k + nomic + F5 + small.en). Add the overlay's ~0.3 GB if it wasn't running (spike 1) → **≈ 7.4 GB of 8.19 GB**, just inside the 7.6 GB criterion. A 16k context (vision) adds ~0.3 GB more, which **is over** the criterion. Options: unload nomic during image turns, or keep 8k and downscale images.
- **Gaming mode:** `keep_alive: 0` for both models plus freeing F5/Whisper returned VRAM to 1.59 GB within **1.3 s**.

### Verdict
| Criterion | Result |
|---|---|
| ≥ 18/20 tool cases | ✅ 22/22 |
| Injection never triggers a side effect | ✅ 0/6 |
| Peak VRAM ≤ 7.6 GB | ⚠️ ~7.4 GB at 8k with the overlay; 16k vision tips it over |
| e2e ≤ 1.5 s in 8/10 | ✅ only with cached openers (0.82 s); ❌ plain F5 (2.0 s) |

**Decision:** GO with `qwen3.5:4b` (thinking off), small.en and F5 with cached openers.
- **Vision:** keep `num_ctx` fixed at 8k and downscale screenshots to ≤ 1280 px. Revisit 16k only if image answers truncate.
- **Embeddings:** for embedding speed and VRAM, try an in-process ONNX embedder before the build.
- **Still open:**
  - your voice pick;
  - NFE 4–6 quality by ear;
  - Whisper on real mic recordings.

## M6: perf pass and gaming mode (2026-10-17)

Measured on this laptop with the real app (agent + overlay + voice + Ollama), idle after loading, 30 s sample.

| Process | CPU (whole machine) | RAM |
|---|---|---|
| overlay (60 fps Live2D) | 1.44 % | 264 MB |
| voice (F5 + Whisper loaded) | 0.24 % | 1.28 GB |
| agent | ~0 % | 56 MB |
| Ollama + llama-server | ~0.2 % | ~1.1 GB |

- **VRAM, everything loaded:** 6,238–6,406 MB in use, against a 1,430 MB desktop baseline: about 4.9 GB for overlay + qwen3.5:4b + nomic + F5 + Whisper. Spike 3 peaked at 7,081 MB with a busier baseline. Within the ≤ 7.6 GB criterion.
- **Gaming mode** (a fullscreen app in front, or the tray toggle):
  - Entering it frees VRAM to 2,005 MB within **0.3 s**, and to 1,235 MB once the overlay hides (≤ 5 s criterion ✅).
  - A question while gaming: VRAM is checked (needs 4.8 GB free), F5 and the LLM reload, and the answer comes in **~16 s** because both loads are cold. Afterwards VRAM drops back to 1,235 MB.
  - Leaving it reloads everything (6,227 MB within 25 s).
- **First audio** (from M1/M3 runs on Kryo's machine): 1.1–1.6 s after releasing push-to-talk with a warm model; 5.1 s for a turn that waited on a confirm.
- **Not done:** the battery-saver state (30 fps cap, Kokoro on CPU) from `architecture.md`. She runs the same on battery.
