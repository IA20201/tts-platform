"""MiMo V2.5 导演级语音工作站 — Gradio 界面

三 Tab 布局：
1. 单句合成：导演指令 + 合成内容 + AI 自动生成指令
2. 批量生产：文件上传 + 并发控制 + 进度展示
3. 音色实验室：VoiceDesign / VoiceClone / 音色库管理
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import gradio as gr

from config import BUILT_IN_VOICES, Settings
from director.agent import DirectorAgent
from mimo_tts.client import MiMoTTSClient
from pipeline.batch import BatchProcessor
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

TTS_MODELS = ["mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone"]
AUDIO_FORMATS = ["wav", "mp3", "pcm16"]
ALL_VOICES = BUILT_IN_VOICES.get("mimo-v2.5-tts", [])


# ──────────────────────────────────────────────
#  Tab 1: 单句合成
# ──────────────────────────────────────────────

def generate_director_instruction(text: str) -> str:
    """AI 自动生成导演指令"""
    if not text.strip():
        return ""
    try:
        return director.generate_instruction(text)
    except Exception as e:
        return f"[生成失败: {e}]"


def synthesize_single(
    text: str,
    instruction: str,
    model: str,
    voice: str,
    audio_format: str,
) -> str | None:
    """单句合成，返回音频文件路径"""
    if not text.strip():
        gr.Warning("请输入合成文本")
        return None
    try:
        # voicedesign: instruction 作为音色描述
        # voiceclone: voice 为音色名称，需从音色库获取 base64
        if model == "mimo-v2.5-tts-voicedesign":
            audio_bytes = client.voice_design(instruction, text, audio_format)
        elif model == "mimo-v2.5-tts-voiceclone":
            clone_data = voice_manager.get_voiceclone_b64(voice)
            if not clone_data:
                gr.Warning(f"音色 '{voice}' 不是 VoiceClone 类型或不存在")
                return None
            b64_data, mime = clone_data
            audio_bytes = client.voice_clone_from_b64(b64_data, mime, text, audio_format)
        else:
            audio_bytes = client.synthesize(text, instruction, model, voice, audio_format)

        # 保存到临时文件
        suffix = f".{audio_format}" if audio_format != "pcm16" else ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=settings.output_dir)
        tmp.write(audio_bytes)
        tmp.close()
        return tmp.name
    except Exception as e:
        gr.Error(f"合成失败: {e}")
        return None


# ──────────────────────────────────────────────
#  Tab 2: 批量生产
# ──────────────────────────────────────────────

def run_batch(
    files: list,
    use_director: bool,
    concurrency: int,
    voice: str,
    model: str,
) -> str:
    """批量合成（阻塞式，Gradio 会自动处理）"""
    if not files:
        return "请上传文件"

    processor = BatchProcessor(
        client=client,
        max_concurrency=concurrency,
        max_chunk_chars=settings.max_chunk_chars,
        output_dir=settings.output_dir,
    )

    # 收集所有文本项
    import json
    items = []
    for file in files:
        path = Path(file.name)
        if path.suffix == ".txt":
            text = path.read_text(encoding="utf-8")
            items.append({"id": path.stem, "text": text})
        elif path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                items.extend(data)
            else:
                items.append(data)

    if not items:
        return "未找到有效文本"

    # 运行异步批量处理
    director_agent = director if use_director else None
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(
            processor.process_texts(items, use_director, director_agent, voice, model)
        )
    finally:
        loop.close()

    # 汇总结果
    done = sum(1 for r in results if r.get("status") == "done")
    failed = sum(1 for r in results if r.get("status") == "error")
    output_lines = [
        f"批量合成完成: {done} 成功, {failed} 失败",
        f"输出目录: {settings.output_dir}",
    ]
    for r in results:
        status = "✓" if r["status"] == "done" else "✗"
        output_lines.append(f"  {status} {r['id']}: {r.get('output', r.get('error', ''))}")
    return "\n".join(output_lines)


# ──────────────────────────────────────────────
#  Tab 3: 音色实验室
# ──────────────────────────────────────────────

def design_voice_preview(description: str, preview_text: str) -> str | None:
    """VoiceDesign 生成预览"""
    if not description.strip():
        gr.Warning("请输入音色描述")
        return None
    try:
        audio_bytes = client.voice_design(description, preview_text or "你好，这是一个音色预览测试。")
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=settings.output_dir)
        tmp.write(audio_bytes)
        tmp.close()
        return tmp.name
    except Exception as e:
        gr.Error(f"生成失败: {e}")
        return None


def clone_voice_preview(audio_file, preview_text: str) -> str | None:
    """VoiceClone 生成预览"""
    if audio_file is None:
        gr.Warning("请上传音频样本")
        return None
    try:
        audio_bytes = client.voice_clone(audio_file, preview_text or "你好，这是一个音色预览测试。")
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=settings.output_dir)
        tmp.write(audio_bytes)
        tmp.close()
        return tmp.name
    except Exception as e:
        gr.Error(f"克隆失败: {e}")
        return None


def save_voice_to_lab(name: str, source: str, description: str, audio_file) -> str:
    """保存音色到音色库"""
    if not name.strip():
        return "请输入音色名称"
    try:
        if source == "voicedesign":
            voice_manager.add_voice(name, "voicedesign", description=description)
        elif source == "voiceclone" and audio_file:
            from mimo_tts.audio_utils import read_audio_to_b64
            b64_str, mime = read_audio_to_b64(audio_file)
            voice_manager.add_voice(
                name, "voiceclone",
                voice_id=f"data:{mime};base64,{b64_str}",
                sample_path=audio_file,
            )
        else:
            return "请提供必要信息"
        return f"音色 '{name}' 已保存"
    except Exception as e:
        return f"保存失败: {e}"


def list_voices_ui() -> str:
    """列出所有音色"""
    voices = voice_manager.list_voices()
    if not voices:
        return "暂无音色"
    lines = []
    for v in voices:
        source = v.get("source", "unknown")
        name = v.get("name", "")
        desc = v.get("description", "")
        tags = ", ".join(v.get("tags", []))
        lines.append(f"[{source}] {name} — {desc} {f'({tags})' if tags else ''}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
#  构建 Gradio 界面
# ──────────────────────────────────────────────

def build_app() -> gr.Blocks:
    with gr.Blocks(title="MiMo V2.5 语音工作站", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 🎙️ MiMo V2.5 导演级语音工作站")

        with gr.Tab("单句合成"):
            with gr.Row():
                with gr.Column(scale=1):
                    instruction_input = gr.Textbox(
                        label="导演指令（可选，留空则直接合成）",
                        placeholder="如：温柔、缓慢、带一点悲伤...",
                        lines=3,
                    )
                    auto_director_btn = gr.Button("🤖 AI 自动生成指令", variant="secondary")

                with gr.Column(scale=1):
                    text_input = gr.Textbox(
                        label="合成内容",
                        placeholder="输入要合成的文本...",
                        lines=5,
                    )

            with gr.Row():
                model_select = gr.Dropdown(choices=TTS_MODELS, value="mimo-v2.5-tts", label="模型")
                voice_select = gr.Dropdown(choices=ALL_VOICES, value="Chloe", label="音色")
                format_select = gr.Dropdown(choices=AUDIO_FORMATS, value="wav", label="音频格式")

            synthesize_btn = gr.Button("▶ 合成", variant="primary")
            audio_output = gr.Audio(label="合成结果", type="filepath")

            auto_director_btn.click(
                fn=generate_director_instruction,
                inputs=[text_input],
                outputs=[instruction_input],
            )
            synthesize_btn.click(
                fn=synthesize_single,
                inputs=[text_input, instruction_input, model_select, voice_select, format_select],
                outputs=[audio_output],
            )

        with gr.Tab("批量生产"):
            with gr.Row():
                batch_files = gr.File(label="上传 .txt / .json 文件", file_count="multiple", file_types=[".txt", ".json"])
                with gr.Column():
                    batch_director = gr.Checkbox(value=True, label="使用导演模式（AI 自动生成指令）")
                    batch_concurrency = gr.Slider(minimum=1, maximum=20, value=10, step=1, label="并发数")
                    batch_voice = gr.Dropdown(choices=ALL_VOICES, value="Chloe", label="音色")
                    batch_model = gr.Dropdown(choices=TTS_MODELS, value="mimo-v2.5-tts", label="模型")

            batch_btn = gr.Button("▶ 开始批量合成", variant="primary")
            batch_output = gr.Textbox(label="批量结果", lines=15, interactive=False)

            batch_btn.click(
                fn=run_batch,
                inputs=[batch_files, batch_director, batch_concurrency, batch_voice, batch_model],
                outputs=[batch_output],
            )

        with gr.Tab("音色实验室"):
            gr.Markdown("### VoiceDesign — 一句话生成音色")
            with gr.Row():
                design_desc = gr.Textbox(label="音色描述", placeholder="如：年轻女性，温柔甜美，带一点气声")
                design_text = gr.Textbox(label="试听文本", value="你好，这是一个音色预览测试。")
            design_btn = gr.Button("生成预览", variant="secondary")
            design_audio = gr.Audio(label="预览结果", type="filepath")

            gr.Markdown("### VoiceClone — 音频样本复刻")
            with gr.Row():
                clone_file = gr.Audio(label="上传音频样本", type="filepath")
                clone_text = gr.Textbox(label="试听文本", value="你好，这是一个音色预览测试。")
            clone_btn = gr.Button("克隆预览", variant="secondary")
            clone_audio = gr.Audio(label="预览结果", type="filepath")

            gr.Markdown("### 音色库管理")
            with gr.Row():
                save_name = gr.Textbox(label="音色名称")
                save_source = gr.Dropdown(choices=["voicedesign", "voiceclone"], value="voicedesign", label="来源")
                save_desc = gr.Textbox(label="描述（VoiceDesign）")
                save_file = gr.Audio(label="样本（VoiceClone）", type="filepath")
            save_btn = gr.Button("保存到音色库")
            save_result = gr.Textbox(label="保存结果", interactive=False)

            list_btn = gr.Button("刷新音色列表")
            voices_list = gr.Textbox(label="音色列表", lines=10, interactive=False)

            design_btn.click(fn=design_voice_preview, inputs=[design_desc, design_text], outputs=[design_audio])
            clone_btn.click(fn=clone_voice_preview, inputs=[clone_file, clone_text], outputs=[clone_audio])
            save_btn.click(fn=save_voice_to_lab, inputs=[save_name, save_source, save_desc, save_file], outputs=[save_result])
            list_btn.click(fn=list_voices_ui, outputs=[voices_list])

    return app


if __name__ == "__main__":
    os.makedirs(settings.output_dir, exist_ok=True)
    app = build_app()
    app.launch(server_name="0.0.0.0", server_port=7860, share=False)
