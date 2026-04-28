"""断点续传状态管理

基于 JSON 文件记录已完成的任务，支持中断后恢复。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ResumeManager:
    """基于 JSON 文件的断点续传状态"""

    def __init__(self, state_file: str = ".batch_state.json"):
        self.state_file = Path(state_file)

    def load(self) -> dict:
        """加载状态，不存在则返回空结构"""
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("状态文件损坏，重新开始: %s", e)
        return {"completed": {}, "failed": {}}

    def save(self, state: dict) -> None:
        """保存状态到文件"""
        self.state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def mark_done(self, task_id: str, output_path: str) -> None:
        """标记任务完成"""
        state = self.load()
        state["completed"][task_id] = {
            "output": output_path,
            "status": "done",
        }
        state["failed"].pop(task_id, None)
        self.save(state)

    def mark_failed(self, task_id: str, error: str) -> None:
        """标记任务失败"""
        state = self.load()
        state["failed"][task_id] = {"error": error}
        self.save(state)

    def is_done(self, task_id: str) -> bool:
        """检查任务是否已完成"""
        state = self.load()
        return task_id in state.get("completed", {})

    def get_pending(self, all_tasks: list[str]) -> list[str]:
        """返回尚未完成的任务 ID 列表"""
        state = self.load()
        completed = set(state.get("completed", {}).keys())
        return [t for t in all_tasks if t not in completed]

    def clear(self) -> None:
        """清空状态（重新开始）"""
        if self.state_file.exists():
            self.state_file.unlink()
