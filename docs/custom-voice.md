# Give Raphael a custom voice (F5-TTS)

Raphael ships with Kokoro, a fast CPU voice with 54 presets (tray → Customize Raphael → Voice). For a voice of your own she can use **F5-TTS**, which copies a voice from one short clip. It runs on the GPU (about 1 GB of VRAM) and isn't installed by default: it adds torch and F5 (about 3 GB).

**Use voices you have the right to use.** Clone your own voice, or one you have permission for. A cloned voice stays on your PC: don't share its clips or recordings, and never use it to impersonate a real person.

## 1. Install F5
Close Raphael (tray → Quit), then in a terminal:

```bash
cd "%LOCALAPPDATA%\Programs\Raphael\voice"
..\bin\uv.exe sync --frozen --no-dev --extra f5
```

(From a repo checkout: `uv sync --extra f5` in `voice/`.)

## 2. Make a reference clip
- **Length:** 6–10 seconds of one person speaking. Stop at the end of a sentence.
- **Clean:** no music, no other voices, little room echo or noise. Remove the background with a tool like Demucs if needed.
- **Format:** WAV, mono, 24 kHz or more.
- **Transcript:** a `.txt` file with exactly what is said, word for word, next to the clip with the same name: `myvoice.wav` + `myvoice.txt`.

Keep the files somewhere of your own, for example `%APPDATA%\ChibiAgent\voices\`.

## 3. Turn it on
Add this to `%APPDATA%\ChibiAgent\config.toml` (create the file if it doesn't exist):

```toml
[voice]
f5 = true
reference = 'C:\Users\you\AppData\Roaming\ChibiAgent\voices\myvoice.wav'
reference_text = 'C:\Users\you\AppData\Roaming\ChibiAgent\voices\myvoice.txt'
speed = 0.90      # 0.85-1.0; lower is calmer
nfe = 8           # diffusion steps: 8 is fast, 16-32 is cleaner but slower
```

Start Raphael. The first F5 load takes a minute (it downloads the F5 model once); her fixed lines ("Answer.", "Confirmed." …) re-render in the new voice in the background.

## 4. Switch voices later
Tray → Customize Raphael → Voice: pick **F5** with any reference clip (a `.wav` with its `.txt` beside it), or a Kokoro preset, then Apply. "Test" speaks a line.

## If she still speaks with Kokoro
Look in `%LOCALAPPDATA%\ChibiAgent\logs\voice.log`:
- "F5-TTS isn't installed": step 1 didn't finish.
- "reference / reference_text aren't set or found": check both paths in `config.toml`.

To go back to Kokoro, set `f5 = false` (or remove the `[voice]` lines you added).
