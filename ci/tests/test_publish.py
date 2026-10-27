"""Exercise publish ordering with fake Docker/GitHub commands; never contact a registry."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "publish_images.sh"
SHA = "a" * 40
PREFIX = "ghcr.io/druidpwnz/antifraud-"


@pytest.fixture
def publish(tmp_path):
    docker = tmp_path / "docker"
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALL_LOG"
if [[ "$1" == push && "$2" == "${FAIL_IMAGE:-}" ]]; then exit 1; fi
''')
    gh = tmp_path / "gh"
    gh.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$CURRENT_SHA"
''')
    docker.chmod(0o755)
    gh.chmod(0o755)
    log = tmp_path / "calls"

    def run(**overrides):
        env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CALL_LOG": str(log),
               "GITHUB_REPOSITORY": "druidpwnz/antifraud_lab", "IMAGE_TAG": SHA, "CURRENT_SHA": SHA,
               **overrides}
        result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
        return result.returncode, log.read_text().splitlines() if log.exists() else []

    return run


def test_commit_tags_before_main_and_generator_last(publish):
    code, calls = publish()
    assert code == 0
    assert calls[:4] == [f"push {PREFIX}{name}:{SHA}" for name in ("api", "admin", "rules", "generator")]
    assert calls[-1] == f"push {PREFIX}generator:main"
    assert len(calls) == 12  # four SHA pushes, then four tag/push pairs


def test_failed_commit_upload_never_promotes_main(publish):
    code, calls = publish(FAIL_IMAGE=f"{PREFIX}rules:{SHA}")
    assert code != 0
    assert len(calls) == 3
    assert not any(":main" in call for call in calls)


def test_stale_ci_run_never_moves_main_back(publish):
    code, calls = publish(CURRENT_SHA="b" * 40)
    assert code == 0
    assert len(calls) == 4
    assert not any(":main" in call for call in calls)


def test_failed_promotion_does_not_move_release_pointer(publish):
    code, calls = publish(FAIL_IMAGE=f"{PREFIX}admin:main")
    assert code != 0
    assert f"push {PREFIX}generator:main" not in calls


@pytest.mark.parametrize("overrides", [{"IMAGE_TAG": "main"}, {"GITHUB_REPOSITORY": "someone/fork"}])
def test_invalid_publish_input_makes_no_registry_calls(publish, overrides):
    code, calls = publish(**overrides)
    assert code != 0
    assert calls == []
