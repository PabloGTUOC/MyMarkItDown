"""Tests for scripts/deploy-nas.sh."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "deploy-nas.sh"


def test_deploy_script_dry_run_plan() -> None:
    """Ensure deploy-nas.sh dry run generates the full deployment plan."""
    if not shutil.which("bash"):
        pytest.skip("bash is missing")

    assert SCRIPT_PATH.exists(), f"Deploy script {SCRIPT_PATH} does not exist"

    env = os.environ.copy()
    env["NAS_HOST"] = "test@example.invalid"
    env["NAS_DIR"] = "/srv/docker/mdbridge"
    env["NAS_DOCKER"] = "docker"

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--dry-run", "--skip-tests"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, (
        f"Script failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    stdout = result.stdout

    # 1. Fail fast: proxy-network check appears before buildx build
    assert "network inspect proxy-network" in stdout
    assert "docker buildx build --platform linux/amd64" in stdout
    network_check_idx = stdout.index("network inspect proxy-network")
    buildx_idx = stdout.index("docker buildx build --platform linux/amd64")
    assert network_check_idx < buildx_idx

    # 2. docker save over ssh includes both mdbridge:latest and version tag mdbridge:<TAG>
    assert "docker save mdbridge:latest mdbridge:" in stdout
    assert 'gunzip | docker load"' in stdout

    # 3. the .env-only-if-missing guard
    assert (
        "if [ ! -f '/srv/docker/mdbridge/.env' ]; then cp"
        " '/srv/docker/mdbridge/.env.example' '/srv/docker/mdbridge/.env'; fi" in stdout
    )
    # 4. compose up -d --force-recreate
    assert "docker compose up -d --force-recreate" in stdout
    # 5. the health poll
    assert "docker inspect -f '{{.State.Health.Status}}' mdbridge" in stdout
    # 6. Deployed tag printed at end
    assert "Deployed mdbridge:" in stdout


def test_deploy_script_requires_nas_host() -> None:
    """Ensure deploy-nas.sh exits non-zero with a clear error when NAS_HOST is missing."""
    if not shutil.which("bash"):
        pytest.skip("bash is missing")

    env = os.environ.copy()
    env.pop("NAS_HOST", None)

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--dry-run", "--skip-tests"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "NAS_HOST environment variable is required" in result.stderr
