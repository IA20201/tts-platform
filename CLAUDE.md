# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MiMo V2.5 导演级语音生产工作站。基于小米 MiMo TTS API（OpenAI 兼容协议），支持三种 TTS 模型、导演指令控制、批量合成、音色克隆/设计。

## 技术栈

- Python 3.12，包管理器：`uv`
- TTS API：OpenAI SDK 兼容，endpoint `token-plan-cn.xiaomimimo.com/v1`
- UI：Gradio（`app.py`，端口 7860）
- 后端：FastAPI（`server.py`，端口 18900）
- 测试：`uv run pytest tests/ -v`

## 常用命令

```bash
uv sync                          # 安装依赖
uv run app.py                    # 启动 Gradio UI
uv run server.py                 # 启动 API 后端
uv run batch_cli.py ./texts/     # 命令行批量合成
uv run pytest tests/ -v          # 运行测试
```

## 架构要点

- `mimo_tts/client.py`：核心 TTS 客户端，封装 3 个模型（tts / voicedesign / voiceclone）
- `director/agent.py`：LLM 自动生成导演指令，输出含 `(情绪)` 和 `[停顿]` 控制标签
- `pipeline/batch.py`：异步并发批量合成，指数退避重试，PCM16 流式收集后转 WAV
- `voice_lab/manager.py`：本地 JSON 音色库管理
- `config.py`：pydantic-settings，从 `.env` 加载配置

## 关键实现约束

- 批量合成统一走 PCM16 流式路径，最后套 WAV 头（避免 WAV 二进制拼接损坏）
- voiceclone 的 `user` 角色消息必须存在（即使内容为空），否则 API 报错
- voicedesign 的 `user` 角色必须有内容（音色描述）
- 流式返回的 audio 是 dict（`{'id': ..., 'data': ...}`），不是对象

## 环境配置

复制 `.env.example` 为 `.env`，填入 `MIMO_API_KEY`。Token Plan 用户用 `token-plan-cn.xiaomimimo.com/v1`，标准 API 用户用 `api.xiaomimimo.com/v1`。
