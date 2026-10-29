"""Pull a tested release, check out its commit, and replace services without removing data."""

import argparse
import fcntl
import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

PREFIX = "ghcr.io/druidpwnz/antifraud-"
SOURCE = "https://github.com/druidpwnz/antifraud_lab"
SERVICES = ("api", "admin", "rules", "generator")
RUNNING = (*SERVICES, "postgres", "prometheus", "grafana")
SHA = re.compile(r"[0-9a-f]{40}")


def log(message):
    print(message, flush=True)


class Updater:
    def __init__(self, repo, state_dir, project):
        self.repo = repo.resolve()
        self.state_dir = state_dir
        self.project = project
        self.env = os.environ.copy()
        for name in ("COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES"):
            self.env.pop(name, None)
        self.env["GIT_TERMINAL_PROMPT"] = "0"
        self.env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes")
        self.version = None
        self.images = {}

    def run(self, *command, timeout=120, check=True, input=None):
        result = subprocess.run(command, cwd=self.repo, env=self.env, text=True, input=input,
                                capture_output=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(f"{' '.join(command)} failed:\n{result.stderr.strip() or result.stdout.strip()}")
        return result

    def git(self, *arguments):
        return self.run("git", *arguments).stdout.strip()

    def compose(self, config, *arguments, **kwargs):
        return self.run("docker", "compose", "--project-name", self.project,
                        "--project-directory", str(self.repo), "--env-file", str(self.repo / ".env"),
                        "-f", str(config), *arguments, **kwargs)

    def read_state(self, name):
        path = self.state_dir / name
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        if data.get("repo") != str(self.repo):
            raise ValueError(f"{path} belongs to another checkout; use a separate ANTIFRAUD_STATE_DIR")
        if data.get("project") != self.project:
            raise ValueError(f"{path} belongs to another Compose project; use a separate ANTIFRAUD_STATE_DIR")
        return data

    def write_state(self, name, **values):
        path = self.state_dir / name
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"repo": str(self.repo), "project": self.project, **values}) + "\n")
        temporary.replace(path)

    def inspect_image(self, tag):
        return json.loads(self.run("docker", "image", "inspect", tag).stdout)[0]

    def verify_images(self):
        for service in SERVICES:
            image = self.inspect_image(f"{PREFIX}{service}:{self.version}")
            labels = image["Config"].get("Labels") or {}
            if ((image["Os"], image["Architecture"]) != ("linux", "amd64")
                    or labels.get("org.opencontainers.image.revision") != self.version
                    or labels.get("org.opencontainers.image.source") != SOURCE
                    or f"BUILD_VERSION={self.version}" not in (image["Config"].get("Env") or [])):
                raise ValueError(f"{service} image has the wrong platform, source or build version")
            self.images[service] = image["Id"]

    def healthy(self, config):
        for service in RUNNING:
            container = self.compose(config, "ps", "-q", service).stdout.strip()
            if not container:
                return False
            details = json.loads(self.run("docker", "inspect", container).stdout)[0]
            state = details["State"]
            if not state["Running"] or state.get("Health", {}).get("Status", "healthy") != "healthy":
                return False
            if service in self.images and details["Image"] != self.images[service]:
                return False
        probe = Path(__file__).with_name("healthcheck.py").read_text()
        result = self.compose(config, "exec", "-T", "api", "python", "-", self.version,
                              input=probe, check=False, timeout=30)
        if result.returncode:
            log(result.stderr.strip() or result.stdout.strip())
            return False
        return True

    def execute(self, args):
        if not (self.repo / ".env").is_file():
            raise ValueError("the deployment checkout needs its existing .env file")
        if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.repo:
            raise ValueError("ANTIFRAUD_REPO must be the repository root")
        if self.git("status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("checkout has local changes; commit or move them before deployment")
        state = self.read_state("state.json")
        pending = self.read_state("pending.json")
        requested = args.version
        if args.rollback:
            requested = pending.get("restore") if pending else state.get("previous")
            if not requested:
                raise ValueError("no recorded rollback release; pass a known published SHA explicitly")
        if requested is not None and not SHA.fullmatch(requested):
            raise ValueError("release must be a full 40-character lowercase commit SHA")

        if requested is None:
            log("Checking the published generator:main release pointer")
            self.run("docker", "pull", f"{PREFIX}generator:main", timeout=300)
            labels = self.inspect_image(f"{PREFIX}generator:main")["Config"].get("Labels") or {}
            requested = labels.get("org.opencontainers.image.revision", "")
            if not SHA.fullmatch(requested) or labels.get("org.opencontainers.image.source") != SOURCE:
                raise ValueError("published release pointer has an invalid source or revision")
        self.version = requested
        self.env.update(IMAGE_TAG=requested, BUILD_VERSION=requested)
        log(f"Target release: {requested}")
        self.git("fetch", "--no-tags", "origin", "main")
        self.git("cat-file", "-e", f"{requested}^{{commit}}")
        self.git("merge-base", "--is-ancestor", requested, "FETCH_HEAD")

        config = self.repo / "docker-compose.yml"
        if not args.check and state.get("current") == requested and self.git("rev-parse", "HEAD") == requested:
            try:
                self.verify_images()
                if self.healthy(config):
                    (self.state_dir / "pending.json").unlink(missing_ok=True)
                    log(f"Already running {requested}; all services healthy")
                    return
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                log("Recorded release needs repair; validating images before replacement")

        # Validate the target config before checkout or stopping any service. Resolve
        # bind mounts against the real checkout, which will receive this commit.
        with tempfile.TemporaryDirectory(prefix="antifraud-release-") as directory:
            archive = Path(directory) / "release.tar"
            self.git("archive", "--format=tar", f"--output={archive}", requested)
            with tarfile.open(archive) as source:
                source.extractall(directory, filter="data")
            config = Path(directory) / "docker-compose.yml"
            self.compose(config, "config", "--quiet")
            self.compose(config, "pull", "--policy", "always", timeout=600)
            self.verify_images()
        if args.check:
            log("PASS preflight: commit, Compose config and all images verified; no services changed")
            return

        config = self.repo / "docker-compose.yml"
        restore = state.get("current")
        self.write_state("pending.json", target=requested, restore=restore)
        log("Stopping the generator, rules and web services before migrations")
        # Use the existing config to stop existing writers; IMAGE_TAG does not
        # select containers here, the explicit project and service names do.
        self.compose(config, "stop", "-t", "30", "generator", "rules", "api", "admin")
        self.git("checkout", "--detach", requested)
        self.compose(config, "up", "-d", "--no-build", "--pull", "never", "--wait",
                     "--wait-timeout", "180", "postgres", timeout=240)
        log("Applying migrations and checking the seed marker")
        self.compose(config, "run", "--rm", "--no-deps", "migrate", timeout=600)
        self.compose(config, "run", "--rm", "--no-deps", "seed", timeout=600)
        # Recreate monitoring too: bind-mounted config may have changed at checkout.
        self.compose(config, "up", "-d", "--no-deps", "--force-recreate", "--no-build",
                     "--pull", "never", "--wait", "--wait-timeout", "180",
                     *SERVICES, "prometheus", "grafana", timeout=240)
        deadline = time.monotonic() + float(os.environ.get("ANTIFRAUD_HEALTH_TIMEOUT", "90"))
        while not self.healthy(config):
            if time.monotonic() >= deadline:
                raise RuntimeError("release failed health/version checks; last successful release was not changed")
            time.sleep(3)
        previous = restore if restore != requested else state.get("previous")
        self.write_state("state.json", current=requested, previous=previous)
        (self.state_dir / "pending.json").unlink(missing_ok=True)
        log(f"DEPLOYED {requested}; previous successful release: {previous or 'none recorded'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="published SHA; omit to follow generator:main")
    parser.add_argument("--check", action="store_true", help="fetch, pull and validate without changing services")
    parser.add_argument("--rollback", action="store_true", help="restore the recorded last/previous successful release")
    args = parser.parse_args()
    if args.rollback and args.version:
        parser.error("use --rollback or an explicit SHA, not both")
    repo = os.environ.get("ANTIFRAUD_REPO")
    if not repo:
        parser.error("set ANTIFRAUD_REPO to the absolute deployment checkout path")
    os.umask(0o077)
    state_dir = Path(os.environ.get("ANTIFRAUD_STATE_DIR", str(Path.home() / ".local/state/antifraud")))
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Another updater is running; skipping this attempt")
            return
        try:
            Updater(Path(repo), state_dir, os.environ.get("ANTIFRAUD_PROJECT", "antifraud")).execute(args)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            log(f"UPDATE FAILED: {exc}")
            log("Inspect journalctl --user -u antifraud-update.service; stop the timer before a manual rollback.")
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
