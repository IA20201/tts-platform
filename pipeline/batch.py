"""异步并发批量语音合成处理器

- asyncio + Semaphore 并发控制
- 指数退避 + jitter 重试（429/5xx）
- 统一走 PCM16 流式路径收集后转 WAV
- 支持断点续传
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path

from director.agent import DirectorAgent
from mimo_tts.client import MiMoTTSClient
from mimo_tts.models import TTSModel
from pipeline.splitter import TextSplitter

from .resume import ResumeManager

logger = logging.getLogger(__name__)


class BatchProcessor:
    """异步并发批量语音合成"""

    def __init__(
        self,
        client: MiMoTTSClient,
        max_concurrency: int = 10,
        max_chunk_chars: int = 500,
        retry_max: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 60.0,
        output_dir: str = "output",
    ):
        self.client = client
        self.max_concurrency = max_concurrency
        self.splitter = TextSplitter(max_chars=max_chunk_chars)
        self.retry_max = retry_max
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.resume = ResumeManager(self.output_dir / ".batch_state.json")

    async def process_texts(
        self,
        items: list[dict],
        use_director: bool = True,
        director_agent: DirectorAgent | None = None,
        voice: str = "mimo_default",
        model: str = "mimo-v2.5-tts",
    ) -> list[dict]:
        """批量合成。

        items: [{"id": ..., "text": ..., "instruction": ..., "output": ...}]
        """
        sem = asyncio.Semaphore(self.max_concurrency)
        tasks = []
        for item in items:
            task_id = item.get("id", str(hash(item["text"])))
            if self.resume.is_done(task_id):
                logger.info("跳过已完成: %s", task_id)
                continue
            tasks.append(
                self._process_one(item, sem, use_director, director_agent, voice, model)
            )

        if not tasks:
            logger.info("所有任务已完成")
            return []

        logger.info("开始批量合成: %d 个任务, 并发=%d", len(tasks), self.max_concurrency)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, result in enumerate(results):
            item = items[i]
            task_id = item.get("id", str(hash(item["text"])))
            if isinstance(result, Exception):
                logger.error("任务失败: %s - %s", task_id, result)
                self.resume.mark_failed(task_id, str(result))
                processed.append({"id": task_id, "status": "error", "error": str(result)})
            else:
                processed.append({"id": task_id, "status": "done", **result})
        return processed

    async def _process_one(
        self,
        item: dict,
        sem: asyncio.Semaphore,
        use_director: bool,
        director_agent: DirectorAgent | None,
        voice: str,
        model: str,
    ) -> dict:
        """单条处理：切片 → 逐片合成 → 合并 → 保存"""
        async with sem:
            task_id = item.get("id", str(hash(item["text"])))
            text = item["text"]
            instruction = item.get("instruction", "")

            # 导演模式：自动生成指令
            if use_director and director_agent and not instruction:
                instruction = await director_agent.generate_instruction_async(text)

            # 切片
            chunks = self.splitter.split(text)
            logger.info("任务 %s: %d 个切片", task_id, len(chunks))

            # 逐片合成（PCM16 流式收集后转 WAV）
            all_pcm_chunks = []
            for i, chunk in enumerate(chunks):
                wav_data = await self._with_retry(
                    lambda c=chunk: self.client.collect_stream_to_wav_async(
                        c, instruction, model, voice
                    )
                )
                all_pcm_chunks.append(wav_data)
                logger.debug("任务 %s: 切片 %d/%d 完成", task_id, i + 1, len(chunks))

            # 合并所有切片的音频
            if len(all_pcm_chunks) == 1:
                final_audio = all_pcm_chunks[0]
            else:
                # 多个 WAV 拼接：提取 PCM 数据拼接后再套 WAV 头
                from mimo_tts.audio_utils import pcm16_to_wav

                pcm_parts = []
                for wav_data in all_pcm_chunks:
                    # 跳过 44 字节 WAV 头，提取 PCM 数据
                    pcm_parts.append(wav_data[44:])
                final_audio = pcm16_to_wav(b"".join(pcm_parts))

            # 保存
            output_path = self.output_dir / f"{task_id}.wav"
            output_path.write_bytes(final_audio)
            self.resume.mark_done(task_id, str(output_path))
            logger.info("任务完成: %s → %s", task_id, output_path)

            return {"output": str(output_path), "chunks": len(chunks)}

    async def _with_retry(self, coro_factory, max_retries: int | None = None) -> any:
        """指数退避 + jitter 重试

        delay = min(base * 2^attempt + random(0, 1), max_delay)
        仅对 429/5xx 重试，其他错误直接抛出。
        """
        retries = max_retries if max_retries is not None else self.retry_max
        last_error = None

        for attempt in range(retries + 1):
            try:
                return await coro_factory()
            except Exception as e:
                last_error = e
                error_str = str(e)

                # 判断是否可重试（429 或 5xx）
                is_retryable = "429" in error_str or "500" in error_str or "502" in error_str or "503" in error_str
                if not is_retryable or attempt >= retries:
                    raise

                # 指数退避 + jitter
                delay = min(
                    self.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                    self.retry_max_delay,
                )
                logger.warning(
                    "请求失败 (attempt %d/%d), %.1fs 后重试: %s",
                    attempt + 1, retries, delay, error_str[:100],
                )
                await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]

    async def process_file(
        self,
        filepath: str,
        use_director: bool = True,
        director_agent: DirectorAgent | None = None,
        **kwargs,
    ) -> dict:
        """处理单个 .txt 或 .json 文件"""
        path = Path(filepath)
        if path.suffix == ".txt":
            text = path.read_text(encoding="utf-8")
            items = [{"id": path.stem, "text": text}]
        elif path.suffix == ".json":
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                items = data
            else:
                items = [data]
        else:
            raise ValueError(f"不支持的文件格式: {path.suffix}")

        results = await self.process_texts(items, use_director, director_agent, **kwargs)
        return {"file": filepath, "results": results}

    async def process_directory(
        self,
        dirpath: str,
        use_director: bool = True,
        director_agent: DirectorAgent | None = None,
        **kwargs,
    ) -> list[dict]:
        """遍历目录下所有 .txt 文件并批量合成"""
        dir_path = Path(dirpath)
        txt_files = sorted(dir_path.glob("*.txt"))
        if not txt_files:
            logger.warning("目录中没有 .txt 文件: %s", dirpath)
            return []

        items = []
        for f in txt_files:
            text = f.read_text(encoding="utf-8")
            items.append({"id": f.stem, "text": text})

        logger.info("目录 %s: 发现 %d 个文件", dirpath, len(items))
        return await self.process_texts(items, use_director, director_agent, **kwargs)
