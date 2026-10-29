"""Exercise real Git checkouts and updater state with a fake Docker command."""

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/update.sh"

DOCKER = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
path = Path(os.environ['FAKE_DOCKER_STATE'])
state = json.loads(path.read_text())
with Path(os.environ['CALL_LOG']).open('a') as stream:
    stream.write(json.dumps(args) + '\n')
version = os.environ.get('IMAGE_TAG', state['target'])

def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)

if args[0] == 'pull':
    if state.get('fail') == 'pointer': fail('registry unreachable')
elif args[:2] == ['image', 'inspect']:
    service, tag = args[2].split('antifraud-')[1].split(':')
    sha = state['target'] if tag == 'main' else tag
    if state.get('fail') == 'bad-image' and service == 'admin': sha = '0' * 40
    print(json.dumps([{
        'Id': f'sha256:{service}-{sha}', 'Os': 'linux', 'Architecture': 'amd64',
        'Config': {'Labels': {'org.opencontainers.image.revision': sha,
                             'org.opencontainers.image.source': 'https://github.com/druidpwnz/antifraud_lab'},
                   'Env': [f'BUILD_VERSION={sha}']}
    }]))
elif args[0] == 'inspect':
    service = args[1].removeprefix('container-')
    running = '0' * 40 if state.get('fail') == 'drift' and service == 'api' else state['running']
    print(json.dumps([{'State': {'Running': True, 'Health': {'Status': 'healthy'}},
                       'Image': f"sha256:{service}-{running}"}]))
elif args[0] == 'compose':
    config = Path(args[args.index('-f') + 1])
    command = args[args.index('-f') + 2:]
    assert config.exists(), config
    if command[0] == 'config' and state.get('fail') == 'config': fail('missing required env')
    if command[0] == 'pull' and state.get('fail') == 'pull': fail('SHA image unavailable')
    if command[0] == 'run' and command[-1] == 'migrate' and state.get('fail') == 'migration':
        fail('migration failed')
    if command[0] == 'up' and 'api' in command:
        state['running'] = version
        if state.get('fail') == 'drift': state['fail'] = ''
        path.write_text(json.dumps(state))
    if command[0] == 'ps': print('container-' + command[-1])
    if command[0] == 'exec' and state.get('fail') == 'health' and version == state['target']:
        fail('wrong build version')
else:
    fail('unexpected Docker command')
