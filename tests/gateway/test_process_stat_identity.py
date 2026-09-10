"""Process names are data, never fields of the PID-reuse fingerprint."""
from pathlib import Path

import pytest

from gateway import status


@pytest.mark.parametrize("name", ["python", "zeus worker", "zeus ) worker", "worker\nZ label"])
@pytest.mark.parametrize("state", ["S", "Z"])
def test_stat_identity_and_liveness_ignore_whitespace_in_process_names(tmp_path, monkeypatch, name, state):
    start_ticks = 987654321
    pid = 4321
    proc_stat = tmp_path / "stat"
    # Linux stat: parenthesized comm is field 2, state is field 3, starttime is field 22.
    fields = [state, *map(str, range(4, 22)), str(start_ticks), "23", "24"]
    proc_stat.write_text(f"{pid} ({name}) " + " ".join(fields), encoding="utf-8")
    original_path = Path
    monkeypatch.setattr(status, "Path", lambda value: proc_stat if str(value) == f"/proc/{pid}/stat" else original_path(value))

    assert status.get_process_start_time(pid) == start_ticks
    assert status._posix_is_zombie(pid) is (state == "Z")
