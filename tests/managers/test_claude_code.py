"""Tests for ClaudeCodeManager."""

import pytest

from open_agent_compiler.managers import ClaudeCodeManager


class TestClaudeCodeManager:
    @pytest.fixture
    def manager(self) -> ClaudeCodeManager:
        return ClaudeCodeManager()

    async def test_deploy_and_health(self, manager: ClaudeCodeManager):
        assert not await manager.health_check()
        await manager.deploy({"backend": "claude_code", "name": "bot"})
        assert await manager.health_check()

    async def test_invoke_without_deploy_raises(self, manager: ClaudeCodeManager):
        with pytest.raises(RuntimeError, match="No agent deployed"):
            await manager.invoke({"prompt": "hi"})

    async def test_invoke_returns_stub(self, manager: ClaudeCodeManager):
        await manager.deploy({"backend": "claude_code"})
        result = await manager.invoke({"prompt": "hello"})
        assert result["status"] == "stub"
        assert result["payload"] == {"prompt": "hello"}

    async def test_teardown(self, manager: ClaudeCodeManager):
        await manager.deploy({"backend": "claude_code"})
        await manager.teardown()
        assert not await manager.health_check()
