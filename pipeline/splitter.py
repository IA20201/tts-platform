"""长文本智能切片器

按句子边界切片，保证不超过 max_chars。
优先按。！？\n 断句，超长句子按 ，；二次切分，仍然超长则强制截断。
"""

from __future__ import annotations

import re


class TextSplitter:
    """智能断句切片器"""

    # 一级断句符（句号、叹号、问号、换行）
    PRIMARY_DELIMITERS = re.compile(r"[。！？\n]")
    # 二级断句符（逗号、分号、顿号）
    SECONDARY_DELIMITERS = re.compile(r"[，；、]")

    def __init__(self, max_chars: int = 500):
        self.max_chars = max_chars

    def split(self, text: str) -> list[str]:
        """按句子边界切片，保证不超过 max_chars"""
        text = text.strip()
        if not text:
            return []

        if len(text) <= self.max_chars:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= self.max_chars:
                chunks.append(remaining)
                break

            # 在 max_chars 范围内找一级断句点
            cut = self._find_cut_point(remaining, self.max_chars, self.PRIMARY_DELIMITERS)
            if cut == -1:
                # 没找到一级断句，尝试二级
                cut = self._find_cut_point(remaining, self.max_chars, self.SECONDARY_DELIMITERS)
            if cut == -1:
                # 都没找到，强制截断
                cut = self.max_chars

            chunk = remaining[:cut].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[cut:].lstrip()

        return chunks

    @staticmethod
    def _find_cut_point(text: str, max_pos: int, pattern: re.Pattern) -> int:
        """在 [0, max_pos] 范围内从后往前找最后一个匹配的断句符位置"""
        search_end = min(max_pos, len(text))
        match = None
        for m in pattern.finditer(text[:search_end]):
            match = m
        if match:
            return match.end()  # 断句符之后切分
        return -1

    def split_preserving_paragraphs(self, text: str) -> list[str]:
        """按段落先拆分，再对每段做细粒度切片"""
        paragraphs = re.split(r"\n\s*\n", text)
        chunks = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            chunks.extend(self.split(para))
        return chunks
