# Custom TTS Reader 浏览器扩展 API 格式

本文档记录 MiMo TTS Studio 后端服务为第三方浏览器扩展（如 Kokoro、Custom TTS Reader）提供的 OpenAI 兼容 TTS API 端点格式。

## 服务地址

```
http://localhost:18900
```

## 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | 获取可用模型列表 |
| GET | `/v1/audio/voices` | 获取可用音色列表 |
| POST | `/v1/audio/speech` | 合成语音 |

---

## 1. GET /v1/models

**说明**：返回后端支持的 TTS 模型列表。

**响应示例**：

```json
{
  "data": [
    {"id": "mimo-v2.5-tts", "object": "model"},
    {"id": "mimo-v2.5-tts-voicedesign", "object": "model"},
    {"id": "mimo-v2.5-tts-voiceclone", "object": "model"}
  ]
}
```

---

## 2. GET /v1/audio/voices

**说明**：返回所有可用音色名称列表。

**响应示例**：

```json
{
  "voices": ["Chloe", "Junqi", "Yunyang", ...]
}
```

---

## 3. POST /v1/audio/speech

**说明**：核心合成端点，兼容 OpenAI TTS API 格式。

### 请求头

```
Content-Type: application/json
```

### 请求体（JSON）

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `input` | string | ✅ | — | 要合成的文本内容 |
| `voice` | string | ❌ | `Chloe` | 音色名称 |
| `model` | string | ❌ | `kokoro` | 模型 ID（暂未使用，统一用 `mimo-v2.5-tts`） |
| `response_format` | string | ❌ | `mp3` | 输出格式：`mp3` 或 `wav` |
| `stream` | boolean | ❌ | `false` | 是否流式返回 |

### 请求示例（非流式）

```json
{
  "input": "你好，欢迎使用 MiMo TTS。",
  "voice": "Chloe",
  "response_format": "mp3",
  "stream": false
}
```

### 响应示例（非流式）

- HTTP 200
- `Content-Type: audio/mpeg`（mp3）或 `audio/wav`（wav）
- Body：二进制音频文件

### 请求示例（流式）

```json
{
  "input": "你好，欢迎使用 MiMo TTS。",
  "voice": "Chloe",
  "response_format": "mp3",
  "stream": true
}
```

### 响应示例（流式）

- HTTP 200
- `Content-Type: audio/l16;rate=24000;channels=1`
- Body：raw PCM16 二进制流（无任何包装，逐块返回音频数据）

### 音色的 `_` 前缀约定

如果音色名称包含 `_`（如自定义音色），合成时会自动取 `_` 后的部分作为 API 参数：

| 传入 voice | 实际使用 |
|------------|----------|
| `Chloe` | `Chloe` |
| `custom_Yunyang` | `Yunyang` |

---

## 浏览器扩展配置建议

以 Custom TTS Reader 或 Kokoro 扩展为例，配置步骤：

1. **API Endpoint**：填写 `http://localhost:18900`
2. **Model**：留空或填 `kokoro`（后端固定使用 `mimo-v2.5-tts`）
3. **Voice**：从 `/v1/audio/voices` 返回的列表中选取
4. **Response Format**：选择 `mp3` 或 `wav`
5. **Streaming**：关闭（mp3/wav 需要完整文件）；如需实时播放可开启（返回 PCM16 流）

> **注意**：流式模式返回的是 raw PCM16（24kHz 16bit 单声道），不是 WAV 文件，需要客户端自行处理音频帧。

---

## 流式行为说明（实测结论）

MiMo API 的"流式"是**伪流式**（Pseudo-streaming）：服务端先完整生成音频，再通过 SSE 分块返回。首块延迟 ≈ 总耗时，块间隔 ≈ 0ms。

### 实测数据

| 类型 | 块数 | 大小 | 耗时 | 首块延迟 | 块间隔 |
|------|------|------|------|----------|--------|
| 内置音色(冰糖)-流式 | 89 | 361KB | 2.46s | 2.46s | 0.0ms |
| 内置音色(冰糖)-非流式 | - | 392KB | 2.92s | - | - |
| VoiceClone(申鹤)-流式 | 111 | 453KB | 4.11s | 4.11s | 0.0ms |
| VoiceClone(申鹤)-非流式 | - | 469KB | 5.05s | - | - |

### 结论

- 流式模式仍可正常工作：首块到达后浏览器即可开始播放
- 流式的优势：内存效率（不缓冲完整音频），浏览器可提前开始播放
- 流式的局限：无法在生成过程中逐步播放（需等待完整生成）
- VoiceClone 和内置音色行为一致，均为伪流式
