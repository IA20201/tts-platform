from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TTSModel(str, Enum):
    TTS = "mimo-v2.5-tts"
    VOICE_DESIGN = "mimo-v2.5-tts-voicedesign"
    VOICE_CLONE = "mimo-v2.5-tts-voiceclone"


class AudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"
    PCM = "pcm"
    PCM16 = "pcm16"


class TTSRequest(BaseModel):
    text: str
    director_instruction: str = ""
    model: TTSModel = TTSModel.TTS
    voice: str = "mimo_default"
    audio_format: AudioFormat = AudioFormat.WAV
    stream: bool = False


class TTSResponse(BaseModel):
    audio_bytes: bytes
    audio_format: AudioFormat
    model: str
    duration_hint: float | None = None  # 估算时长（秒）


class VoiceDesignRequest(BaseModel):
    voice_description: str
    text: str
    audio_format: AudioFormat = AudioFormat.WAV
    stream: bool = False


class VoiceCloneRequest(BaseModel):
    sample_audio_b64: str  # Base64 编码的音频样本
    sample_mime: str = "audio/mpeg"  # audio/mpeg 或 audio/wav
    text: str
    audio_format: AudioFormat = AudioFormat.WAV
    stream: bool = False


class SynthesisChunk(BaseModel):
    """流式合成的单个 chunk"""
    audio_data: bytes
    chunk_index: int
