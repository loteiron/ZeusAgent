"""Behavioral regression coverage for the wheel/sdist distribution guard."""

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _build_artifact(kind: str, tmp_path, *, nix_build: bool) -> subprocess.CompletedProcess[str]:
    """Invoke the real PEP 517 hook (build_sdist / build_wheel) as a subprocess.

    The wheel and sdist guards live in SEPARATE cmdclass entries in setup.py
    (the bdist_wheel one behind a try/except ImportError), so each hook needs
    its own regression coverage — a passing sdist test proves nothing about
    the wheel path.
    """
    env = os.environ.copy()
    # nix develop exports this too, so it must not grant permission to build
    # a distributable artifact.
    env["NIX_BUILD_TOP"] = "/build/devshell"
    if nix_build:
        env["ZEUS_NIX_BUILD"] = "1"
    else:
        env.pop("ZEUS_NIX_BUILD", None)
    # PEP 517 may stage a complete sdist beside setup.py even when build/ and
    # egg-info are redirected. Keep the whole build away from parallel source
    # scanners, including transient files and interrupted builds.
    source = tmp_path / "source"
    shutil.copytree(PROJECT_ROOT, source, ignore=shutil.ignore_patterns(
        ".git", ".venv", "venv", "node_modules", "verification", "__pycache__",
        ".pytest_cache", ".ruff_cache", "build", "dist", "*.egg-info",
    ))
    # Build outputs belong to the same isolated temporary directory.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    extra_cfg = tmp_path / "dist-extra.cfg"
    extra_cfg.write_text(
        f"[build]\nbuild_base = {scratch / 'build'}\n\n[egg_info]\negg_base = {scratch}\n",
        encoding="utf-8",
    )
    env["DIST_EXTRA_CONFIG"] = str(extra_cfg)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from setuptools.build_meta import build_{kind}; build_{kind}(r'{out}')".format(
                kind=kind, out=tmp_path
            ),
        ],
        cwd=source,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("kind", ["sdist", "wheel"])
def test_artifact_build_rejects_nix_development_shell_environment(kind, tmp_path):
    result = _build_artifact(kind, tmp_path, nix_build=False)

    assert result.returncode != 0
    assert "Building wheels or sdists for zeus-agent is not supported" in result.stderr


@pytest.mark.parametrize(
    ("kind", "artifact_glob"),
    [("sdist", "zeus_agent-*.tar.gz"), ("wheel", "zeus_agent-*.whl")],
)
def test_artifact_build_allows_explicit_nix_package_build_marker(kind, artifact_glob, tmp_path):
    # The parallel runner may create its timing cache while this build runs.
    # The regression is a staged source DIRECTORY leaking beside setup.py;
    # unrelated runner files must not make an isolated build look unsafe.
    root_directories = {path.name for path in PROJECT_ROOT.iterdir() if path.is_dir()}
    result = _build_artifact(kind, tmp_path, nix_build=True)

    assert result.returncode == 0, result.stderr
    assert {path.name for path in PROJECT_ROOT.iterdir() if path.is_dir()} == root_directories, (
        "Artifact builds must not leave staging directories in the shared source tree"
    )
    artifacts = list(tmp_path.glob(artifact_glob))
    assert artifacts

    expected = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for pattern in ("plugin.yaml", "plugin.yml")
        for path in (PROJECT_ROOT / "plugins").rglob(pattern)
    }
    assert expected, "expected bundled plugin manifests under plugins/"

    if kind == "wheel":
        with zipfile.ZipFile(artifacts[0]) as wheel:
            shipped = set(wheel.namelist())
    else:
        with tarfile.open(artifacts[0]) as sdist:
            shipped = {
                name.split("/", 1)[1]
                for name in sdist.getnames()
                if "/" in name
            }

    missing = sorted(expected - shipped)
    assert not missing, f"{kind} omits bundled plugin manifests: {missing}"
