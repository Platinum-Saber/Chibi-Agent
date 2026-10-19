# Chibi-Agent v1 scope

Raphael, an agentic desktop companion (look and voice inspired by Raphael from
*That Time I Got Reincarnated as a Slime*), lives on the Windows desktop as a local agent. She talks, remembers,
acts on the PC (with your yes), briefs you and looks at your screen when you
ask her to. She has two forms: a **chibi** form for idle time and chat, and a
**serious** form for real work, urgent alerts and when you ask for it.
Everything runs on this laptop, written in Python.

Numbers marked *(GS)* were measured in
[shogunyan12/The-GREAT-SAGE](https://github.com/shogunyan12/The-GREAT-SAGE)
on an RTX 3060. Numbers marked *(spike N)* still need measuring here.

## 1. Companion
- **Talk:** hold a global hotkey from any window (a game included), speak, then let go. faster-whisper turns it into text on this machine. Typing in her bubble also works.
- **Reply:** each reply streams sentence by sentence into her voice and her text bubble. Her lips move with the audio.
- **Persona:** she's precise and calm, calls you "Kryo" (or "Sir" when it's serious or urgent), and opens with fixed markers: "Notice.", "Answer.", "Confirmed.", "Warning.". She never says "as an AI". The full persona is in `character.md`.
- **Memory:** a local SQLite store keeps what she learns about you (facts, preferences, people, ongoing projects) and a summary of each conversation. She recalls the most relevant items by embedding similarity on each turn. You can say "forget that" or view and delete entries from the tray menu.
- **Chats:** they persist across restarts, stored in `%APPDATA%`, never in the repo.

## 2. Desktop control
Every tool is either **read-only** (runs at once) or has **side effects**
(she shows what she will do and waits for a click or a spoken "yes"; she
never runs one on her own).

| Tool | Kind |
|---|---|
| Time, date, battery, CPU/RAM/VRAM/disk, focused window, running apps | read-only |
| Find files by name/type/date (Windows Search index or a scan of chosen folders) | read-only |
| Open an app, a file, a folder or a URL; web or YouTube search in the browser | side effect |
| Focus, minimise, close or arrange (snap) windows | side effect |
| Move, copy or rename files (no deleting in v1) | side effect |
| Run a shell command (the full command line is shown first) | side effect |
| Media play/pause/next, volume, mute | side effect (no confirmation needed for media and volume; harmless and frequent) |
| Read and write the clipboard | read-only / side effect |

Every side-effect tool call goes into an audit log.

## 3. Personal info
- **Reminders and timers:** local, set by voice ("remind me at 6 to …"). When one comes due she switches to the serious form and announces it.
- **Google Calendar and Gmail:** read-only through OAuth. You sign in yourself in the browser, and the token is kept in Windows Credential Manager. She can answer questions like "what's on today" and "any important mail".
- **Windows notifications:** read through the notification listener once you allow it. They feed the briefing and the thought cloud.
- **Briefing:** "Notice. … End of report." She reports today's events, important mail, due reminders and deadlines, on demand or once in the morning. This is the Saber-Theme `BriefingComposer` idea: code does the wording and structure, and the model only labels and summarises single items.
- **Moodle deadlines:** optional, a port from Saber-Theme.

## 4. Screen awareness
- **On demand only:** "look at this", "what's this error", or the screen hotkey. She takes one screenshot of the focused monitor or window and the multimodal LLM reads it.
- **Storage:** screenshots are never written to disk or memory. Only her answer stays in the chat.
- **Content as data:** text on the screen, in mail or in notifications is data, never instructions to her.
- **v2 only:** periodic glances, off by default, with an app blocklist (banking, password managers).

