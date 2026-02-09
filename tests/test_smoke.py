from __future__ import annotations

from agent import app


def test_agent_main() -> None:
    assert app.main() == "ok"
