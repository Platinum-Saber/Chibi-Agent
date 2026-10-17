"""Push-to-talk capture (16 kHz mono) and faster-whisper transcription.

The model runs on CUDA (int8_float16) while loaded and on the CPU (int8) when the
VRAM manager unloads it, so speech still works in gaming mode, only slower.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SR = 16000
# Words she must hear right ("status report" runs the briefing; Whisper heard "briefing" as "breathing").
HOTWORDS = "Raphael, Kryo, status report"


class Recorder:
    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks = []

        def callback(indata, _frames, _time, status):
            if status:
                log.debug("input status: %s", status)
            with self._lock:
                self._chunks.append(indata[:, 0].copy())

        self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                      callback=callback)
        self._stream.start()
        try:  # which mic: Windows may switch the default input under us
            self.device = sd.query_devices(self._stream.device)["name"]
        except Exception:
            self.device = "?"

    def stop(self) -> np.ndarray:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            chunks, self._chunks = self._chunks, []
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


class Stt:
    def __init__(self, model_name: str = "small.en"):
        self.model_name = model_name
        self.model = None
        self.device: str | None = None

    def load(self, device: str = "cuda") -> None:
        import torch  # loads the cuBLAS/cuDNN DLLs ctranslate2 needs
        from faster_whisper import WhisperModel

        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"
        if self.model is not None and self.device == device:
            return
        t0 = time.perf_counter()
        self.model = None
        self.model = WhisperModel(self.model_name, device=device,
                                  compute_type="int8_float16" if device == "cuda" else "int8",
                                  cpu_threads=8)
        self.device = device
        # Warm up the model (without VAD, which would drop the silence before it ran),
        # then load the Silero VAD model, which faster-whisper loads on first use.
        silence = np.zeros(SR, dtype=np.float32)
        list(self.model.transcribe(silence, language="en", beam_size=1)[0])
        self.transcribe(silence)
        log.info("stt %s on %s in %.1fs", self.model_name, device, time.perf_counter() - t0)

    def unload(self) -> None:
        """Free the GPU copy and fall back to the CPU."""
        if self.device == "cuda":
            self.model = None
            import gc
            import torch
            gc.collect()
            torch.cuda.empty_cache()
        self.load("cpu")

    def transcribe(self, audio: np.ndarray) -> str:
        if self.model is None:
            raise RuntimeError("stt not loaded")
        if audio.size < SR // 10:
            return ""
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=True, hotwords=HOTWORDS)
        return " ".join(s.text.strip() for s in segs).strip()
