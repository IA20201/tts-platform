# MiMo V2.5 导演级语音工作站

基于小米 MiMo TTS API 的语音生产平台，支持三种 TTS 模型、导演指令控制、批量合成、音色克隆/设计。

## 快速开始

```bash
# 安装依赖
uv sync

# 复制配置文件，填入 MIMO_API_KEY
cp .env.example .env

# 启动 Gradio UI（端口 7860）
uv run app.py

# 启动 API 后端（端口 18900）
uv run server.py
```

## 功能

- **单句合成**：输入文本 + 导演指令，实时生成语音
- **批量生产**：上传 txt/json 文件，并发合成
- **音色实验室**：VoiceDesign（一句话生成音色）、VoiceClone（音频样本复刻）
- **AI 导演**：LLM 自动生成导演指令（情绪、停顿、语速控制）

## API 端点

### 原生端点（端口 18900）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/synthesize` | 单句合成，返回 base64 音频 |
| POST | `/synthesize/stream` | SSE 流式合成 |
| POST | `/voice-design` | 音色设计 |
| POST | `/voice-clone` | 音色克隆 |
| POST | `/batch` | 批量合成 |
| GET | `/voices` | 列出所有音色 |

### OpenAI TTS 兼容端点

供 Kokoro TTS Reader、Custom TTS Reader 等第三方工具使用：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | 返回可用模型列表 |
| GET | `/v1/audio/voices` | 返回可用音色列表 |
| POST | `/v1/audio/speech` | 合成端点（支持流式/非流式） |

**`/v1/audio/speech` 请求示例：**

```json
{
  "input": "你好世界",
  "voice": "Chloe",
  "response_format": "mp3",
  "stream": false
}
```

- `stream=false`（默认）：返回完整 MP3/WAV 文件
- `stream=true`：返回 raw PCM16 流（`audio/l16;rate=24000;channels=1`）

**配合浏览器扩展使用：**

1. 启动 `uv run server.py`
2. 在 Kokoro / Custom TTS Reader 扩展中设置 API URL 为 `http://127.0.0.1:18900/v1`
3. 音色名手动输入（如 `Chloe`、`冰糖`、`Mia`）

## 技术栈

- Python 3.12，包管理器：`uv`
- TTS API：OpenAI SDK 兼容，endpoint `token-plan-cn.xiaomimimo.com/v1`
- UI：Gradio（`app.py`）
- 后端：FastAPI（`server.py`）

## 项目结构

```
├── app.py              # Gradio UI（端口 7860）
├── server.py           # FastAPI 后端（端口 18900）
├── config.py           # 配置管理
├── mimo_tts/
│   └── client.py       # MiMo TTS 客户端
├── director/
│   └── agent.py        # AI 导演指令生成
├── pipeline/
│   └── batch.py        # 批量合成引擎
├── voice_lab/
│   └── manager.py      # 音色库管理
└── .env.example        # 环境变量模板
```

## 环境配置

复制 `.env.example` 为 `.env`，填入 `MIMO_API_KEY`。

- Token Plan 用户：`token-plan-cn.xiaomimimo.com/v1`
- 标准 API 用户：`api.xiaomimimo.com/v1`
