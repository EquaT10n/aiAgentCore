from agent.app import main

def test_smoke():
    assert main() == "ok"
