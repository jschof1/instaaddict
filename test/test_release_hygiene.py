"""Release hygiene checks for v1.4.3 (Homelab B-77): a clean install must carry every runtime import,
version metadata must agree, and the fleet auto-tune path must use the real dogfood module."""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DEPS = ["google-generativeai", "python-dotenv", "pillow", "matplotlib"]


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _names(lines):
    return {re.split(r"[<>=~!\[ ]", line.strip().strip('",'), maxsplit=1)[0].lower() for line in lines if line.strip()}


def test_requirements_declare_runtime_imports():
    names = _names(l for l in _read("requirements.txt").splitlines() if not l.startswith("#"))
    for dep in RUNTIME_DEPS:
        assert dep in names, f"{dep} missing from requirements.txt"


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib needs Python 3.11+")
def test_pyproject_dependencies_match_requirements():
    import tomllib

    project = tomllib.loads(_read("pyproject.toml"))["project"]
    deps = _names(project["dependencies"])
    for dep in RUNTIME_DEPS:
        assert dep in deps, f"{dep} missing from pyproject dependencies"
    assert "analytics" not in project.get("optional-dependencies", {}), "stale matplotlib==3.4.2 extra is back"
    assert {"pytest", "pytest-mock"} <= set(project["optional-dependencies"]["dev"])


def test_version_metadata_agrees():
    import InstaAddict

    version = InstaAddict.__version__
    assert not os.path.exists(os.path.join(ROOT, "InstaAddict", "version.py")), "stray version.py is back"
    first_release = re.search(r"^## v(\d+\.\d+\.\d+)", _read("CHANGELOG.md"), re.MULTILINE).group(1)
    assert first_release == version
    assert f"badge/release-v{version}-" in _read("README.md")


def test_fleet_apply_tuning_uses_dogfood_module(monkeypatch):
    import InstaAddict.core.dogfood as dogfood
    from InstaAddict.core.multi_telemetry import MultiAccountTelemetryAggregator

    calls = []

    class FakeOptimizer:
        def __init__(self, username, *a, **k):
            calls.append(("init", username))

        def analyze(self):
            calls.append(("analyze",))
            return {}

        def apply_tuning(self, *a, **k):
            calls.append(("apply_tuning",))
            return {"applied": []}

    class FakeOrchestrator:
        def restart_account(self, username, delay_seconds=0):
            calls.append(("restart", username))
            return True

    monkeypatch.setattr(dogfood, "DogfoodOptimizer", FakeOptimizer)
    agg = MultiAccountTelemetryAggregator(["alice"])
    assert agg.apply_tuning_and_restart("@alice", FakeOrchestrator()) is True
    assert calls == [("init", "alice"), ("analyze",), ("apply_tuning",), ("restart", "alice")]
