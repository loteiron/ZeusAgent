"""Experience learning follows real check outcomes, never the agent's success claim."""
import subprocess
import sys
import os
import json

import pytest

from agent.verification_evidence import begin_verify_run, record_verify_run


def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "private"))
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (root / "app.py").write_text("answer = 1\n", encoding="utf-8")
    (root / "check.py").write_text(
        "import os\nfrom app import answer\nassert answer == int(os.environ.get('CHECK_EXPECTED', '2')), 'wrong answer'\nprint('check passed')\n",
        encoding="utf-8",
    )
    return root


def check(root, session="first", command="zeus verify --skip-start", expected="2"):
    before = begin_verify_run(root=root, session_id=session, command=command)
    result = subprocess.run([sys.executable, "-B", "check.py"], cwd=root, capture_output=True, text=True, encoding="utf-8",
                            env={**os.environ, "CHECK_EXPECTED": expected})
    return record_verify_run(root=root, session_id=session, command=command,
                             ok=result.returncode == 0, output=result.stdout + result.stderr,
                             workspace_before=before)


def test_real_failed_check_and_repair_become_a_durable_experience(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    failed = check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    passed = check(root)

    # A newly opened store represents another conversation/process.
    report = ExperienceStore().recall(root=root, query="wrong answer")
    assert len(report["experiences"]) == 1
    lesson = report["experiences"][0]
    assert lesson["state"] == "recovered"
    assert lesson["freshness"] == "current"
    assert lesson["cause"] == ""  # A green exit does not prove a causal explanation.
    detail = ExperienceStore().show(lesson["id"], root=root)
    assert [item["event_id"] for item in detail["observations"]] == [failed["id"], passed["id"]]
    assert detail["observations"][0]["fingerprint"] != detail["observations"][1]["fingerprint"]
    assert "wrong answer" in detail["symptom"]


def test_background_lesson_is_reused_in_another_turn_without_a_command(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent.experience_review import prepare_review, apply_review, turn_recall
    from tools.terminal_tool import record_session_cwd, clear_session_cwd

    root = project(tmp_path, monkeypatch)
    check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    check(root)
    agent = SimpleNamespace(session_id="first", skip_memory=False, _delegate_depth=0)
    record_session_cwd("first", str(root))
    record_session_cwd("next", str(root))
    try:
        bundle = prepare_review(agent)
        case = bundle["cases"][0]
        response = json.dumps({"experience_lessons": [{"id": case["id"],
            "cause": "The default answer did not match the check.",
            "resolution": "Set the default answer to 2 and rerun check.py.",
            "conditions": "For this project's default answer contract."}]})
        assert apply_review(bundle, {"final_response": response, "completed": True}) == 1
        next_agent = SimpleNamespace(session_id="next", skip_memory=False, _delegate_depth=0)
        recalled = turn_recall(next_agent, "Fix the wrong answer in app.py", "next")
        assert "Set the default answer to 2" in recalled
        assert "hypothesis" in recalled
        assert "experience_lessons" not in turn_recall(next_agent, "selam", "next")
    finally:
        clear_session_cwd("first")
        clear_session_cwd("next")


def test_late_or_foreign_review_cannot_overrule_new_evidence(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent.experience_review import prepare_review, apply_review, turn_recall
    from agent.experience_store import ExperienceStore
    from tools.terminal_tool import record_session_cwd, clear_session_cwd

    root = project(tmp_path, monkeypatch)
    check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    check(root)
    agent = SimpleNamespace(session_id="first", skip_memory=False, _delegate_depth=0)
    record_session_cwd("first", str(root))
    try:
        bundle = prepare_review(agent)
        case = bundle["cases"][0]
        response = {"completed": True, "final_response": json.dumps({"experience_lessons": [
            {"id": case["id"], "cause": "old assumption", "resolution": "old repair"}]})}
        monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "other-profile"))
        assert apply_review(bundle, response) == 0
        assert turn_recall(agent, "wrong answer", "first") == ""
        monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "private"))
        check(root, session="counterexample", expected="3")
        assert apply_review(bundle, response) == 0
        detail = ExperienceStore().show(case["id"], root=root)
        assert detail["state"] == "contradicted" and not detail["resolution"]
        for bad in ({**response, "completed": False}, {**response, "interrupted": True},
                    {**response, "final_response": '{"experience_lessons": ['}):
            assert apply_review(prepare_review(agent), bad) == 0
        nested = root / "nested"
        nested.mkdir()
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        record_session_cwd("first", str(nested))
        assert turn_recall(agent, "wrong answer", "first") == ""
    finally:
        clear_session_cwd("first")


