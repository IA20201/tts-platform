"""音色资产管理器

本地 JSON 音色库，管理自定义音色（VoiceDesign / VoiceClone）和内置音色。
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class VoiceAssetManager:
    """本地 JSON 音色库管理"""

    def __init__(self, db_path: str = "voice_lab/voices.json"):
        self.db_path = Path(db_path)
        self.samples_dir = self.db_path.parent / "samples"
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    def _ensure_db(self) -> None:
        """确保数据库文件存在"""
        if not self.db_path.exists():
            self._save({"voices": {}, "built_in": [
                "mimo_default", "冰糖", "茉莉", "苏打", "白桦",
                "Mia", "Chloe", "Milo", "Dean",
            ]})

    def _load(self) -> dict:
        return json.loads(self.db_path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.db_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_voice(
        self,
        name: str,
        source: str,
        voice_id: str = "",
        description: str = "",
        tags: list[str] | None = None,
        sample_path: str = "",
    ) -> dict:
        """添加自定义音色

        Args:
            name: 音色名称（唯一标识）
            source: 来源类型 ("voicedesign" | "voiceclone")
            voice_id: voiceclone 的 Base64 数据，或 voicedesign 留空
            description: 音色描述（voicedesign）
            tags: 标签列表
            sample_path: voiceclone 的原始音频文件路径
        """
        data = self._load()
        entry = {
            "source": source,
            "tags": tags or [],
            "created_at": datetime.now().isoformat(),
        }
        if source == "voiceclone":
            entry["voice_id"] = voice_id
            if sample_path:
                # 复制样本到 voice_lab/samples/
                dest = self.samples_dir / f"{name}{Path(sample_path).suffix}"
                shutil.copy2(sample_path, dest)
                entry["sample_path"] = str(dest)
        elif source == "voicedesign":
            entry["description"] = description

        data["voices"][name] = entry
        self._save(data)
        logger.info("音色已添加: %s (%s)", name, source)
        return entry

    def get_voice(self, name: str) -> dict | None:
        """获取音色信息"""
        data = self._load()
        # 先查自定义
        if name in data.get("voices", {}):
            return data["voices"][name]
        # 再查内置
        if name in data.get("built_in", []):
            return {"source": "built_in", "name": name}
        return None

    def list_voices(self, source_filter: str | None = None) -> list[dict]:
        """列出所有音色"""
        data = self._load()
        voices = []
        # 内置音色
        for name in data.get("built_in", []):
            if source_filter is None or source_filter == "built_in":
                voices.append({"name": name, "source": "built_in"})
        # 自定义音色
        for name, info in data.get("voices", {}).items():
            if source_filter is None or info.get("source") == source_filter:
                voices.append({"name": name, **info})
        return voices

    def delete_voice(self, name: str) -> bool:
        """删除自定义音色"""
        data = self._load()
        if name not in data.get("voices", {}):
            logger.warning("音色不存在: %s", name)
            return False

        entry = data["voices"].pop(name)
        # 删除样本文件
        sample_path = entry.get("sample_path")
        if sample_path and Path(sample_path).exists():
            Path(sample_path).unlink()

        self._save(data)
        logger.info("音色已删除: %s", name)
        return True

    def get_voiceclone_b64(self, name: str) -> tuple[str, str] | None:
        """获取 voiceclone 的 (base64_data, mime_type)，用于 API 调用"""
        voice = self.get_voice(name)
        if not voice or voice.get("source") != "voiceclone":
            return None
        voice_id = voice.get("voice_id", "")
        # 从 "data:audio/mpeg;base64,xxx" 格式中提取
        if voice_id.startswith("data:"):
            parts = voice_id.split(",", 1)
            mime = parts[0].replace("data:", "").replace(";base64", "")
            return parts[1], mime
        return voice_id, "audio/mpeg"

    def get_built_in_voices(self) -> list[str]:
        """返回内置音色列表"""
        data = self._load()
        return data.get("built_in", [])
