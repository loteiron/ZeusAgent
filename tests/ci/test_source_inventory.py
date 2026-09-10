"""Actual Git behavior must keep product sources while ignoring private state."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_git_add_keeps_runtime_examples_exports_and_site_data_but_not_private_state(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    public = {
        "apps/desktop/src/plugins/hello-runtime/plugin.runtime.js",
        "optional-skills/creative/concept-diagrams/examples/preview.svg",
        "skills/creative/p5js/references/export-pipeline.md",
        "skills/creative/p5js/scripts/export-frames.js",
        "website/src/data/userStories.json",
    }
    private = {".env", "verification/chat.log", "MagicMock/tmp.txt", "node_modules/pkg/index.js", "local.bundle"}
    for name in public | private:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=tmp_path).decode().split("\0"))
    assert public <= tracked
    assert not (private & tracked)
