#!/usr/bin/python3
"""Root-owned deployment gate. Never execute scripts or Compose files from a release."""

import fcntl
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path("/srv/jardines-del-encanto")
REPOSITORY = "https://github.com/asepulvedadev/jardines-del-encanto.git"
ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
}


def parse_command(value):
    match = re.fullmatch(r"(deploy|rollback) ([0-9a-f]{40})", value)
    if not match:
        raise ValueError(
            "Expected: deploy <40-character SHA> or rollback <40-character SHA>"
        )
    return match.group(1), match.group(2)


def run(args, **kwargs):
    return subprocess.run(args, check=True, env=ENV, **kwargs)


def git(*args, **kwargs):
    return run(["git", "--git-dir", str(ROOT / "repository.git"), *args], **kwargs)


def compose(sha, *args):
    # Retain the foundation policy for previously healthy pre-CRM images.
    policy = "crm.compose.yaml" if (ROOT / "crm-releases" / sha).is_file() else "compose.yaml"
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            "jardines",
            "-f",
            str(ROOT / policy),
            *args,
        ],
        env={**ENV, "RELEASE": sha},
        check=True,
        cwd=ROOT,
    )


def prepare_crm(sha):
    markers = ROOT / "crm-releases"
    markers.mkdir(mode=0o700, exist_ok=True)
    (markers / sha).touch(mode=0o600)
    compose(sha, "up", "-d", "--wait", "--wait-timeout", "90", "db")
    # A short-lived maintenance process alone receives the migration credential.
    compose(sha, "run", "--rm", "--no-deps", "migrate")


def activate(sha):
    compose(sha, "up", "-d", "--wait", "--wait-timeout", "150", "web", "api", "db")
    run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--max-time",
            "8",
            "http://127.0.0.1:13400/health/ready",
        ]
    )


def verify_builder():
    policy = json.loads(
        run(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .HostConfig}}",
                "buildx_buildkit_jardines-builder0",
            ],
            capture_output=True,
            text=True,
        ).stdout
    )
    if not (
        0 < policy.get("Memory", 0) <= 3 * 1024**3
        and 0 < policy.get("CpuQuota", 0) <= 200000
        and policy.get("CpuPeriod") == 100000
        and 0 < policy.get("PidsLimit", 0) <= 512
    ):
        raise ValueError("Project builder must have verified CPU, memory and PID caps")


def materialize(sha):
    release = ROOT / "releases" / sha
    if release.exists():
        return release
    with TemporaryDirectory(prefix=".staging-", dir=ROOT / "releases") as temporary:
        staging = Path(temporary)
        archive = staging / "source.tar"
        git("archive", "--format=tar", "--output", str(archive), sha)
        source_dir = staging / "source"
        source_dir.mkdir(mode=0o700)
        with tarfile.open(archive) as source:
            members = source.getmembers()
            if any(not (item.isfile() or item.isdir()) for item in members):
                raise ValueError("Release contains unsupported links or special files")
            source.extractall(source_dir, members=members, filter="data")
        source_dir.rename(release)
    return release


def deploy(operation, sha):
    current = ROOT / "current"
    previous = current.read_text().strip() if current.exists() else None
    if previous:
        run(["/usr/local/libexec/jardines-backup"])
    release = ROOT / "releases" / sha
    if operation == "deploy":
        git("fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
        tip = git(
            "rev-parse", "refs/remotes/origin/main", capture_output=True, text=True
        ).stdout.strip()
        if sha != tip:
            raise ValueError(
                "Refusing a stale deployment: deploy the current main tip or use rollback"
            )
        release = materialize(sha)
        verify_builder()
        # Fixed build locations. Release code cannot replace the root-owned runtime policy.
        for service, context, dockerfile in [
            ("web", release, "apps/web/Dockerfile"),
            ("api", release / "apps/api", "Dockerfile"),
        ]:
            run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--builder",
                    "jardines-builder",
                    "--load",
                    "--tag",
                    f"jardines-{service}:{sha}",
                    "--file",
                    str(context / dockerfile),
                    str(context),
                ]
            )
    elif not (ROOT / "healthy" / sha).is_file():
        raise ValueError("Rollback target must be a previously healthy release")
    try:
        if operation == "deploy":
            prepare_crm(sha)
        activate(sha)
    except Exception:
        if previous:
            print(
                "Deployment failed; restoring previous application images", flush=True
            )
            activate(previous)
        else:
            # Stop this project's application only. Preserve the database and its volume.
            compose(sha, "stop", "web", "api")
        raise
    (ROOT / "healthy" / sha).touch(mode=0o600)
    temporary = ROOT / "current.tmp"
    temporary.write_text(sha + "\n")
    temporary.replace(current)
    print(f"Healthy release: {sha}", flush=True)


def main():
    if len(sys.argv) != 2:
        raise ValueError("One deployment command is required")
    operation, sha = parse_command(
        sys.argv[1]
    )  # Reject before filesystem or process effects.
    if os.geteuid() != 0:
        raise PermissionError("The deployment gate must run as root")
    os.umask(0o077)
    with (ROOT / "deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        deploy(operation, sha)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, PermissionError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
