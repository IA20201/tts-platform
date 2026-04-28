"""MiMo V2.5 TTS 统一客户端

封装三款 TTS 模型：
- mimo-v2.5-tts: 内置精品音色
- mimo-v2.5-tts-voicedesign: 文本描述生成音色
- mimo-v2.5-tts-voiceclone: 音频样本复刻音色
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Generator
from pathlib import Path

import numpy as np
from openai import AsyncOpenAI, OpenAI

from .audio_utils import (
    SAMPLE_RATE,
    bytes_to_b64,
    pcm16_chunks_to_bytes,
    pcm16_to_wav,
    read_audio_to_b64,
)
from .models import (
    AudioFormat,
    TTSModel,
    TTSRequest,
    TTSResponse,
    VoiceCloneRequest,
    VoiceDesignRequest,
)

logger = logging.getLogger(__name__)


class MiMoTTSClient:
    """封装 MiMo V2.5 TTS 三款模型的统一客户端"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.xiaomimimo.com/v1",
        default_model: str = "mimo-v2.5-tts",
        default_voice: str = "Chloe",
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.default_model = default_model
        self.default_voice = default_voice

    # ──────────────────────────────────────────────
    #  核心合成方法
    # ──────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        director_instruction: str = "",
        model: str | TTSModel = "mimo-v2.5-tts",
        voice: str = "mimo_default",
        audio_format: str = "wav",
    ) -> bytes:
        """单次同步合成，返回音频 bytes"""
        model_str = model.value if isinstance(model, TTSModel) else model
        messages = self._build_messages(text, director_instruction, model_str)
        fmt = self._resolve_format(audio_format, stream=False)

        params: dict = {
            "model": model_str,
            "messages": messages,
            "audio": {"format": fmt},
            "stream": False,
        }
        # voice 参数：voicedesign 不支持，tts/voiceclone 需要
        if model_str != "mimo-v2.5-tts-voicedesign":
            params["audio"]["voice"] = voice

        logger.info("合成请求: model=%s, voice=%s, fmt=%s, text_len=%d",
                     model_str, voice, fmt, len(text))
        completion = self.client.chat.completions.create(**params)
        return self._decode_audio_response(completion, fmt)

    async def synthesize_async(
        self,
        text: str,
        director_instruction: str = "",
        model: str | TTSModel = "mimo-v2.5-tts",
        voice: str = "mimo_default",
        audio_format: str = "wav",
    ) -> bytes:
        """异步合成，返回音频 bytes"""
        model_str = model.value if isinstance(model, TTSModel) else model
        messages = self._build_messages(text, director_instruction, model_str)
        fmt = self._resolve_format(audio_format, stream=False)

        params: dict = {
            "model": model_str,
            "messages": messages,
            "audio": {"format": fmt},
            "stream": False,
        }
        if model_str != "mimo-v2.5-tts-voicedesign":
            params["audio"]["voice"] = voice

        completion = await self.async_client.chat.completions.create(**params)
        return self._decode_audio_response(completion, fmt)

    # ──────────────────────────────────────────────
    #  流式合成（PCM16 chunks）
    # ──────────────────────────────────────────────

    def synthesize_stream(
        self,
        text: str,
        director_instruction: str = "",
        model: str | TTSModel = "mimo-v2.5-tts",
        voice: str = "mimo_default",
    ) -> Generator[bytes, None, None]:
        """流式返回 PCM16 原始 chunks"""
        model_str = model.value if isinstance(model, TTSModel) else model
        messages = self._build_messages(text, director_instruction, model_str)

        params: dict = {
            "model": model_str,
            "messages": messages,
            "audio": {"format": "pcm16"},
            "stream": True,
        }
        if model_str != "mimo-v2.5-tts-voicedesign":
            params["audio"]["voice"] = voice

        completion = self.client.chat.completions.create(**params)
        for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            audio = getattr(delta, "audio", None)
            if audio and hasattr(audio, "data") and audio.data:
                yield base64.b64decode(audio.data)

    async def synthesize_stream_async(
        self,
        text: str,
        director_instruction: str = "",
        model: str | TTSModel = "mimo-v2.5-tts",
        voice: str = "mimo_default",
    ):
        """异步流式返回 PCM16 原始 chunks"""
        model_str = model.value if isinstance(model, TTSModel) else model
        messages = self._build_messages(text, director_instruction, model_str)

        params: dict = {
            "model": model_str,
            "messages": messages,
            "audio": {"format": "pcm16"},
            "stream": True,
        }
        if model_str != "mimo-v2.5-tts-voicedesign":
            params["audio"]["voice"] = voice

        completion = await self.async_client.chat.completions.create(**params)
        async for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            audio = getattr(delta, "audio", None)
            if audio and hasattr(audio, "data") and audio.data:
                yield base64.b64decode(audio.data)

    def collect_stream_to_wav(
        self,
        text: str,
        director_instruction: str = "",
        model: str | TTSModel = "mimo-v2.5-tts",
        voice: str = "mimo_default",
    ) -> bytes:
        """流式收集 PCM16 chunks → 拼接 → 转 WAV（批量长文本推荐路径）"""
        chunks = list(self.synthesize_stream(text, director_instruction, model, voice))
        pcm_data = pcm16_chunks_to_bytes(chunks)
        return pcm16_to_wav(pcm_data)

    async def collect_stream_to_wav_async(
        self,
        text: str,
        director_instruction: str = "",
        model: str | TTSModel = "mimo-v2.5-tts",
        voice: str = "mimo_default",
    ) -> bytes:
        """异步版本：流式收集 PCM16 → WAV"""
        chunks = []
        async for chunk in self.synthesize_stream_async(text, director_instruction, model, voice):
            chunks.append(chunk)
        pcm_data = pcm16_chunks_to_bytes(chunks)
        return pcm16_to_wav(pcm_data)

    # ──────────────────────────────────────────────
    #  VoiceDesign
    # ──────────────────────────────────────────────

    def voice_design(
        self,
        voice_description: str,
        text: str,
        audio_format: str = "wav",
    ) -> bytes:
        """用自然语言描述生成音色，voice_description 传入 user 角色"""
        messages = [
            {"role": "user", "content": voice_description},
            {"role": "assistant", "content": text},
        ]
        fmt = self._resolve_format(audio_format, stream=False)
        completion = self.client.chat.completions.create(
            model="mimo-v2.5-tts-voicedesign",
            messages=messages,
            audio={"format": fmt},
            stream=False,
        )
        return self._decode_audio_response(completion, fmt)

    def voice_design_preview(
        self,
        voice_description: str,
        text: str = "你好，这是一个音色预览测试。",
    ) -> bytes:
        """VoiceDesign 快速预览，返回 WAV"""
        return self.voice_design(voice_description, text, "wav")

    # ──────────────────────────────────────────────
    #  VoiceClone
    # ──────────────────────────────────────────────

    def voice_clone(
        self,
        sample_audio_path: str,
        text: str,
        audio_format: str = "wav",
    ) -> bytes:
        """上传音频样本复刻音色。sample_audio_path 支持 mp3/wav"""
        b64_str, mime = read_audio_to_b64(sample_audio_path)
        messages = [
            {"role": "user", "content": ""},  # voiceclone 必须有 user 消息，可为空
            {"role": "assistant", "content": text},
        ]
        fmt = self._resolve_format(audio_format, stream=False)
        completion = self.client.chat.completions.create(
            model="mimo-v2.5-tts-voiceclone",
            messages=messages,
            audio={
                "format": fmt,
                "voice": f"data:{mime};base64,{b64_str}",
            },
            stream=False,
        )
        return self._decode_audio_response(completion, fmt)

    def voice_clone_from_b64(
        self,
        sample_b64: str,
        sample_mime: str,
        text: str,
        audio_format: str = "wav",
    ) -> bytes:
        """从 Base64 数据复刻音色（用于 VoiceAssetManager）"""
        messages = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": text},
        ]
        fmt = self._resolve_format(audio_format, stream=False)
        completion = self.client.chat.completions.create(
            model="mimo-v2.5-tts-voiceclone",
            messages=messages,
            audio={
                "format": fmt,
                "voice": f"data:{sample_mime};base64,{sample_b64}",
            },
            stream=False,
        )
        return self._decode_audio_response(completion, fmt)

    # ──────────────────────────────────────────────
    #  内部方法
    # ──────────────────────────────────────────────

    @staticmethod
    def _build_messages(text: str, instruction: str, model: str) -> list[dict]:
        """构建 messages 数组。

        关键：
        - voiceclone 的 user 角色必须存在（即使内容为空），否则 API 报错。
        - voicedesign 的 user 角色必须有内容（音色描述）。
        - 普通 tts 的 user 角色可选（导演指令）。
        """
        messages = []
        if model == "mimo-v2.5-tts-voiceclone":
            # voiceclone: user 消息必须存在，可为空
            messages.append({"role": "user", "content": instruction or ""})
        elif model == "mimo-v2.5-tts-voicedesign":
            # voicedesign: user 消息必须有内容（音色描述）
            if not instruction:
                raise ValueError("voicedesign 模型必须提供 user 角色的音色描述")
            messages.append({"role": "user", "content": instruction})
        else:
            # 普通 tts: user 消息可选（导演指令）
            if instruction:
                messages.append({"role": "user", "content": instruction})

        messages.append({"role": "assistant", "content": text})
        return messages

    @staticmethod
    def _resolve_format(audio_format: str, stream: bool) -> str:
        """流式模式强制 pcm16，非流式按用户指定"""
        if stream:
            return "pcm16"
        fmt = audio_format.lower()
        if fmt in ("pcm", "pcm16"):
            return "pcm16"
        return fmt

    @staticmethod
    def _decode_audio_response(completion, fmt: str) -> bytes:
        """从非流式 completion 中提取音频 bytes"""
        message = completion.choices[0].message
        audio = getattr(message, "audio", None)
        if audio and hasattr(audio, "data") and audio.data:
            return base64.b64decode(audio.data)
        raise ValueError(f"API 返回中未找到音频数据: {completion}")
