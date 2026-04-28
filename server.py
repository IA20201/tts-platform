"""MiMo TTS API 后端服务

FastAPI 实现，提供 RESTful TTS 接口。
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from config import Settings
from director.agent import DirectorAgent
from mimo_tts.audio_utils import estimate_duration, pcm16_to_wav, read_audio_to_b64
from mimo_tts.client import MiMoTTSClient
from pipeline.batch import BatchProcessor
from pipeline.splitter import TextSplitter
from voice_lab.manager import VoiceAssetManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  初始化
# ──────────────────────────────────────────────

settings = Settings()  # type: ignore[call-arg]
client = MiMoTTSClient(
    api_key=settings.mimo_api_key,
    base_url=settings.mimo_base_url,
    default_model=settings.tts_model,
    default_voice=settings.default_voice,
)
director = DirectorAgent(
    api_key=settings.llm_api_key or settings.mimo_api_key,
    base_url=settings.llm_base_url or settings.mimo_base_url,
    model=settings.llm_model,
)
voice_manager = VoiceAssetManager(settings.voices_db_path)

app = FastAPI(title="MiMo TTS Studio", version="0.1.0")


# ──────────────────────────────────────────────
#  请求/响应模型
# ──────────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    text: str
    director_instruction: str = ""
    model: Literal["mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"] = "mimo-v2.5-tts"
    voice: str = "Chloe"
    audio_format: Literal["wav", "mp3", "pcm16"] = "wav"
    auto_director: bool = False


class VoiceDesignRequest(BaseModel):
    voice_description: str
    text: str = "你好，这是一个音色预览测试。"
    audio_format: Literal["wav", "mp3", "pcm16"] = "wav"


class VoiceCloneRequest(BaseModel):
    text: str
    audio_format: Literal["wav", "mp3", "pcm16"] = "wav"
    director_instruction: str = ""


class BatchRequest(BaseModel):
    texts: list[str]
    ids: list[str] | None = None
    director_instruction: str = ""
    auto_director: bool = True
    model: str = "mimo-v2.5-tts"
    voice: str = "Chloe"
    concurrency: int = 10


class TTSResponse(BaseModel):
    audio_base64: str
    audio_format: str
    duration_seconds: float
    size_bytes: int


# ──────────────────────────────────────────────
#  端点
# ──────────────────────────────────────────────

@app.get("/")
def root():
    return {"name": "MiMo TTS Studio", "version": "0.1.0", "status": "running"}


@app.get("/voices")
def list_voices():
    """列出所有可用音色"""
    return {
        "built_in": voice_manager.get_built_in_voices(),
        "custom": voice_manager.list_voices(),
    }


@app.post("/synthesize", response_model=TTSResponse)
def synthesize(req: SynthesizeRequest):
    """语音合成"""
    try:
        instruction = req.director_instruction
        if req.auto_director and not instruction:
            instruction = director.generate_instruction(req.text)

        audio = client.synthesize(
            text=req.text,
            director_instruction=instruction,
            model=req.model,
            voice=req.voice,
            audio_format=req.audio_format,
        )
        pcm_len = len(audio) - 44 if req.audio_format == "wav" else len(audio)
        return TTSResponse(
            audio_base64=base64.b64encode(audio).decode(),
            audio_format=req.audio_format,
            duration_seconds=estimate_duration(audio[44:]) if req.audio_format == "wav" else 0,
            size_bytes=len(audio),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/synthesize/raw")
def synthesize_raw(req: SynthesizeRequest):
    """语音合成 — 返回原始音频文件"""
    try:
        instruction = req.director_instruction
        if req.auto_director and not instruction:
            instruction = director.generate_instruction(req.text)

        audio = client.synthesize(
            text=req.text,
            director_instruction=instruction,
            model=req.model,
            voice=req.voice,
            audio_format=req.audio_format,
        )
        media = {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "pcm16": "audio/pcm",
        }.get(req.audio_format, "audio/wav")
        return Response(content=audio, media_type=media)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/voice-design")
def voice_design(req: VoiceDesignRequest):
    """音色设计"""
    try:
        audio = client.voice_design(req.voice_description, req.text, req.audio_format)
        return TTSResponse(
            audio_base64=base64.b64encode(audio).decode(),
            audio_format=req.audio_format,
            duration_seconds=estimate_duration(audio[44:]) if req.audio_format == "wav" else 0,
            size_bytes=len(audio),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/voice-clone")
async def voice_clone(
    text: str,
    audio_format: str = "wav",
    director_instruction: str = "",
):
    """音色克隆 — 需要通过 multipart/form-data 上传音频文件"""
    # 注意：这个简化版用 query params，完整版需要 UploadFile
    raise HTTPException(status_code=501, detail="请使用 /voice-clone/upload 端点")


@app.post("/voice-clone/b64", response_model=TTSResponse)
def voice_clone_b64(sample_base64: str, sample_mime: str, text: str, audio_format: str = "wav", director_instruction: str = ""):
    """音色克隆 — Base64 输入"""
    try:
        audio = client.voice_clone_from_b64(sample_base64, sample_mime, text, audio_format)
        return TTSResponse(
            audio_base64=base64.b64encode(audio).decode(),
            audio_format=audio_format,
            duration_seconds=estimate_duration(audio[44:]) if audio_format == "wav" else 0,
            size_bytes=len(audio),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch")
async def batch_synthesize(req: BatchRequest):
    """批量合成"""
    try:
        processor = BatchProcessor(
            client=client,
            max_concurrency=req.concurrency,
            output_dir=settings.output_dir,
        )
        items = []
        for i, text in enumerate(req.texts):
            item_id = req.ids[i] if req.ids and i < len(req.ids) else f"item_{i}"
            items.append({
                "id": item_id,
                "text": text,
                "instruction": req.director_instruction,
            })

        director_agent = director if req.auto_director else None
        results = await processor.process_texts(
            items,
            use_director=req.auto_director,
            director_agent=director_agent,
            voice=req.voice,
            model=req.model,
        )
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/director/generate")
def generate_director(text: str):
    """生成导演指令"""
    try:
        instruction = director.generate_instruction(text)
        return {"text": text, "instruction": instruction}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=18900)
