"""语音转写：faster-whisper 本地模型；音频只写临时文件，转写完立即删除。"""
from __future__ import annotations
import os
import subprocess
import tempfile
import threading

from . import config

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "models", f"faster-whisper-{config.ASR_MODEL}")
_lock = threading.Lock()
_model = None


class ASRError(RuntimeError):
    pass


def _model_or_raise():
    global _model
    with _lock:
        if _model is None:
            if not os.path.exists(os.path.join(MODEL_DIR, "model.bin")):
                raise ASRError(f"ASR 模型未就绪：{MODEL_DIR}/model.bin 不存在")
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_DIR, device=config.ASR_DEVICE, compute_type="int8")
    return _model


def _decode_to_16k_mono(src: str, dst: str) -> None:
    """用 ffmpeg 统一解码成 16k 单声道 wav：浏览器录的 webm/opus、手机 m4a 都能吃。"""
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                           "-ar", "16000", "-ac", "1", "-f", "wav", dst],
                          capture_output=True)
    if proc.returncode != 0:
        raise ASRError("音频解码失败：" + proc.stderr.decode("utf-8", "ignore")[:200])


def _wav_to_float32(path: str):
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0


def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> dict:
    m = _model_or_raise()
    fd, path = tempfile.mkstemp(suffix=suffix)
    wav_path = path + ".16k.wav"
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio_bytes)
        _decode_to_16k_mono(path, wav_path)
        audio = _wav_to_float32(wav_path)
        segments, info = m.transcribe(audio, language="zh", beam_size=5, vad_filter=True,
                                      initial_prompt="以下是普通话或带方言口音的劳动纠纷陈述，可能是工资、辞退、合同、加班。")
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segments]
        text = "".join(s["text"] for s in segs).strip()
        return {"text": text, "segments": segs,
                "duration": round(getattr(info, "duration", 0.0), 2),
                "language": getattr(info, "language", "zh")}
    finally:
        for p in (path, wav_path):
            try:
                os.remove(p)
            except OSError:
                pass