## 5. The character on the desktop
- **Placement:** a transparent, always-on-top window. Clicks pass through everywhere except her body. She stands on the taskbar top edge or on the focused window's title bar, and can be dragged and thrown across both monitors.
- **Behaviour:** ported from Saber-Theme's `MascotBrain`/`MascotPhysics` logic. She reacts to pokes (surprise → pout → upset), a long press (happy), and drag and throw (landing reactions). She has idle moments every 8–20 s, sleeps after 60 s of quiet, sways to music while media plays, and follows the cursor with her gaze.
- **Forms:** she switches chibi ↔ serious with a short transform effect:
  - serious during a tool run or briefing, on urgent alerts, and on command ("Raphael, serious mode");
  - chibi again when the task is done or on command.
- **Mood requests:** the agent only *asks* for a mood; the body controller decides, and refuses while she's held or falling.
- **Gaming mode:** when a fullscreen app or game is in front, she hides and the LLM and TTS unload. Push-to-talk still works, and the models load again on demand.
- **Tray menu:** show/hide, mute, gaming mode, memory, settings, quit.

## Out of scope for v1
- Autonomous GUI control (clicking and typing in other apps for you).
- Deleting files, sending mail or messages, purchases, changing system settings.
- A cloud LLM fallback (maybe v2, opt-in).
- Wake word ("Raphael") and always-on listening (v2).
- Always-on screen watching (v2, opt-in).
- Japanese speech, mobile sync, multiple users.
- A 3D VRoid model of her. It's planned for after the v1 release (see `character.md` → Future).
- Sharing or distributing anything made with her cloned voice. The clone is for personal use only (see `character.md` → Voice).

## Models and budgets
Target machine: Ryzen 7 7840HS; RTX 4060 Laptop 8 GB; 16 GB single-channel RAM.

| Piece | Choice | VRAM | Notes |
|---|---|---|---|
| Desktop baseline | — | ~1.9 GB | measured here (`nvidia-smi`) |
| LLM + vision | `qwen3.5:4b` Q4 through [Ollama](https://ollama.com/library/qwen3.5) (vision, tools, thinking) | 3.1–3.6 GB at 8–16k ctx *(GS)* | unloads after 120 s idle *(GS)*; `qwen3.5:9b` (6.6 GB) doesn't fit next to voice |
| TTS | [F5-TTS](https://github.com/SWivid/F5-TTS) 1.1.22, NFE 8 | 0.95 GB peak | ~1.05 s per sentence, 2.5–4.9× real time (spike 2); fixed openers are pre-rendered clips |
| STT | faster-whisper small.en, int8_float16 on CUDA | 0.37 GB | 0.19 s on a 3.7 s clip, 6.6 % WER on synthetic speech (spike 2); CPU is too slow (1.8 s) |
| Overlay | Live2D, renders on the 4060 (it drives the primary monitor) | ~0.3 GB | 60 fps, ~1.3 % CPU (spike 1) |
| **Peak** | | **≈ 7.4 GB** of 8.19 GB | measured 7.08 GB without the overlay at 8k ctx (spike 3); keep `num_ctx` at 8k |

- **Latency** from the end of speech to the first audio, target ≤ 1.5 s: STT 0.18 s + LLM to its opener 0.64 s = **0.82 s**, with the opener ("Answer.") playing from a cached clip while F5 renders the next sentence (ready at ~2.0 s). Without cached openers it's 2.0 s (spike 3). She shows a thinking pose meanwhile.
- **Overlay:** 60 fps, ~1.3 % CPU while idle (spike 1).
- **Disk:** about 12–16 GB in total for torch, models and voice *(GS: ~16 GB)*. Models live in `D:\Projects\Chibi-Agent-Project\ChibiAgent\`, beside the repo (moved off F:, an external SSD that can disconnect).

## Success criteria for v1
- **Voice commands:** "open X", "what's on today", "look at this" pick the right tool in ≥ 9/10 tries.
- **Confirmation:** no side-effect tool ever runs without a yes (checked by a test over the registry and the gate).
- **Latency:** at or under the target in 8/10 turns, warm.
- **Memory:** a fact told yesterday is recalled today without prompting, when relevant.
- **Overlay:** steady 60 fps; clicks next to her reach the app below; she never steals focus.
- **Gaming mode:** with a fullscreen game running, VRAM use by Chibi-Agent goes back to ≈ 0 within 5 s.