def test_legacy_database_migrates_and_late_review_preserves_manual_conditions(tmp_path, monkeypatch):
    import sqlite3
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    result = check(root)
    store = ExperienceStore()
    store.explain(result["experience"]["id"], root=root, cause="Default mismatch", resolution="Use answer 2")
    # Reproduce the actual prior on-disk schema, with existing rows retained.
    with sqlite3.connect(store.path) as connection:
        connection.execute("ALTER TABLE experiences DROP COLUMN reviewed_revision")
    case = ExperienceStore().review_candidates(root)[0]
    store.explain(case["id"], root=root, cause=case["cause"], resolution=case["resolution"],
                  conditions="Only the original configuration was tested")
    assert not store.save_review(case, {"cause": "Assumed cause", "resolution": "Assumed repair"})
    assert store.show(case["id"], root=root)["conditions"] == "Only the original configuration was tested"


def test_corrupt_experience_database_does_not_abort_background_memory_review(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent.experience_review import prepare_review
    from tools.terminal_tool import record_session_cwd, clear_session_cwd

    root = project(tmp_path, monkeypatch)
    profile = tmp_path / "private"
    profile.mkdir(exist_ok=True)
    (profile / "experience.db").write_bytes(b"Not a SQLite database")
    record_session_cwd("corrupt-review", str(root))
    try:
        assert prepare_review(SimpleNamespace(session_id="corrupt-review")) == {}
    finally:
        clear_session_cwd("corrupt-review")


def test_same_source_failure_and_success_are_unstable_not_a_learned_repair(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    check(root)
    check(root, expected="1")  # Only external runtime configuration changed.
    lesson = ExperienceStore().recall(root=root)["experiences"][0]
    assert lesson["state"] == "unstable"
    assert lesson["recovery_fingerprint"] == ""


def test_changed_code_expires_advice_and_counterexample_overrules_a_previous_pass(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    check(root)
    (root / "unrelated.py").write_text("changed = True\n", encoding="utf-8")
    assert ExperienceStore().recall(root=root)["experiences"][0]["freshness"] == "stale"
    (root / "unrelated.py").unlink()
    check(root, session="later", expected="3")
    lesson = ExperienceStore().recall(root=root)["experiences"][0]
    assert lesson["state"] == "contradicted"
    assert lesson["freshness"] == "current"
    assert lesson["usable_as_repair"] is False


def test_explanations_remain_hypotheses_are_private_and_can_be_forgotten(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    check(root)
    lesson = ExperienceStore().recall(root=root)["experiences"][0]
    case_id = lesson["id"]
    store = ExperienceStore()
    store.explain(case_id, root=root, cause="Default value was wrong; API_KEY=private-test-value",
                  resolution="Change the default to 2.", avoid="Do not mask the failing check.",
                  conditions="Only the default answer path.")
    detail = ExperienceStore().show(case_id, root=root)
    assert detail["causal_explanation"] == "hypothesis"
    assert detail["state"] == "unresolved"
    assert "Change the default" in detail["resolution"]
    assert "private-test-value" not in json.dumps(detail)
    other = tmp_path / "other"
    other.mkdir()
    assert store.recall(root=other)["experiences"] == []
    with pytest.raises(ValueError, match="not found"):
        store.show(case_id, root=other)
    monkeypatch.setenv("ZEUS_HOME", str(tmp_path / "another-profile"))
    assert ExperienceStore().recall(root=root)["experiences"] == []
    # The original store stays bound to its original profile.
    assert store.forget(case_id, root=root) is True
    assert store.recall(root=root)["experiences"] == []


def test_overlapping_and_different_checks_cannot_certify_a_repair(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    # This passing run began before the observed failure completed.
    overlapping = begin_verify_run(root=root, session_id="first", command="zeus verify --skip-start")
    check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    check(root, command="zeus verify --phase build")
    check(root, session="unrelated-session")
    assert ExperienceStore().recall(root=root)["experiences"][0]["state"] == "unresolved"
    record_verify_run(root=root, session_id="first", command="zeus verify --skip-start", ok=True,
                      workspace_before=overlapping, workspace_after=overlapping)
    assert ExperienceStore().recall(root=root)["experiences"][0]["state"] == "unverified"


def test_replays_do_not_inflate_learning_and_retention_removes_old_evidence(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    (tmp_path / "private").mkdir(exist_ok=True)
    (tmp_path / "private" / "config.yaml").write_text("experience:\n  max_cases: 2\n", encoding="utf-8")
    failed = check(root)
    case_id = failed["experience"]["id"]
    stores = [ExperienceStore() for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda store: store.observe(failed), stores))
    assert all(result["id"] == case_id for result in results)
    assert len(ExperienceStore().show(case_id, root=root)["observations"]) == 1
    check(root, command="zeus verify --phase test")
    check(root, command="zeus verify --phase build")
    remaining = ExperienceStore().recall(root=root)["experiences"]
    assert len(remaining) == 2
    assert case_id not in {item["id"] for item in remaining}
    with pytest.raises(ValueError, match="not found"):
        ExperienceStore().show(case_id, root=root)


def test_next_conversation_recalls_a_relevant_repair_before_editing_without_repeating_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent.experience_runtime import read_experience_hint
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    result = check(root)
    ExperienceStore().explain(result["experience"]["id"], root=root, cause="Wrong default answer",
                             resolution="Set answer to 2", avoid="Changing the checker instead of the default")
    agent = SimpleNamespace(skip_memory=False, system_prompt="unchanged prefix")
    args = {"path": str(root / "app.py")}
    hint = read_experience_hint(agent, "read_file", args, "new-session")
    assert "Set answer to 2" in hint and "historical_data" in hint
    assert agent.system_prompt == "unchanged prefix"
    assert read_experience_hint(agent, "read_file", args, "new-session") == ""
    assert read_experience_hint(agent, "terminal", {"command": "echo hello"}, "new-session") == ""
    assert read_experience_hint(SimpleNamespace(skip_memory=True), "read_file", args, "cron") == ""


def test_new_session_can_revalidate_without_inventing_another_recovery(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    check(root)
    (root / "app.py").write_text("answer = 2\n", encoding="utf-8")
    first = check(root)
    lesson = ExperienceStore().recall(root=root)["experiences"][0]
    assert lesson["recovery_count"] == 1
    assert first["experience"]["new_recovery"] is True
    (root / "other.py").write_text("value = 3\n", encoding="utf-8")
    assert ExperienceStore().recall(root=root)["experiences"][0]["freshness"] == "stale"
    repeated = check(root, session="next")
    lesson = ExperienceStore().recall(root=root)["experiences"][0]
    assert lesson["freshness"] == "current" and lesson["recovery_count"] == 1
    assert repeated["experience"]["new_recovery"] is False
    assert "annotation_hint" not in repeated["experience"]


def test_progress_noise_does_not_fragment_the_same_failure_into_different_lessons(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    ids = []
    for number, duration in ((1, "0.2"), (2, "9.1")):
        event = record_verify_run(root=root, session_id="s", ok=False,
                                  output=f"run {number}, elapsed {duration}s\nAssertionError: wrong answer\n1 failed in {duration}s",
                                  workspace_before=begin_verify_run(root=root, session_id="s"))
        ids.append(event["experience"]["id"])
    assert ids[0] == ids[1]
    other = record_verify_run(root=root, session_id="s", ok=False, output="ConnectionError: refused",
                               workspace_before=begin_verify_run(root=root, session_id="s"))
    assert other["experience"]["id"] != ids[0]
    assert len(ExperienceStore().show(ids[0], root=root)["observations"]) == 2


def test_experience_reaches_new_tool_message_and_preserves_committed_history(tmp_path, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from agent.tool_executor import _commit_tool_result, _ToolCallRef, BudgetConfig

    root = project(tmp_path, monkeypatch)
    check(root)
    agent = SimpleNamespace(
        skip_memory=False, verbose_logging=False, tool_progress_callback=None,
        _append_guardrail_observation=lambda name, args, result, **kwargs: result,
        _record_file_mutation_result=lambda *args: None,
        _touch_activity=lambda text: None,
        _subdirectory_hints=SimpleNamespace(check_tool_call=lambda *args: None),
        _tool_result_content_for_active_model=lambda name, result: result,
        _flush_messages_to_session_db=lambda messages: True,
    )
    messages = [{"role": "system", "content": "Cached system prefix"},
                {"role": "user", "content": "Fix the default answer"},
                {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "read-1", "type": "function", "function": {
                        "name": "read_file", "arguments": json.dumps({"path": str(root / "app.py")})}}]}]
    original = deepcopy(messages)
    result = _commit_tool_result(
        agent, messages, _ToolCallRef("read_file", {"path": str(root / "app.py")}, "next", "read-1", []),
        (root / "app.py").read_text(encoding="utf-8"), budget=BudgetConfig(),
        tool_duration=0.01, is_error=False, blocked=False, effect_disposition=None, observed=True,
    )
    assert result is not None
    assert messages[:-1] == original
    assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "read-1"
    assert "answer = 1" in messages[-1]["content"]
    assert "project_experience" in messages[-1]["content"]
    assert "historical_data" in messages[-1]["content"]


def test_capture_and_recall_controls_and_corrupt_database_do_not_break_checks(tmp_path, monkeypatch, caplog):
    from types import SimpleNamespace
    from agent.experience_runtime import read_experience_hint

    root = project(tmp_path, monkeypatch)
    profile = tmp_path / "private"
    profile.mkdir(exist_ok=True)
    config = profile / "config.yaml"
    config.write_text("experience:\n  enabled: false\n", encoding="utf-8")
    disabled = check(root)
    assert disabled["status"] == "failed" and "experience" not in disabled
    assert not (profile / "experience.db").exists()
    config.write_text("experience:\n  recall_enabled: false\n", encoding="utf-8")
    assert "experience" in check(root)
    args = {"path": str(root / "app.py")}
    assert read_experience_hint(SimpleNamespace(), "read_file", args, "next") == ""
    config.write_text("experience:\n  enabled: true\n", encoding="utf-8")
    (profile / "experience.db").write_bytes(b"Not a SQLite database")
    failed = check(root)
    assert failed["status"] == "failed" and failed["id"] > disabled["id"]
    assert "experience" not in failed
    assert read_experience_hint(SimpleNamespace(), "read_file", args, "next") == ""
    assert "verification receipt retained" in caplog.text
    assert "original file result retained" in caplog.text


def test_file_recall_cannot_exceed_the_conversation_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agent.experience_runtime import read_experience_hint

    root = project(tmp_path, monkeypatch)
    for phase in ("test", "build", "start"):
        check(root, command=f"zeus verify --phase {phase}")
    seen = {(f"profile-{index}", str(index)) for index in range(31)}
    agent = SimpleNamespace(_experience_recalled=seen)
    hint = read_experience_hint(agent, "read_file", {"path": str(root / "app.py")}, "next")
    assert len(json.loads(hint)["project_experience"]) == 1
    assert len(agent._experience_recalled) == 32


def test_long_check_output_keeps_the_final_diagnostic_and_groups_the_failure(tmp_path, monkeypatch):
    from agent.experience_store import ExperienceStore

    root = project(tmp_path, monkeypatch)
    cases = []
    for run in (1, 2):
        event = record_verify_run(
            root=root, session_id="s", ok=False,
            output=(f"run {run}: completed setup stage\n" * 120) + "ConnectionError: worker connection refused\n",
            workspace_before=begin_verify_run(root=root, session_id="s"),
        )
        cases.append(event["experience"]["id"])
    assert cases[0] == cases[1]
    detail = ExperienceStore().show(cases[0], root=root)
    assert "ConnectionError: worker connection refused" in detail["symptom"]
    assert len(detail["symptom"]) <= 1600
