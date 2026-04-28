"""音频工具：Base64 编解码、PCM16→WAV 转换、PCM16 拼接"""

from __future__ import annotations

import base64
import io
import struct

import numpy as np

# MiMo TTS 输出参数
SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes


def b64_to_bytes(b64_str: str) -> bytes:
    """Base64 字符串 → 原始 bytes"""
    return base64.b64decode(b64_str)


def bytes_to_b64(data: bytes) -> str:
    """原始 bytes → Base64 字符串"""
    return base64.b64encode(data).decode("utf-8")


def read_audio_to_b64(file_path: str) -> tuple[str, str]:
    """读取音频文件，返回 (base64_str, mime_type)"""
    with open(file_path, "rb") as f:
        data = f.read()
    mime = "audio/wav" if file_path.endswith(".wav") else "audio/mpeg"
    return base64.b64encode(data).decode("utf-8"), mime


def pcm16_chunks_to_bytes(chunks: list[bytes]) -> bytes:
    """多个 PCM16 chunk → 拼接后的原始 PCM16 bytes"""
    return b"".join(chunks)


def pcm16_to_wav(pcm_data: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """PCM16 原始数据 → 带 WAV 头的完整文件

    关键：批量合成统一走 pcm16 流式收集，最后套 WAV 头。
    WAV 拼接会导致文件头损坏，PCM16 拼接再套头最稳。
    """
    num_samples = len(pcm_data) // SAMPLE_WIDTH
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,       # 文件大小 - 8
        b"WAVE",
        b"fmt ",
        16,                   # fmt chunk size
        1,                    # PCM format
        CHANNELS,
        sample_rate,
        sample_rate * CHANNELS * SAMPLE_WIDTH,  # byte rate
        CHANNELS * SAMPLE_WIDTH,                # block align
        16,                   # bits per sample
        b"data",
        data_size,
    )
    return header + pcm_data


def pcm16_to_numpy(pcm_data: bytes) -> np.ndarray:
    """PCM16 bytes → numpy float32 数组（-1.0 ~ 1.0）"""
    samples = np.frombuffer(pcm_data, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def numpy_to_pcm16(samples: np.ndarray) -> bytes:
    """numpy float32 数组 → PCM16 bytes"""
    samples = np.clip(samples, -1.0, 1.0)
    return (samples * 32768).astype(np.int16).tobytes()


def estimate_duration(pcm_data: bytes, sample_rate: int = SAMPLE_RATE) -> float:
    """估算 PCM16 音频时长（秒）"""
    num_samples = len(pcm_data) // (SAMPLE_WIDTH * CHANNELS)
    return num_samples / sample_rate
