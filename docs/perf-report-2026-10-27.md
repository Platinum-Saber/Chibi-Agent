# Performance report: Ollama, voice and 3D rendering (2026-10-27)

**Question:** why did her voice misbehave in the deployment (`Deployments\Raphael`) when the dev copy didn't, and what do the chat model, the voice and the 3D body cost on this laptop?

**Machine:** RTX 4060 Laptop 8 GB (8,188 MiB), Ryzen 7 7840HS, 16 GB single-channel RAM, Windows 11. Raphael v0.1.1 deployment; Ollama 0.40.x with `qwen3.5:4b` (8k context) and `nomic-embed-text`; voice with F5-TTS 1.1.22, faster-whisper `small.en` (int8_float16, CUDA) and Kokoro v1.0; Godot 4.7.2 rendering `raphael.vrm`.

## Summary
- **Each part is healthy on its own.** The chat model gives 55 tokens/s and 0.1–0.6 s to its first token when warm. Whisper transcribes 3 s of speech in 0.3 s. F5 speaks at 0.27–0.43× real time. The 3D body holds 59 fps at about 12 % GPU.
- **Together they nearly fill the 8 GB GPU.** In the live session it was 8.1 GB used out of 8.19 GB, about 1.6 GB of that from Windows and the NVIDIA App overlay. Any extra allocation then spills GPU memory into system RAM.
- **RAM was the second limit.** It was at 93 %: the chat model held 6.2 GB and the voice 5.5 GB. A GPU spill into nearly full RAM pages to disk. That's how 1.6 s of speech once took **61 s** to transcribe, and why the GPU stayed busy.
- **Why the dev copy didn't show it.** Until 2026-10-26, memory relief unloaded F5 and the chat model whenever RAM passed 90 %: 5 and 6 times that day. That kept both memories freer. Since today F5 stays loaded below 95 % RAM (your choice). Two of my v0.1.1 changes added pressure: the embedding model on the GPU, and a second copy of the CUDA libraries. The first start of a brand-new environment was also slow once.
- **Fixed today:**
  - embeddings on the CPU (−433 MB VRAM);
  - one copy of the CUDA libraries (−250–620 MB RAM);
  - memory relief no longer unloads F5 during startup;
  - the stale bubble on drag.
- **Biggest remaining win (your call):** turn off the NVIDIA App overlay (−830 MB VRAM).

## What happened in the live session (logs)
| Time | Log | Meaning |
|---|---|---|
| 16:56:17 | voice starts; F5 loaded only at 16:59:15 | the first start of a fresh torch install took 3 min (one-time) |
| 16:59:35 | `RAM 93% (threshold 90%)`; `llama-server 6210` MB, voice `5465` MB private | RAM nearly full |
| 16:59:42 | `voice idle 207s … unloading F5`; then `unloaded the language model` | relief fired 2 s after F5 loaded and cut off her reaction clips (fixed: startup grace) |
| 17:08:52 | `first audio 8.16 s` for "What time is it?" | the chat model reloading cold: 8.17 s measured below |
| 17:11:38 | `heard (61494 ms)` for a 1.6 s clip | Whisper starved: GPU full and RAM full |

