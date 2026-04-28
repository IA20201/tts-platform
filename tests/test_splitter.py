"""文本切片器单元测试"""

import pytest

from pipeline.splitter import TextSplitter


class TestTextSplitter:
    def test_short_text_no_split(self):
        splitter = TextSplitter(max_chars=100)
        result = splitter.split("你好，世界。")
        assert result == ["你好，世界。"]

    def test_empty_text(self):
        splitter = TextSplitter(max_chars=100)
        assert splitter.split("") == []
        assert splitter.split("   ") == []

    def test_split_at_primary_delimiter(self):
        splitter = TextSplitter(max_chars=10)
        text = "这是第一句话。这是第二句话。这是第三句话。"
        result = splitter.split(text)
        assert len(result) == 3
        for chunk in result:
            assert len(chunk) <= 10

    def test_split_at_secondary_delimiter(self):
        splitter = TextSplitter(max_chars=10)
        text = "短句一，短句二，短句三。"
        result = splitter.split(text)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 10

    def test_force_cut_long_sentence(self):
        splitter = TextSplitter(max_chars=5)
        text = "这是一段没有任何标点符号的超长文本"
        result = splitter.split(text)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 5

    def test_split_preserving_paragraphs(self):
        splitter = TextSplitter(max_chars=50)
        text = "第一段内容。\n\n第二段内容。第三段内容。"
        result = splitter.split_preserving_paragraphs(text)
        assert len(result) >= 2
