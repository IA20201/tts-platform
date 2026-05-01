"""MiMo TTS API 后端服务

FastAPI 实现，提供 RESTful TTS 接口。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "custom": [v for v in voice_manager.list_voices() if v.get("source") != "built_in"],
    }


# ── OpenAI 兼容端点（Kokoro 等第三方工具需要） ──


@app.get("/v1/models")
async def get_models():
    """返回可用模型列表（OpenAI 兼容格式）"""
    return {
        "data": [
            {"id": "mimo-v2.5-tts", "object": "model"},
            {"id": "mimo-v2.5-tts-voicedesign", "object": "model"},
            {"id": "mimo-v2.5-tts-voiceclone", "object": "model"},
        ]
    }


@app.get("/v1/audio/voices")
async def get_voices():
    """返回可用音色列表（OpenAI 兼容格式，Kokoro 扩展需要）"""
    all_voices = voice_manager.list_voices()
    return {"voices": [v["name"] for v in all_voices]}


@app.post("/v1/audio/speech")
async def audio_speech(request: dict):
    """Kokoro 扩展合成端点（OpenAI TTS 兼容格式）— 流式返回

    请求: {"model": "kokoro", "input": "文本", "voice": "Chloe", "response_format": "wav"}
    返回: 流式音频二进制（先发 WAV 头，再逐块发 PCM 数据）
    """
    import queue
    import threading

    text = request.get("input", "")
    voice_input = request.get("voice", "Chloe")
    clean_voice = voice_input.split("_", 1)[-1] if "_" in voice_input else voice_input

    chunk_queue: queue.Queue = queue.Queue()

    def _producer():
        try:
            for chunk in client.synthesize_stream(text, "", "mimo-v2.5-tts", clean_voice):
                chunk_queue.put(("data", chunk))
        except Exception as e:
            chunk_queue.put(("error", str(e)))
        finally:
            chunk_queue.put(("done", None))

    threading.Thread(target=_producer, daemon=True).start()

    # 先收到第一个 chunk 确定有数据，再拼 WAV 头返回
    first_type, first_data = chunk_queue.get()
    if first_type == "error":
        raise HTTPException(status_code=500, detail=first_data)

    sample_rate = 24000
    num_channels = 1
    bits_per_sample = 16

    def _stream():
        all_pcm = bytearray(first_data)
        while True:
            msg_type, chunk_data = chunk_queue.get()
            if msg_type == "error":
                break
            if msg_type == "done":
                break
            all_pcm.extend(chunk_data)

        # 全部收完后一次性输出完整 WAV（Kokoro 扩展需要完整文件才能播放）
        data_size = len(all_pcm)
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8

        header = bytearray()
        header += b"RIFF"
        header += (36 + data_size).to_bytes(4, "little")
        header += b"WAVE"
        header += b"fmt "
        header += (16).to_bytes(4, "little")
        header += (1).to_bytes(2, "little")
        header += num_channels.to_bytes(2, "little")
        header += sample_rate.to_bytes(4, "little")
        header += byte_rate.to_bytes(4, "little")
        header += block_align.to_bytes(2, "little")
        header += bits_per_sample.to_bytes(2, "little")
        header += b"data"
        header += data_size.to_bytes(4, "little")

        yield bytes(header)
        yield bytes(all_pcm)

    return StreamingResponse(_stream(), media_type="audio/wav")


@app.post("/synthesize", response_model=TTSResponse)
def synthesize(req: SynthesizeRequest):
    """语音合成 — 自动识别自定义音色并路由到对应 API"""
    try:
        instruction = req.director_instruction
        if req.auto_director and not instruction:
            instruction = director.generate_instruction(req.text)

        voice_info = voice_manager.get_voice(req.voice)
        source = voice_info.get("source", "built_in") if voice_info else None

        if source == "voiceclone":
            b64_data, mime = voice_manager.get_voiceclone_b64(req.voice)
            if not b64_data:
                raise ValueError(f"voiceclone 音色数据缺失: {req.voice}")
            audio = client.voice_clone_from_b64(b64_data, mime, req.text, req.audio_format, instruction)
        elif source == "voicedesign":
            desc = voice_info.get("description", "")
            if not desc:
                raise ValueError(f"voicedesign 音色描述缺失: {req.voice}")
            audio = client.voice_design(desc, req.text, req.audio_format)
        else:
            audio = client.synthesize(
                text=req.text,
                director_instruction=instruction,
                model=req.model,
                voice=req.voice,
                audio_format=req.audio_format,
            )

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

        voice_info = voice_manager.get_voice(req.voice)
        source = voice_info.get("source", "built_in") if voice_info else None

        if source == "voiceclone":
            b64_data, mime = voice_manager.get_voiceclone_b64(req.voice)
            if not b64_data:
                raise ValueError(f"voiceclone 音色数据缺失: {req.voice}")
            audio = client.voice_clone_from_b64(b64_data, mime, req.text, req.audio_format, instruction)
        elif source == "voicedesign":
            desc = voice_info.get("description", "")
            if not desc:
                raise ValueError(f"voicedesign 音色描述缺失: {req.voice}")
            audio = client.voice_design(desc, req.text, req.audio_format)
        else:
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
        audio = client.voice_clone_from_b64(sample_base64, sample_mime, text, audio_format, director_instruction)
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


@app.post("/synthesize/stream")
def synthesize_stream(req: SynthesizeRequest):
    """语音合成 — SSE 流式返回 PCM16 chunks"""
    def event_stream():
        try:
            instruction = req.director_instruction
            if req.auto_director and not instruction:
                instruction = director.generate_instruction(req.text)

            voice_info = voice_manager.get_voice(req.voice)
            source = voice_info.get("source", "built_in") if voice_info else None

            if source == "voiceclone":
                b64_data, mime = voice_manager.get_voiceclone_b64(req.voice)
                if not b64_data:
                    raise ValueError(f"voiceclone 音色数据缺失: {req.voice}")
                # voiceclone 暂不支持流式，走一次性合成
                audio = client.voice_clone_from_b64(b64_data, mime, req.text, req.audio_format, instruction)
                pcm = audio[44:] if req.audio_format == "wav" else audio
                chunk_size = 4096
                for i in range(0, len(pcm), chunk_size):
                    yield f"data: {base64.b64encode(pcm[i:i+chunk_size]).decode()}\n\n"
            elif source == "voicedesign":
                desc = voice_info.get("description", "")
                if not desc:
                    raise ValueError(f"voicedesign 音色描述缺失: {req.voice}")
                audio = client.voice_design(desc, req.text, req.audio_format)
                pcm = audio[44:] if req.audio_format == "wav" else audio
                chunk_size = 4096
                for i in range(0, len(pcm), chunk_size):
                    yield f"data: {base64.b64encode(pcm[i:i+chunk_size]).decode()}\n\n"
            else:
                for chunk in client.synthesize_stream(req.text, instruction, req.model, req.voice):
                    yield f"data: {base64.b64encode(chunk).decode()}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"{e}\"}}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.websocket("/ws/synthesize")
async def ws_synthesize(ws: WebSocket):
    """WebSocket 实时流式合成 — 边生成边发送 PCM16 chunks"""
    await ws.accept()
    try:
        req = json.loads(await ws.receive_text())
        text = req.get("text", "")
        instruction = req.get("instruction", "")
        model = req.get("model", "mimo-v2.5-tts")
        voice = req.get("voice", "Chloe")

        if not text.strip():
            await ws.send_text(json.dumps({"type": "error", "message": "请输入合成文本"}))
            await ws.close()
            return

        # 解析 voice → API 参数（同 /synthesize/stream 逻辑）
        voice_info = voice_manager.get_voice(voice)
        source = voice_info.get("source", "built_in") if voice_info else None

        if source == "voiceclone":
            clone_data = voice_manager.get_voiceclone_b64(voice)
            if not clone_data:
                await ws.send_text(json.dumps({"type": "error", "message": f"voiceclone 数据缺失: {voice}"}))
                await ws.close()
                return
            b64_data, mime = clone_data
            voice_api = f"data:{mime};base64,{b64_data}"
            effective_model = "mimo-v2.5-tts-voiceclone"
        elif source == "voicedesign":
            desc = voice_info.get("description", "")
            if not desc:
                await ws.send_text(json.dumps({"type": "error", "message": f"voicedesign 描述缺失: {voice}"}))
                await ws.close()
                return
            voice_api = None
            effective_model = "mimo-v2.5-tts-voicedesign"
            instruction = desc
        else:
            voice_api = voice
            effective_model = model

        # 在线程池中收集所有 PCM chunks（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        all_chunks = []

        def _collect_chunks():
            for chunk in client.synthesize_stream(text, instruction, effective_model, voice_api):
                all_chunks.append(chunk)

        await loop.run_in_executor(None, _collect_chunks)

        # 逐个发送 chunks
        total_bytes = 0
        for chunk in all_chunks:
            await ws.send_bytes(chunk)
            total_bytes += len(chunk)

        duration = total_bytes / (24000 * 2)  # 24kHz, 16-bit mono
        await ws.send_text(json.dumps({"type": "done", "duration": round(duration, 2)}))
        await ws.close()

    except WebSocketDisconnect:
        logger.info("WebSocket 客户端断开")
    except Exception as e:
        logger.error("WebSocket 错误: %s", e)
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            await ws.close()
        except Exception:
            pass


PLAYER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>实时流式合成</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #fafafa; padding: 16px; }
.box { max-width: 800px; margin: 0 auto; }
h3 { font-size: 17px; margin-bottom: 14px; }
h3 span { font-size: 12px; color: #999; font-weight: normal; }
.row { display: flex; gap: 12px; margin-bottom: 12px; align-items: flex-end; }
.col { flex: 1; }
.col label { font-size: 13px; color: #666; margin-bottom: 4px; display: block; }
textarea, select { width: 100%%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
textarea:focus, select:focus { border-color: #f97316; outline: none; }
.btn { padding: 10px 28px; background: #f97316; color: #fff; border: none; border-radius: 6px; font-size: 15px; font-weight: 600; cursor: pointer; }
.btn:hover { background: #ea580c; }
.btn:disabled { background: #ccc; cursor: not-allowed; }
.status { margin-top: 8px; padding: 8px 12px; border-radius: 6px; font-size: 13px; background: #f5f5f5; color: #666; }
.status.playing { background: #fef3c7; color: #92400e; }
.status.done { background: #d1fae5; color: #065f46; }
.status.error { background: #fee2e2; color: #991b1b; }
.wave { display: flex; align-items: center; gap: 3px; height: 24px; margin-top: 6px; }
.wave span { display: inline-block; width: 3px; background: #f97316; border-radius: 2px; animation: bounce 0.6s ease-in-out infinite; }
.wave span:nth-child(2) { animation-delay: 0.1s; }
.wave span:nth-child(3) { animation-delay: 0.2s; }
.wave span:nth-child(4) { animation-delay: 0.3s; }
.wave span:nth-child(5) { animation-delay: 0.4s; }
@keyframes bounce { 0%,100%% { height: 6px; } 50%% { height: 20px; } }
</style>
</head>
<body>
<div class="box">
<h3>实时流式合成 <span>WebSocket + Web Audio API</span></h3>
<div class="row">
  <div class="col" style="flex:2">
    <label>合成文本</label>
    <textarea id="ws-text" rows="3" placeholder="输入要合成的文本..."></textarea>
  </div>
  <div class="col" style="flex:1">
    <label>导演指令</label>
    <textarea id="ws-instruction" rows="3" placeholder="可选：温柔、缓慢..."></textarea>
  </div>
</div>
<div class="row">
  <div class="col">
    <label>模型</label>
    <select id="ws-model">
      <option value="mimo-v2.5-tts">mimo-v2.5-tts</option>
      <option value="mimo-v2.5-tts-voicedesign">mimo-v2.5-tts-voicedesign</option>
      <option value="mimo-v2.5-tts-voiceclone">mimo-v2.5-tts-voiceclone</option>
    </select>
  </div>
  <div class="col">
    <label>音色</label>
    <select id="ws-voice"></select>
  </div>
  <div class="col" style="flex:0 0 auto; align-self:flex-end;">
    <button class="btn" id="ws-btn" onclick="doSynth()">▶ 合成</button>
  </div>
</div>
<div class="status" id="ws-status">就绪</div>
<div class="wave" id="ws-wave" style="display:none;"><span></span><span></span><span></span><span></span><span></span></div>
<audio id="ws-audio" controls style="width:100%%;margin-top:12px;"></audio>
</div>

<script>
var WS_URL = 'ws://' + location.hostname + ':18900/ws/synthesize';
var API_URL = 'http://' + location.hostname + ':18900';
var SR = 24000;
var actx = null, nextT = 0, chunks = [], playing = false, ws = null;

function getAC() {
  if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: SR});
  if (actx.state === 'suspended') actx.resume();
  return actx;
}

function setStatus(t, c) {
  var el = document.getElementById('ws-status');
  el.textContent = t;
  el.className = 'status' + (c ? ' ' + c : '');
}

function playNext() {
  if (!chunks.length) { playing = false; setStatus('播放完成', 'done'); document.getElementById('ws-wave').style.display='none'; return; }
  var f32 = chunks.shift();
  var ctx = getAC();
  var buf = ctx.createBuffer(1, f32.length, SR);
  buf.getChannelData(0).set(f32);
  var s = ctx.createBufferSourceNode();
  s.buffer = buf; s.connect(ctx.destination);
  s.start(nextT); nextT += buf.duration;
  s.onended = playNext;
}

function doSynth() {
  var text = document.getElementById('ws-text').value.trim();
  if (!text) { alert('请输入合成文本'); return; }
  var btn = document.getElementById('ws-btn');
  btn.disabled = true;
  document.getElementById('ws-wave').style.display = 'flex';
  if (actx) { actx.close(); actx = null; }
  chunks = []; playing = false;
  setStatus('正在连接...', '');

  ws = new WebSocket(WS_URL);
  ws.binaryType = 'arraybuffer';
  ws.onopen = function() {
    setStatus('已连接 — 正在合成...', 'playing');
    ws.send(JSON.stringify({
      text: text,
      instruction: document.getElementById('ws-instruction').value.trim(),
      model: document.getElementById('ws-model').value,
      voice: document.getElementById('ws-voice').value,
    }));
  };
  ws.onmessage = function(e) {
    if (typeof e.data === 'string') {
      var m = JSON.parse(e.data);
      if (m.type === 'done') {
        setStatus('合成完成 — ' + m.duration + 's', 'done');
        btn.disabled = false;
        document.getElementById('ws-wave').style.display = 'none';
        ws.close();
        if (!playing && chunks.length) { playing = true; playNext(); }
      } else if (m.type === 'error') {
        setStatus('错误: ' + m.message, 'error');
        btn.disabled = false;
        document.getElementById('ws-wave').style.display = 'none';
        ws.close();
      }
    } else {
      var i16 = new Int16Array(e.data);
      var f32 = new Float32Array(i16.length);
      for (var i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
      chunks.push(f32);
      if (!playing && chunks.length >= 1) { playing = true; playNext(); }
    }
  };
  ws.onerror = function() {
    setStatus('连接失败 — 请确认 server.py 已启动', 'error');
    btn.disabled = false;
    document.getElementById('ws-wave').style.display = 'none';
  };
  ws.onclose = function() { btn.disabled = false; };
}

// 加载音色列表
fetch(API_URL + '/voices')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    var sel = document.getElementById('ws-voice');
    var g1 = document.createElement('optgroup');
    g1.label = '内置音色';
    d.built_in.forEach(function(n) { var o = document.createElement('option'); o.value = n; o.textContent = n; g1.appendChild(o); });
    sel.appendChild(g1);
    if (d.custom.length) {
      var g2 = document.createElement('optgroup');
      g2.label = '自定义音色';
      d.custom.forEach(function(v) { var o = document.createElement('option'); o.value = v.name; o.textContent = v.name + ' (' + v.source + ')'; g2.appendChild(o); });
      sel.appendChild(g2);
    }
    setStatus('就绪 — ' + d.built_in.length + ' 内置, ' + d.custom.length + ' 自定义音色', '');
  })
  .catch(function(e) { setStatus('音色加载失败: ' + e.message, 'error'); });
</script>
</body>
</html>"""


@app.get("/player", response_class=HTMLResponse)
def player_page():
    """实时流式合成播放器页面"""
    return HTMLResponse(content=PLAYER_HTML)


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

    # 启动时打印可用模型和音色，方便复制到第三方工具
    models = ["mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"]
    voices = [v["name"] for v in voice_manager.list_voices()]
    print("\n" + "=" * 50)
    print("  MiMo TTS Server — OpenAI 兼容端点")
    print("=" * 50)
    print(f"  模型: {', '.join(models)}")
    print(f"  音色: {', '.join(voices)}")
    print("=" * 50 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=18900)
