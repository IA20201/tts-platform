"""命令行批量语音合成脚本

用法:
    uv run batch_cli.py ./texts/ --director --concurrency 10 --output ./output/
    uv run batch_cli.py ./texts/story.txt --voice Chloe --model mimo-v2.5-tts
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config import Settings
from director.agent import DirectorAgent
from mimo_tts.client import MiMoTTSClient
from pipeline.batch import BatchProcessor


def main():
    parser = argparse.ArgumentParser(description="MiMo TTS 批量语音合成")
    parser.add_argument("input", help="输入文件或目录路径")
    parser.add_argument("--director", action="store_true", help="使用导演模式（AI 自动生成指令）")
    parser.add_argument("--voice", default="Chloe", help="音色名称（默认: Chloe）")
    parser.add_argument("--model", default="mimo-v2.5-tts", help="TTS 模型")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数（默认: 10）")
    parser.add_argument("--output", default="output", help="输出目录（默认: output）")
    parser.add_argument("--max-chunk", type=int, default=500, help="长文本切片阈值（默认: 500）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = parser.parse_args()

    # 日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 初始化
    settings = Settings()  # type: ignore[call-arg]
    tts_client = MiMoTTSClient(
        api_key=settings.mimo_api_key,
        base_url=settings.mimo_base_url,
    )
    director_agent = None
    if args.director:
        director_agent = DirectorAgent(
            api_key=settings.llm_api_key or settings.mimo_api_key,
            base_url=settings.llm_base_url or settings.mimo_base_url,
            model=settings.llm_model,
        )

    processor = BatchProcessor(
        client=tts_client,
        max_concurrency=args.concurrency,
        max_chunk_chars=args.max_chunk,
        output_dir=args.output,
    )

    # 执行
    input_path = Path(args.input)
    loop = asyncio.new_event_loop()

    try:
        if input_path.is_dir():
            results = loop.run_until_complete(
                processor.process_directory(
                    str(input_path),
                    use_director=args.director,
                    director_agent=director_agent,
                    voice=args.voice,
                    model=args.model,
                )
            )
        elif input_path.is_file():
            result = loop.run_until_complete(
                processor.process_file(
                    str(input_path),
                    use_director=args.director,
                    director_agent=director_agent,
                    voice=args.voice,
                    model=args.model,
                )
            )
            results = result.get("results", [])
        else:
            print(f"错误: 路径不存在 - {input_path}", file=sys.stderr)
            sys.exit(1)
    finally:
        loop.close()

    # 输出结果
    done = sum(1 for r in results if r.get("status") == "done")
    failed = sum(1 for r in results if r.get("status") == "error")
    print(f"\n{'='*50}")
    print(f"批量合成完成: {done} 成功, {failed} 失败")
    print(f"输出目录: {args.output}")
    print(f"{'='*50}")

    for r in results:
        status = "✓" if r["status"] == "done" else "✗"
        print(f"  {status} {r['id']}: {r.get('output', r.get('error', ''))}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
