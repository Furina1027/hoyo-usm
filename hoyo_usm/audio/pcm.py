"""PCM / WAV 工具：WAV 解析、priming 裁剪、ffmpeg 编码（FLAC/AAC）与 ADX 解码。"""

from __future__ import annotations

import io
import os
import subprocess
import wave
from pathlib import Path


class FfmpegError(RuntimeError):
    pass


def _run_ffmpeg(ffmpeg: str, args: list[str], *, hint: str = "") -> bytes:
    # 窗口应用（console=False）下子进程会弹出黑色控制台，必须 CREATE_NO_WINDOW
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    cmd = [ffmpeg, "-y", "-v", "error"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=600, creationflags=flags)
    except FileNotFoundError as exc:
        raise FfmpegError(f"找不到 ffmpeg（{ffmpeg}）：{exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise FfmpegError(f"ffmpeg 失败{('（' + hint + '）') if hint else ''}: {err[:400]}")
    return proc.stderr


def wav_frames(wav: bytes) -> tuple[int, int, int]:
    """RIFF WAV → (总帧数, 声道数, 采样率)。"""
    with wave.open(io.BytesIO(wav), "rb") as w:
        return w.getnframes(), w.getnchannels(), w.getframerate()


def wav_pcm(wav: bytes) -> bytes:
    """RIFF WAV → 裸 s16le PCM。"""
    with wave.open(io.BytesIO(wav), "rb") as w:
        return w.readframes(w.getnframes())


def write_wav(path: Path, wav: bytes) -> None:
    path.write_bytes(wav)


def trim_pcm_frames(pcm: bytes, channels: int, delay: int, padding: int) -> bytes:
    """按帧裁剪 priming：去头部 encoder_delay 帧、尾部 encoder_padding 帧。

    输入为交错 s16le PCM；帧 = 1 采样 × 声道数。
    """
    frame_bytes = channels * 2
    total = len(pcm) // frame_bytes
    start = min(delay, total)
    end = max(start, total - min(padding, total - start))
    return pcm[start * frame_bytes: end * frame_bytes]


def make_wav_bytes(pcm: bytes, channels: int, sample_rate: int) -> bytes:
    """裸 s16le PCM → RIFF WAV。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def encode_audio(ffmpeg: str, src_wav: Path, dst: Path, codec: str, *, aac_bitrate: str = "256k") -> None:
    """WAV → FLAC/AAC（WAV 场景直接由调用方复制，不走这里）。"""
    args = ["-i", str(src_wav)]
    if codec == "flac":
        args += ["-c:a", "flac"]
    elif codec == "aac":
        args += ["-c:a", "aac", "-b:a", aac_bitrate]
    else:
        raise ValueError(f"不支持的音频编码 {codec}")
    _run_ffmpeg(ffmpeg, args + [str(dst)], hint=f"{codec} 编码 {src_wav.name}")


def decode_adx(ffmpeg: str, src_adx: Path, dst_wav: Path) -> None:
    """ADX → WAV（ffmpeg 原生 ADX 解码器；文件需已补 (c)CRI）。"""
    _run_ffmpeg(ffmpeg, ["-f", "adx", "-i", str(src_adx), "-c:a", "pcm_s16le", str(dst_wav)],
                hint="ADX 解码")
