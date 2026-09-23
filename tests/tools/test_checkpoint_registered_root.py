"""Explicit checkpoint roots also own the write ledger, even without a marker."""
from tools.checkpoint_manager import CheckpointManager


def test_explicit_checkpoint_under_another_project_preserves_user_edits(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.checkpoint_manager.CHECKPOINT_BASE", tmp_path / "checkpoints")
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "pyproject.toml").write_text("[project]\nname='parent'\n")
    work = parent / "scratch"
    work.mkdir()
    agent_file, user_file = work / "agent.txt", work / "user.txt"
    agent_file.write_text("original")
    user_file.write_text("original")
    mgr = CheckpointManager(enabled=True)
    assert mgr.ensure_checkpoint(str(work))
    checkpoint = mgr.list_checkpoints(str(work))[0]["hash"]
    # A fresh manager must discover the persisted root, too.
    mgr = CheckpointManager(enabled=True)
    agent_file.write_text("agent change")
    mgr.record_agent_write(str(agent_file))
    user_file.write_text("user change")
    result = mgr.restore(str(work), checkpoint, safe=True)
    assert result["success"]
    assert user_file.read_text() == "user change"
    assert agent_file.read_text() == "original"
    assert result["skipped_user_edits"] == ["user.txt"]
