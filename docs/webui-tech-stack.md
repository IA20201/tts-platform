# MiMo TTS WebUI 技术栈文档

基于 MiMo V2.5 项目 Gradio WebUI 实现，适用于其他 TTS 项目参考。

## 核心技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| **UI 框架** | Gradio (`gradio`) | Blocks 模式构建，支持 Tab/Row/Column 布局 |
| **Python 版本** | 3.12 | 使用 `uv` 管理依赖 |
| **异步** | `asyncio` + `asyncio.new_event_loop()` | Windows 兼容处理 |
| **音频处理** | `soundfile` | WAV/MP3 等音频格式读写 |
| **后端 API** | FastAPI | `server.py` 端口 18900 |
| **TTS 客户端** | OpenAI SDK 兼容 | `mimo_tts/client.py` 封装 |

## 项目目录结构

```
tts-platform/
├── app.py              # Gradio WebUI 入口
├── server.py          # FastAPI 后端（REST API）
├── config.py          # pydantic-settings 配置管理
├── mimo_tts/
│   ├── client.py      # TTS 客户端封装
│   └── audio_utils.py # 音频工具
├── director/
│   └── agent.py       # LLM 导演指令生成
├── pipeline/
│   └── batch.py       # 异步批量合成处理器
└── voice_lab/
    └── manager.py     # 本地音色库管理
```

## 布局架构（三 Tab）

```
┌─────────────────────────────────────────────────────┐
│  🎙️ MiMo V2.5 导演级语音工作站                       │
├─────────────────────────────────────────────────────┤
│  [单句合成]  [批量生产]  [音色实验室]                 │
├─────────────────────────────────────────────────────┤
│  Tab 1: 单句合成                                    │
│  ├── Row: 导演指令输入 + 文本输入                   │
│  ├── Row: 模型选择 / 音色选择 / 格式选择              │
│  └── 合成按钮 → AudioOutput                        │
│                                                     │
│  Tab 2: 批量生产                                    │
│  ├── File 上传 (.txt/.json)                         │
│  ├── 并发数 Slider (1-20)                          │
│  └── 结果 Textbox                                   │
│                                                     │
│  Tab 3: 音色实验室                                  │
│  ├── VoiceDesign: 描述 → 预览                        │
│  ├── VoiceClone: 上传音频 → 预览 → 保存              │
│  └── 音色库管理: 增删查                              │
└─────────────────────────────────────────────────────┘
```

## Gradio 关键用法

### 1. 启动配置

```python
app.launch(
    server_name="127.0.0.1",
    server_port=7860,
    share=False,
    theme=gr.themes.Soft(),
    enable_monitoring=False,
    ssr_mode=False,  # 关闭 SSR 使用 Blocks 模式
)
```

### 2. Blocks 层级结构

```python
with gr.Blocks(title="TTS 应用") as app:
    with gr.Tab("单句合成"):
        with gr.Row():
            with gr.Column(scale=1):
                # 左侧组件
            with gr.Column(scale=2):
                # 右侧组件
```

- `gr.Blocks()` → 根容器
- `gr.Tab()` → 选项卡
- `gr.Row()` → 行（横向排列）
- `gr.Column(scale=N)` → 列（可设置权重）

### 3. 组件类型

| 组件 | 用途 |
|------|------|
| `gr.Textbox(lines=N)` | 多行文本输入/输出 |
| `gr.Dropdown(choices=[], value=X)` | 下拉选择 |
| `gr.Slider(min, max, value, step)` | 数值滑块 |
| `gr.File(file_count="multiple")` | 文件上传 |
| `gr.Audio(type="filepath")` | 音频播放 |
| `gr.Checkbox(label="")` | 复选框 |
| `gr.Button(variant="primary/secondary/stop")` | 按钮 |
| `gr.State(value=None)` | 跨事件持久状态 |

### 4. 事件绑定

```python
# 单向绑定：输入 → 输出
synthesize_btn.click(
    fn=synthesize_single,
    inputs=[text_input, instruction_input, model_select, voice_select, format_select],
    outputs=[audio_output],
)

# 批量处理（异步）
batch_btn.click(fn=run_batch, inputs=[...], outputs=[...])
# Gradio 自动处理异步显示
```

### 5. gr.update() 动态更新下拉选项

```python
def save_voice_to_lab(name: str, ...) -> tuple:
    if not name.strip():
        return ("请输入音色名称", gr.update(), gr.update(), gr.update())
    # ... 处理逻辑
    choices = get_voice_choices()
    return ("保存成功", gr.update(choices=choices), gr.update(choices=choices), gr.update(choices=choices))
```

### 6. State 跨事件持久化

```python
clone_audio_state = gr.State(value=None)  # 保存中间状态

def clone_voice_preview(audio_file, preview_text):
    # ... 处理
    return (tmp.name, audio_file)  # 返回两个值

clone_btn.click(
    fn=clone_voice_preview,
    inputs=[clone_file, clone_text],
    outputs=[clone_audio, clone_audio_state],  # 第二个输出写入 State
)
```

## Windows 兼容处理

```python
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

## 代理排除（避免 502）

```python
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,0.0.0.0")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,0.0.0.0")
```

## 复用要点

1. **依赖安装**: `uv add gradio openai httpx pydantic-settings`

2. **异步批量处理**: 使用 `asyncio.new_event_loop()` + `loop.run_until_complete()` 避免 Gradio 事件循环冲突

   ```python
   loop = asyncio.new_event_loop()
   try:
       results = loop.run_until_complete(processor.process_texts(...))
   finally:
       loop.close()
   ```

3. **临时文件**: `tempfile.NamedTemporaryFile(delete=False)` 保存合成结果，Gradio 自动清理

4. **动态选项**: 用函数封装，保证下拉列表实时更新

   ```python
   def get_voice_choices() -> list[str]:
       built_in = BUILT_IN_VOICES.get("mimo-v2.5-tts", [])
       custom = [v["name"] for v in voice_manager.list_voices() if v.get("source") != "built_in"]
       return built_in + custom
   ```

5. **ffmpeg 路径配置**（可选）:

   ```python
   _FFMPEG_DIR = Path.home() / "AppData/Local/Microsoft/WinGet/Packages/.../ffmpeg-8.1-full_build/bin"
   if _FFMPEG_DIR.exists():
       os.environ["PATH"] = str(_FFMPEG_DIR) + ";" + os.environ.get("PATH", "")
   ```

## 快速开始模板

```python
import gradio as gr
import asyncio

with gr.Blocks(title="TTS 应用") as app:
    gr.Markdown("# TTS 应用")

    with gr.Tab("合成"):
        with gr.Row():
            text_input = gr.Textbox(label="文本", lines=5)
        with gr.Row():
            model_select = gr.Dropdown(choices=["model-a", "model-b"], value="model-a", label="模型")
            voice_select = gr.Dropdown(choices=["voice-1", "voice-2"], value="voice-1", label="音色")

        synthesize_btn = gr.Button("合成", variant="primary")
        audio_output = gr.Audio(label="结果", type="filepath")

        synthesize_btn.click(
            fn=synthesize,
            inputs=[text_input, model_select, voice_select],
            outputs=[audio_output],
        )

app.launch(server_name="127.0.0.1", server_port=7860)
```