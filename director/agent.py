"""智能导演代理

用 LLM 自动分析文本情感，生成符合 MiMo 规范的导演指令。
支持在输出文本中直接插入 (情绪) 和 [停顿] 控制标签。
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI, OpenAI

logger = logging.getLogger(__name__)

DIRECTOR_PROMPT = """你是一位专业的语音导演。分析以下文本，生成用于语音合成的导演指令。

指令要求：
1. 用自然语言描述整体情绪、语速、语气风格、发声方式
2. 在文本中直接插入 MiMo 支持的行内控制标签：
   - 括号标签控制情绪/状态：(温柔)、(激昂)、(悲伤)、(愤怒)、(低语)、(兴奋)
   - 中括号标签控制节奏：[停顿]、[长停顿]、[深呼吸]
3. 标签可叠加使用，如：(温柔)(气声)

输出示例：
(温柔)孩子，别怕... [停顿] (坚定)有我在呢。
(激昂)同志们，胜利就在前方！[停顿]跟我冲！
(低语)(神秘)你听... [长停顿] 那是什么声音？

输出格式：直接输出插入了控制标签的文本，不要加任何解释或前缀。"""


class DirectorAgent:
    """用 LLM 自动分析文本情感，生成 MiMo 导演指令"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.xiaomimimo.com/v1",
        model: str = "mimo-v2.5-flash",
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def generate_instruction(self, text: str) -> str:
        """分析文本，返回带控制标签的导演指令文本"""
        logger.info("导演代理分析文本: %s...", text[:50])
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DIRECTOR_PROMPT},
                {"role": "user", "content": f"请为以下文本生成导演指令：\n\n{text}"},
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        instruction = completion.choices[0].message.content.strip()
        logger.info("生成指令: %s...", instruction[:80])
        return instruction

    async def generate_instruction_async(self, text: str) -> str:
        """异步版本：分析文本，返回导演指令"""
        completion = await self.async_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DIRECTOR_PROMPT},
                {"role": "user", "content": f"请为以下文本生成导演指令：\n\n{text}"},
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        return completion.choices[0].message.content.strip()

    def generate_simple_instruction(
        self,
        emotion: str = "平静",
        pace: str = "中速",
        style: str = "自然",
    ) -> str:
        """快速生成简单指令（不调用 LLM）"""
        parts = []
        if emotion:
            parts.append(f"({emotion})")
        if pace:
            parts.append(f"[{pace}]")
        if style:
            parts.append(style)
        return "".join(parts)