## Ollama: qwen3.5:4b
Her real system prompt (3,378 characters) and tools: 5 tools (tool selection's typical subset) or all 37.

| Measure | Alone | With voice and 3D loaded (v0.1.1 as shipped) | With voice and 3D loaded (fixed) |
|---|---|---|---|
| Cold load (8k ctx) | **8.17 s** | — | — |
| VRAM, Ollama's estimate | 3,209 MB | 3,209 MB | 3,209 MB |
| VRAM, Windows counter (with CUDA context and compute buffers) | 3,976 MB | 3,976 MB | 3,976 MB |
| Pinned host memory (normal: `CUDA_Host` model buffer 497 MiB plus compute) | 634 MB | 634 MB | 634 MB |
| Generation speed | 48–58 tok/s (≈55) | 45.6–48.3 tok/s (≈47) | 41.1–49.5 tok/s (≈47) |
| First token, new prompt (5 / 37 tools) | 1.10 / 1.62 s | 1.08 / 0.95–1.20 s | 1.48 / 1.24–1.85 s |
| First token, repeated prompt (cached prefix) | 0.09–0.59 s | 0.09–0.65 s | 0.10–0.63 s |
| Prompt size (5 / 37 tools) | 1,398 / 3,772 tokens | same | same |

- All 33 layers are on the GPU; nothing of the model runs on the CPU.
- Next to the voice and the 3D body, generation slows by about 15 %. That's shared GPU time, not a memory spill.
- Sending all 37 tools adds about 0.5 s on a new prompt (2,400 more prompt tokens), so per-turn tool selection is worth keeping.

## Voice: Whisper, Kokoro, F5 (one process, as the voice runs them)
| Measure | Two CUDA copies (v0.1.1) | One copy (fixed) |
|---|---|---|
| Whisper load (CUDA) | 4.6 s, 453 MB VRAM | 4.9 s, 453 MB VRAM |
| Whisper: 2.6 / 3.3 / 3.2 s of speech | 0.42 / 0.28 / 0.28 s | 0.42–0.43 / 0.33 / 0.31 s |
| Kokoro load / speed | 3.5 s / 0.52–0.54× real time (first line 1.9× while warming up) | same |
| torch import / F5 load (with its warm-up line) | 3.8 s / 25.3 s | 3.6 s / 25.7 s |
| F5: 2.9 / 4.2 / 3.9 s of audio | 1.25 / 1.12 / 1.06 s (0.27–0.43× real time) | 1.43 / 1.35 / 1.34 s with Ollama and 3D beside it |
| VRAM, everything loaded | 1,277 MB | 1,277 MB |
| Private RAM after F5 loads | **6,082 MB** | **5,464 MB** |
| Private RAM, everything loaded | 5,770 MB | 5,521 MB |
| CUDA DLLs loaded (cuBLAS, cuBLASLt, cudart, cuDNN) | 9: NVIDIA wheels and torch, both | 5: torch's, plus ctranslate2's own cuDNN stub |

- **The duplicate libraries cost RAM, not VRAM:** 250–620 MB more private memory, and a heavier working set (3.1 GB against 2.7 GB).
- **Beside Ollama and the 3D body:** Whisper stays at 0.31–0.43 s and F5 at 0.33–0.53× real time. F5's load grows to 32–37 s while the GPU is shared.

## 3D body: Godot renderer
The renderer ran off-screen at her overlay size (520 px tall, 2560×1439 window), playing the Talk clip, 20 s per setting.

| Supersampling | MSAA | VRAM | GPU (3D engine), avg / max | fps |
|---|---|---|---|---|
| **2.0 (current)** | 2× | **580 MB** | 12.2 / 15.2 % | 59.2 |
| 1.5 | 2× | 426 MB | 12.2 / 13.8 % | 59.3 |
| 1.0 | 2× | 295 MB | 9.1 / 11.3 % | 59.3 |

The 3D body isn't what keeps the GPU at 100 %; it costs about 12 %. Its VRAM matches `overlay3d/README.md`'s table.

## Everything at once: who holds the GPU
Chat model warm, 3D body at 2.0/2×, voice with F5 loaded, then the chat model timed beside F5.

| Process | v0.1.1 as shipped | Fixed |
|---|---|---|
| Ollama chat model | 3,976 MB | 3,976 MB |
| Voice (F5 + Whisper) | 1,277 MB | 1,277 MB |
| Windows desktop (dwm) | 925 MB | 928 MB |
| **NVIDIA App overlay** (not Raphael) | **832 MB** | **832 MB** |
| Godot 3D body | 580 MB | 580 MB |
| Ollama embedding model | 433 MB | 0 (on the CPU) |
| Others (explorer, csrss, Claude…) | ~210 MB | ~210 MB |
| **Total** | **≈ 8,230 MB of 8,188: full** | **≈ 7,800 MB: about 390 MB free** |

- Raphael's own share is about 6.1 GB once fixed: chat model, voice, 3D body, and the overlay window's ~120 MB.
- The rest is Windows and the NVIDIA overlay.
- About 390 MB is left for what grows during use:
  - a screenshot turn (vision, 16k context);
  - F5 on a long sentence;
  - the Customize preview.

## Why the dev copy behaved better
1. **Memory relief used to free the GPU often.** At RAM ≥ 90 % it unloaded F5 (about 1.3 GB VRAM and 5 GB RAM) and the chat model: 5 F5 and 6 chat unloads on 2026-10-26. Since today F5 stays unless RAM ≥ 95 % (Saber's call), so it stays loaded almost all the time. That's better for her voice and tighter for memory.
2. **Duplicate CUDA libraries** (v0.1.1, my change): Whisper took NVIDIA's wheels while F5 took torch's copy: +250–620 MB RAM. The dev copy had only torch's copy until it was synced today. Fixed: torch's copy comes first when F5 is installed.
3. **The embedding model on the GPU** (433 MB): it was there in dev too, but with F5 unloaded more often it fit. Fixed: it runs on the CPU at 34–37 ms a query.
4. **A one-time cold start:** the deployment's fresh torch took 3 min to import the first time. Later starts load F5 in 14–26 s.

## Recommendations
1. **Turn off the NVIDIA App overlay** (NVIDIA App → Settings → in-game overlay, or Alt+Z → settings): −830 MB VRAM, the biggest single win. It's your setting.
2. **Give memory relief a VRAM guard** (follow-up): unload F5 when free VRAM falls under about 400 MB, or before a screenshot turn, and reload it on push-to-talk. RAM-only rules miss the GPU running full.
3. **3D at 1.5 / 2×** if VRAM stays tight: −154 MB, same 59 fps. Your call on the look (`[overlay] render_scale`).
4. Keep per-turn tool selection: all 37 tools cost about 0.5 s more on a new prompt.
5. Re-measure a screenshot ("look at this") turn with everything loaded. It wasn't covered here, and it's the largest allocation she makes.

## Reproduce
Quit Raphael first. The scripts are in `spikes/perf/` and the raw results in `spikes/perf/results/`:
- `bench_ollama.py <out.json>` (agent venv);
- `bench_voice.py <label> <wheels|torch> <out.json>` (voice venv);
- `bench_godot.ps1 -Out <file>`;
- `bench_all.ps1 -Label <name> [-DllOrder torch] [-EmbedOnGpu]` (everything at once).
