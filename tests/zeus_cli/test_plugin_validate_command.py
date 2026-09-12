"""The installed CLI exposes admission validation and returns a usable CI result."""

import argparse
import json

import pytest


@pytest.mark.parametrize("declared", [True, False])
def test_validate_command_probes_plugin_and_returns_json(tmp_path, capsys, declared):
    from zeus_cli.plugins_cmd import plugins_command
    from zeus_cli.subcommands.plugins import build_plugins_parser

    plugin = tmp_path / "sample"
    plugin.mkdir()
    manifest = "name: sample\nversion: 1.0.0\ndescription: Test plugin\n"
    if declared:
        manifest += "provides_tools: [sample_tool]\n"
    (plugin / "plugin.yaml").write_text(manifest, encoding="utf-8")
    (plugin / "__init__.py").write_text(
        "def register(ctx):\n"
        "    ctx.register_tool('sample_tool', 'Sample', {}, lambda args: '')\n",
        encoding="utf-8",
    )
    parser = argparse.ArgumentParser()
    build_plugins_parser(parser.add_subparsers(), cmd_plugins=plugins_command)
    args = parser.parse_args(["plugins", "validate", str(plugin), "--json"])
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    result = json.loads(capsys.readouterr().out)
    assert exc.value.code == (0 if declared else 1)
    assert result["ok"] is declared
    if not declared:
        assert any("sample_tool" in check["detail"] for check in result["checks"] if not check["ok"])
