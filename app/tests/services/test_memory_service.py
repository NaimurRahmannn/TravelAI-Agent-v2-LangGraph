from unittest.mock import Mock

import app.services.memory_service as memory_service


def test_memory_service_recall_returns_empty_list_on_exception(monkeypatch):
    """Recall degrades to an empty list when Mem0 search fails."""

    memory = Mock()
    memory.search.side_effect = RuntimeError("qdrant unavailable")
    monkeypatch.setattr(
        memory_service.Memory,
        "from_config",
        Mock(return_value=memory),
    )

    service = memory_service.MemoryService()

    assert service.recall("vegetarian meals", user_id="user-123") == []


def test_memory_service_remember_swallows_exceptions(monkeypatch):
    """Remember logs Mem0 failures without raising."""

    memory = Mock()
    memory.add.side_effect = RuntimeError("qdrant unavailable")
    monkeypatch.setattr(
        memory_service.Memory,
        "from_config",
        Mock(return_value=memory),
    )

    service = memory_service.MemoryService()

    service.remember(
        [{"role": "user", "content": "I prefer aisle seats."}],
        user_id="user-123",
    )
