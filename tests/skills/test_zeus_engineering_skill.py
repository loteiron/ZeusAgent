"""The bundled workflow is discoverable and loadable through the runtime tools."""
import json
from pathlib import Path
import shutil


def test_engineering_workflow_is_a_loadable_runtime_command(tmp_path, monkeypatch):
    home = tmp_path / ".zeus"
    source = Path(__file__).resolve().parents[2] / "skills" / "software-development" / "zeus-engineering"
    shutil.copytree(source, home / "skills" / "software-development" / source.name)
    monkeypatch.setenv("ZEUS_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    from agent.skill_commands import scan_skill_commands
    from tools.skills_tool import skill_view
    commands = scan_skill_commands()
    assert "/zeus-engineering" in commands
    loaded = json.loads(skill_view("zeus-engineering"))
    assert loaded["success"]
    assert "zeus verify --capture-baseline --json" in loaded["content"]
    assert "## Verification" in loaded["content"]
