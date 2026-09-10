"""Detected verification respects project runners and avoids formatting edits."""
import json

from agent.coding_context import detect_project_facts
from agent.verify.recipes import detect_recipe
from zeus_cli.verify_cmd import _merge_project_facts_commands


def test_detected_checks_do_not_run_formatters(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {
        "test": "node --test", "fmt": "prettier --write .", "format": "biome format --write .",
    }}), encoding="utf-8")
    (tmp_path / "Makefile").write_text("lint:\n\techo checked\nformat:\n\techo changed\n", encoding="utf-8")
    recipe = detect_recipe(tmp_path)
    _merge_project_facts_commands(tmp_path, recipe)
    assert "npm run test" in recipe.test
    assert "make lint" in recipe.test
    assert "npm run fmt" not in recipe.test
    assert "npm run format" not in recipe.test
    assert "make format" not in recipe.test


def test_canonical_python_runner_is_not_bypassed_or_duplicated(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="1"\n[tool.pytest.ini_options]\n', encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run_tests.sh").write_text("#!/bin/sh\npython -m pytest\n", encoding="utf-8")
    recipe = detect_recipe(tmp_path)
    _merge_project_facts_commands(tmp_path, recipe)
    assert recipe.test == ["scripts/run_tests.sh"]
    assert detect_project_facts(tmp_path).verify_commands == ["scripts/run_tests.sh"]


def test_setup_py_project_installs_itself_not_missing_requirements(tmp_path):
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup(name='sample')\n", encoding="utf-8")
    assert detect_recipe(tmp_path).bootstrap == ["pip install -e ."]


def test_explicit_formatting_recipe_still_runs_as_authored(tmp_path):
    from agent.verify import load_or_detect, save_manifest
    from agent.verify.recipes import Recipe
    recipe = Recipe(name="Explicit project check", test=["npm run format"])
    save_manifest(tmp_path, recipe)
    loaded, source = load_or_detect(tmp_path)
    assert source == "manifest"
    assert loaded.test == recipe.test
