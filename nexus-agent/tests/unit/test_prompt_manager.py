"""Unit tests for PromptManager — registration, versioning, A/B testing."""

from __future__ import annotations

import pytest

from nexus.agent.prompts.manager import PromptManager


@pytest.fixture
def manager() -> PromptManager:
    return PromptManager(
        ab_test_weights={
            "test_prompt": {"1.0": 0.5, "2.0": 0.5},
        }
    )


class TestPromptManager:
    """PromptManager — central prompt registry."""

    def test_register_and_get(self, manager: PromptManager) -> None:
        manager.register("greeting", "Hello {name}!", version="1.0")
        tmpl = manager.get("greeting")
        assert tmpl.name == "greeting"
        assert tmpl.version == "1.0"
        assert tmpl.template == "Hello {name}!"

    def test_render(self, manager: PromptManager) -> None:
        manager.register("greeting", "Hello {name}!", version="1.0")
        result = manager.render("greeting", name="World")
        assert result == "Hello World!"

    def test_version_selection(self, manager: PromptManager) -> None:
        manager.register("test", "v1", version="1.0")
        manager.register("test", "v2", version="2.0")
        tmpl = manager.get("test", version="1.0")
        assert tmpl.template == "v1"

    def test_highest_version_default(self, manager: PromptManager) -> None:
        manager.register("test", "v1", version="1.0")
        manager.register("test", "v2", version="2.0")
        manager.register("test", "v3", version="3.0")
        tmpl = manager.get("test")
        assert tmpl.version == "3.0"

    def test_unknown_name_raises(self, manager: PromptManager) -> None:
        with pytest.raises(KeyError, match="Unknown prompt"):
            manager.get("nonexistent")

    def test_unknown_version_raises(self, manager: PromptManager) -> None:
        manager.register("test", "v1", version="1.0")
        with pytest.raises(KeyError, match="Unknown version"):
            manager.get("test", version="99.0")

    def test_list_versions(self, manager: PromptManager) -> None:
        manager.register("test", "v1", version="1.0")
        manager.register("test", "v2", version="2.0")
        manager.register("test", "v3", version="1.5")
        versions = manager.list_versions("test")
        assert versions == ["1.0", "1.5", "2.0"]

    def test_metadata_on_template(self, manager: PromptManager) -> None:
        manager.register("test", "v1", version="1.0", metadata={"author": "alice"})
        tmpl = manager.get("test", version="1.0")
        assert tmpl.metadata["author"] == "alice"

    def test_ab_testing_returns_valid_version(self, manager: PromptManager) -> None:
        manager.register("test_prompt", "a", version="1.0")
        manager.register("test_prompt", "b", version="2.0")
        seen = set()
        for _ in range(100):
            tmpl = manager.get("test_prompt")
            seen.add(tmpl.version)
        # both versions should appear at least once
        assert "1.0" in seen
        assert "2.0" in seen

    def test_render_with_kwargs(self, manager: PromptManager) -> None:
        manager.register("farewell", "Goodbye, {name}!", version="1.0")
        result = manager.render("farewell", name="Alice")
        assert result == "Goodbye, Alice!"

    def test_missing_key_in_render_raises(self, manager: PromptManager) -> None:
        manager.register("test", "Hello {name}!", version="1.0")
        with pytest.raises(KeyError):
            manager.render("test", unknown_arg="x")

    def test_multiple_registrations_same_version(self, manager: PromptManager) -> None:
        manager.register("dup", "first", version="1.0")
        manager.register("dup", "second", version="1.0")  # overwrites
        tmpl = manager.get("dup", version="1.0")
        assert tmpl.template == "second"


class TestPromptManagerSingleton:
    """Verify the default singleton is properly initialised."""

    def test_singleton_exists(self) -> None:
        from nexus.agent.prompts import prompt_manager
        assert isinstance(prompt_manager, PromptManager)

    def test_pre_registered_prompts(self) -> None:
        from nexus.agent.prompts import prompt_manager
        names = prompt_manager.list_versions("understand_intent")
        assert "1.0" in names
        assert "2.0" in names
        names = prompt_manager.list_versions("plan")
        assert "2.0" in names
        names = prompt_manager.list_versions("finalize")
        assert "1.0" in names
