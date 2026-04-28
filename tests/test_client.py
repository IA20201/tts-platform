"""MiMo TTS 客户端单元测试（mock 验证逻辑）"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from mimo_tts.audio_utils import pcm16_to_wav
from mimo_tts.client import MiMoTTSClient


@pytest.fixture
def client():
    return MiMoTTSClient(api_key="test_key", base_url="https://test.api/v1")


class TestBuildMessages:
    def test_normal_tts_with_instruction(self, client):
        msgs = client._build_messages("你好", "温柔地说", "mimo-v2.5-tts")
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "温柔地说"}
        assert msgs[1] == {"role": "assistant", "content": "你好"}

    def test_normal_tts_without_instruction(self, client):
        msgs = client._build_messages("你好", "", "mimo-v2.5-tts")
        assert len(msgs) == 1
        assert msgs[0] == {"role": "assistant", "content": "你好"}

    def test_voiceclone_empty_user_required(self, client):
        """voiceclone 必须有 user 消息，即使内容为空"""
        msgs = client._build_messages("你好", "", "mimo-v2.5-tts-voiceclone")
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": ""}
        assert msgs[1] == {"role": "assistant", "content": "你好"}

    def test_voicedesign_requires_instruction(self, client):
        """voicedesign 必须提供音色描述"""
        with pytest.raises(ValueError, match="必须提供"):
            client._build_messages("你好", "", "mimo-v2.5-tts-voicedesign")

    def test_voicedesign_with_instruction(self, client):
        msgs = client._build_messages("你好", "年轻男性音色", "mimo-v2.5-tts-voicedesign")
        assert msgs[0] == {"role": "user", "content": "年轻男性音色"}


class TestResolveFormat:
    def test_stream_forces_pcm16(self, client):
        assert client._resolve_format("wav", stream=True) == "pcm16"

    def test_wav_passthrough(self, client):
        assert client._resolve_format("wav", stream=False) == "wav"

    def test_pcm_normalized(self, client):
        assert client._resolve_format("pcm", stream=False) == "pcm16"

    def test_pcm16_passthrough(self, client):
        assert client._resolve_format("pcm16", stream=False) == "pcm16"

    def test_mp3_passthrough(self, client):
        assert client._resolve_format("mp3", stream=False) == "mp3"


class TestPcm16ToWav:
    def test_valid_wav_header(self):
        pcm_data = b"\x00\x00" * 100  # 100 samples of silence
        wav = pcm16_to_wav(pcm_data, sample_rate=24000)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert wav[12:16] == b"fmt "
        # 文件大小 = 44 header + pcm_data
        assert len(wav) == 44 + len(pcm_data)
