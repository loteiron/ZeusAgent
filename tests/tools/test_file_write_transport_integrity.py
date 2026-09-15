"""A failed content transfer must never replace the last complete file."""
import json
import pytest

from tools import file_tools
from tools.environments.local import LocalEnvironment
from tools.file_operations import ShellFileOperations
from tools.registry import registry


@pytest.mark.parametrize("fault", ["truncated", "empty", "corrupted"])
@pytest.mark.parametrize("existing", [True, False])
def test_interrupted_stdin_keeps_original_file(tmp_path, monkeypatch, fault, existing):
    tmp_path = tmp_path / "workspace"
    tmp_path.mkdir()
    target = tmp_path / "source file.txt"
    original = b"last complete version\n"
    if existing:
        target.write_bytes(original)
    env = LocalEnvironment(cwd=str(tmp_path))
    ops = ShellFileOperations(env, cwd=str(tmp_path))
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda task_id: ops)
    registry.dispatch("read_file", {"path": str(target)}, task_id="transport-fault")
    execute = env.execute

    def interrupted(command, **kwargs):
        data = kwargs.get("stdin_data")
        if data is not None:
            kwargs["stdin_data"] = {
                "truncated": data[:len(data) // 2],
                "empty": "",
                "corrupted": "X" + data[1:],
            }[fault]
        return execute(command, **kwargs)

    monkeypatch.setattr(env, "execute", interrupted)
    content = "complete source line\n" * 10000 + "END_OF_FILE\n"
    result = json.loads(registry.dispatch(
        "write_file", {"path": str(target), "content": content}, task_id="transport-fault"))
    assert result.get("error"), "An incomplete transfer must report failure"
    if existing:
        assert target.read_bytes() == original, "A failed transfer replaced the previous complete file"
    else:
        assert not target.exists(), "A failed transfer published an incomplete new file"
    assert sorted(p.name for p in tmp_path.iterdir()) == ([target.name] if existing else [])


def test_large_unicode_file_is_written_completely_through_registry(tmp_path, monkeypatch):
    target = tmp_path / "large source.txt"
    ops = ShellFileOperations(LocalEnvironment(cwd=str(tmp_path)), cwd=str(tmp_path))
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda task_id: ops)
    content = "Türkçe kaynak: şğıİ 🚀 漢字\n" * 100000 + "END_OF_FILE\n"
    result = json.loads(registry.dispatch(
        "write_file", {"path": str(target), "content": content}, task_id="large-transfer"))
    assert not result.get("error"), result
    assert target.read_bytes() == content.encode("utf-8")