'''


@pytest.fixture
def deployment(tmp_path):
    origin = tmp_path / "origin"
    repo = tmp_path / "checkout"
    origin.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args, cwd=origin):
        return subprocess.check_output(["git", *args], cwd=cwd, env=env, text=True).strip()

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Deploy test")
    git("config", "user.email", "deploy@example.invalid")
    (origin / ".gitignore").write_text(".env\n")
    (origin / "docker-compose.yml").write_text("name: antifraud\nservices: {}\n")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "first release")
    first = git("rev-parse", "HEAD")
    (origin / "release.txt").write_text("second release\n")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "second release")
    second = git("rev-parse", "HEAD")
    git("clone", "-q", str(origin), str(repo))
    git("checkout", "-q", "--detach", first, cwd=repo)
    original_env = "SECRET_KEY=fixture-secret\nADMIN_USERS='literal$characters'\n"
    (repo / ".env").write_text(original_env)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(DOCKER.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    docker.chmod(0o755)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    fake = tmp_path / "docker-state.json"
    log = tmp_path / "calls.jsonl"
    fake.write_text(json.dumps({"target": second, "running": first}))
    env.update(ANTIFRAUD_REPO=str(repo), ANTIFRAUD_STATE_DIR=str(state_dir),
               ANTIFRAUD_HEALTH_TIMEOUT="0", FAKE_DOCKER_STATE=str(fake), CALL_LOG=str(log),
               PATH=f"{binary}:{env['PATH']}")

    class Fixture:
        def run(self, *args):
            return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)

        def calls(self):
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

        def record(self, current=first, previous=None):
            (state_dir / "state.json").write_text(json.dumps(
                {"repo": str(repo), "project": "antifraud", "current": current, "previous": previous}
            ))

        def fail(self, stage):
            data = json.loads(fake.read_text())
            data["fail"] = stage
            fake.write_text(json.dumps(data))

        def head(self):
            return git("rev-parse", "HEAD", cwd=repo)

    fixture = Fixture()
    fixture.repo, fixture.state_dir = repo, state_dir
    fixture.first, fixture.second, fixture.original_env = first, second, original_env
    return fixture


def test_success_uses_target_config_and_records_release_after_health(deployment):
    d = deployment
    d.record()
    result = d.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert d.head() == d.second
    state = json.loads((d.state_dir / "state.json").read_text())
    assert (state["current"], state["previous"]) == (d.second, d.first)
    calls = d.calls()
    pull = next(i for i, call in enumerate(calls) if "--policy" in call)
    stop = next(i for i, call in enumerate(calls) if "stop" in call)
    migrate = next(i for i, call in enumerate(calls) if "migrate" in call)
    assert pull < stop < migrate
    assert not any("down" in call or "--build" in call or "--volumes" in call for call in calls)
    assert (d.repo / ".env").read_text() == d.original_env
    assert not (d.state_dir / "pending.json").exists()


@pytest.mark.parametrize("stage", ["pointer", "config", "pull", "bad-image"])
def test_preflight_failure_never_stops_services_or_checks_out_target(deployment, stage):
    d = deployment
    d.fail(stage)
    result = d.run()
    assert result.returncode != 0
    assert d.head() == d.first
    assert not any("stop" in call for call in d.calls())
    assert not (d.state_dir / "state.json").exists()


def test_dirty_checkout_is_rejected_before_registry_access(deployment):
    d = deployment
    (d.repo / "local-notes.txt").write_text("do not discard\n")
    result = d.run()
    assert result.returncode != 0
    assert "local changes" in result.stdout
    assert d.calls() == []
    assert d.head() == d.first


def test_preflight_only_preserves_checkout_services_and_state(deployment):
    d = deployment
    result = d.run("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert d.head() == d.first
    assert not any("stop" in call or "up" in call for call in d.calls())
    assert not (d.state_dir / "state.json").exists()


@pytest.mark.parametrize("stage", ["migration", "health"])
def test_failed_release_does_not_replace_successful_state_and_can_roll_back(deployment, stage):
    d = deployment
    d.record()
    d.fail(stage)
    result = d.run()
    assert result.returncode != 0
    assert ("migration failed" if stage == "migration" else "failed health/version checks") in result.stdout
    assert json.loads((d.state_dir / "state.json").read_text())["current"] == d.first
    assert json.loads((d.state_dir / "pending.json").read_text())["restore"] == d.first
    d.fail("")
    result = d.run("--rollback")
    assert result.returncode == 0, result.stdout + result.stderr
    assert d.head() == d.first
    assert (d.repo / ".env").read_text() == d.original_env


def test_rollback_after_success_restores_previous_commit(deployment):
    d = deployment
    d.record()
    assert d.run().returncode == 0
    result = d.run("--rollback")
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((d.state_dir / "state.json").read_text())
    assert (state["current"], state["previous"]) == (d.first, d.second)
    assert d.head() == d.first


def test_already_healthy_release_does_not_recreate_or_pull_all_images(deployment):
    d = deployment
    d.record()
    assert d.run().returncode == 0
    before = len(d.calls())
    result = d.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Already running" in result.stdout
    assert not any("stop" in call or "--policy" in call for call in d.calls()[before:])


def test_invalid_sha_is_rejected_before_any_registry_access(deployment):
    d = deployment
    assert d.run("main").returncode != 0
    assert d.calls() == []


def test_wrong_running_image_is_repaired_even_when_recorded_sha_matches(deployment):
    d = deployment
    d.record()
    assert d.run().returncode == 0
    before = len(d.calls())
    d.fail("drift")
    result = d.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("stop" in call for call in d.calls()[before:])


def test_state_from_another_project_is_rejected(deployment):
    d = deployment
    d.record()
    path = d.state_dir / "state.json"
    state = json.loads(path.read_text())
    state["project"] = "another-project"
    path.write_text(json.dumps(state))
    result = d.run()
    assert result.returncode != 0
    assert "another Compose project" in result.stdout
    assert d.calls() == []


def test_overlapping_updater_skips_without_contacting_registry(deployment):
    d = deployment
    with (d.state_dir / "update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = d.run()
    assert result.returncode == 0
    assert "Another updater" in result.stdout
    assert d.calls() == []
