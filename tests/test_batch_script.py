"""Tests for scripts/mdbridge-batch.sh."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "mdbridge-batch.sh"


def get_free_port() -> int:
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_bash4() -> str | None:
    """Find a bash >= 4 interpreter if available on the system."""
    for candidate in ["/opt/homebrew/bin/bash", "/usr/local/bin/bash"]:
        p = Path(candidate)
        if p.is_file() and os.access(p, os.X_OK):
            try:
                res = subprocess.run(
                    [str(p), "-c", "echo $BASH_VERSINFO"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
            except (subprocess.SubprocessError, OSError):
                res = None

            if res is not None and res.returncode == 0 and res.stdout.strip():
                try:
                    major = int(res.stdout.strip().split()[0])
                except ValueError:
                    major = 0
                if major >= 4:
                    return str(p)
    return None


def _run_batch_script_test(bash_bin: str) -> None:
    """Run batch conversion test suite using the specified bash binary."""
    if not shutil.which(bash_bin) or not shutil.which("curl"):
        pytest.skip(f"{bash_bin} or curl is missing")

    assert SCRIPT_PATH.exists(), f"Batch script {SCRIPT_PATH} does not exist"

    port = get_free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)

    # Start uvicorn server in background subprocess
    server_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    server_url = f"http://127.0.0.1:{port}"

    try:
        # Wait for server to become healthy
        server_ready = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{server_url}/healthz", timeout=1) as resp:
                    if resp.status == 200:
                        server_ready = True
                        break
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)

        assert server_ready, "Uvicorn server failed to start within timeout"

        # Prepare test directories
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            in_dir = tmp_path / "input"
            out_dir = tmp_path / "output"

            (in_dir / "sub").mkdir(parents=True, exist_ok=True)
            (in_dir / "collision").mkdir(parents=True, exist_ok=True)

            # Copy sample files
            shutil.copy(FIXTURES_DIR / "sample.pdf", in_dir / "sample.pdf")
            shutil.copy(FIXTURES_DIR / "sample.docx", in_dir / "sub" / "sample.docx")
            shutil.copy(
                FIXTURES_DIR / "sample.pdf", in_dir / "collision" / "Report.pdf"
            )
            shutil.copy(
                FIXTURES_DIR / "sample.docx", in_dir / "collision" / "Report.docx"
            )
            shutil.copy(FIXTURES_DIR / "photo.jpg", in_dir / "photo.jpg")

            # First run: should convert supported files and resolve collision
            run1 = subprocess.run(
                [
                    bash_bin,
                    str(SCRIPT_PATH),
                    "-u",
                    server_url,
                    str(in_dir),
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert run1.returncode == 0, (
                f"Run 1 failed:\nSTDOUT:\n{run1.stdout}\nSTDERR:\n{run1.stderr}"
            )

            # Verify output structure
            assert (out_dir / "sample.md").exists(), "sample.md not generated"
            assert (out_dir / "sub" / "sample.md").exists(), (
                "sub/sample.md not generated"
            )
            # Collision pair in the same folder must be Report.pdf.md and Report.docx.md
            assert (out_dir / "collision" / "Report.pdf.md").exists(), (
                "Report.pdf.md collision name missing"
            )
            assert (out_dir / "collision" / "Report.docx.md").exists(), (
                "Report.docx.md collision name missing"
            )
            # Photo must not be converted
            assert not (out_dir / "photo.md").exists(), "photo.md should not exist"
            assert not (out_dir / "photo.jpg.md").exists(), (
                "photo.jpg.md should not exist"
            )

            # Check summary text in stdout
            assert "4 converted" in run1.stdout
            assert "1 skipped" in run1.stdout
            assert "0 failed" in run1.stdout

            # Second run: incremental mode should skip all files
            run2 = subprocess.run(
                [
                    bash_bin,
                    str(SCRIPT_PATH),
                    "-u",
                    server_url,
                    str(in_dir),
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert run2.returncode == 0, (
                f"Run 2 failed:\nSTDOUT:\n{run2.stdout}\nSTDERR:\n{run2.stderr}"
            )
            assert "0 converted" in run2.stdout
            assert "5 skipped" in run2.stdout
            assert "0 failed" in run2.stdout

    finally:
        server_process.terminate()
        try:
            server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_process.kill()


def test_batch_script_end_to_end() -> None:
    """Test batch conversion script with default bash."""
    _run_batch_script_test("bash")


def test_batch_script_bash4_end_to_end() -> None:
    """Test batch conversion script under bash >= 4 if available."""
    bash4 = find_bash4()
    if not bash4:
        pytest.skip(
            "No bash >= 4 found at /opt/homebrew/bin/bash or /usr/local/bin/bash"
        )
    _run_batch_script_test(bash4)
