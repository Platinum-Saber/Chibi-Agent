# Saber's deployment, voice and GPU fixes (after v0.1.1)

**Goal:** keep Raphael running well from Saber's own deployment (`D:\Projects\Chibi-Agent-Project\Deployments\Raphael`, Start menu → Raphael), with both 3D characters, F5 and the 2D chibi.

## Decisions
- **Deployment:** Saber runs the deployed app, not `python chibi.py`. `packaging\deploy.ps1` builds it: the shipped app plus the VRMs, Mixamo motions and F5 (`voice\extras.txt`). Start menu shortcut only, no desktop one. Startup entry: `Startup\Raphael (Chibi-Agent).lnk` → `Raphael.exe`.
- **Personal config:** `%APPDATA%\ChibiAgent\config.toml` holds only paths outside the app (copy: `ChibiAgent\config-saber.toml`; the old one is `config.toml.bak-0.1.1`).
- **No automatic transform:** `[overlay] auto_serious = false`. She changes form only on "serious mode" / "chibi mode"; an outfit with one model in both forms never transforms. Her panels show beside the chibi.
- **Memory relief:** F5 is unloaded only at ≥ 95 % RAM (`voice_unload_pct`) and never in the first 600 s (`startup_grace_s`).
- **Embeddings:** on the CPU (`[ollama] embed_on_gpu = false`): 35 ms a query, saves 433 MB of VRAM.
- **CUDA libraries:** `env.cuda_dll_dirs` puts torch's lib first when F5 is installed, so the voice loads one copy (two cost +250–620 MB RAM).
- **Radeon 780M:** not used by Raphael. Embeddings there aren't worth it. Moving the 3D body there (about 580 MB VRAM back) is an idea Saber said not to test yet.
- **NVIDIA App overlay:** Saber turned it off (it held 830 MB of VRAM).
- **The VRMs never ship** (rurune's licence); their metadata stays rurune's.

## Files
- `packaging/deploy.ps1`: builds or updates the deployment (quit Raphael first).
- `packaging/{build,setup}.ps1`, `packaging/raphael.iss`: the installer; setup reads `extras.txt` and the config's model folders.
- `docs/perf-report-2026-10-27.md`: benchmarks (Ollama, voice, 3D, all together) and causes.
- `spikes/perf/`: the benchmark scripts and raw results.
- `overlay/chibi_overlay/stage.py`: `auto_serious`, `chibi_only` / `panels_on_chibi`, the bubble only extended by live speech.
- `agent/chibi_agent/memrelief.py`: the 95 % rule and startup grace.
- `agent/chibi_agent/memory/__init__.py`: CPU embeddings.
- `voice/chibi_voice/env.py`: the CUDA DLL order.
- `handoffs/release-0.1.1.md`: the release itself.

## State
- **Works:** the deployment with all three characters, the F5 voice, pose reactions, and the startup entry.
- **Copied into the deployment but not yet checked live:** the latest fixes (no transform, bubble, CPU embeddings, CUDA order). Saber needs tray → Restart agent. A full `deploy.ps1` re-run would also sync everything.
- **Untested:** a screenshot ("look at this") turn with everything loaded; Godot's `--import` of a newly dropped VRM on a clean install; the mixed 2D-chibi/3D-serious transform live.
- **Tag:** `v0.1.1` is at c5414a9 and `dist\Raphael-0.1.1-setup.exe` predates the later fixes. Moving the tag and rebuilding is undecided.
- **Panel font:** Saber's saved panel font is Consolas. Customize → Look → Default gives Electroharmonix.

## Next step
Ask Saber whether the restart shows no transform on replies and no stale bubble on drag, then offer the VRAM guard in memory relief (unload F5 when free VRAM is under ~400 MB or before a screenshot turn; reload on push-to-talk).
