"""导演代理单元测试（不调用 API）"""

from director.agent import DirectorAgent


class TestDirectorAgent:
    def test_simple_instruction(self):
        # 不需要 API key 的简单指令生成
        agent = DirectorAgent(api_key="test", base_url="https://test.api/v1")
        instruction = agent.generate_simple_instruction(
            emotion="温柔", pace="慢速", style="亲切"
        )
        assert "(温柔)" in instruction
        assert "[慢速]" in instruction
        assert "亲切" in instruction

    def test_simple_instruction_defaults(self):
        agent = DirectorAgent(api_key="test", base_url="https://test.api/v1")
        instruction = agent.generate_simple_instruction()
        assert "(平静)" in instruction
        assert "[中速]" in instruction
