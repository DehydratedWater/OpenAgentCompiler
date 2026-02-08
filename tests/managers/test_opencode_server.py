"""Tests for OpenCodeServerManager."""

import pytest

from open_agent_compiler.managers import OpenCodeServerManager


class TestOpenCodeServerManager:
    @pytest.fixture
    def manager(self) -> OpenCodeServerManager:
        return OpenCodeServerManager(base_url="http://localhost:9999")

    async def test_deploy_and_health(self, manager: OpenCodeServerManager):
        assert not await manager.health_check()
        await manager.deploy({"backend": "opencode", "agent": {"name": "bot"}})
        assert await manager.health_check()

    async def test_invoke_without_deploy_raises(self, manager: OpenCodeServerManager):
        with pytest.raises(RuntimeError, match="No agent deployed"):
            await manager.invoke({"prompt": "hi"})

    async def test_invoke_returns_stub(self, manager: OpenCodeServerManager):
        await manager.deploy({"backend": "opencode"})
        result = await manager.invoke({"prompt": "hello"})
        assert result["status"] == "stub"
        assert result["payload"] == {"prompt": "hello"}

    async def test_teardown(self, manager: OpenCodeServerManager):
        await manager.deploy({"backend": "opencode"})
        await manager.teardown()
        assert not await manager.health_check()
