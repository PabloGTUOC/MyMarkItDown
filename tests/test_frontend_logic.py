"""Test that frontend pure logic runs and passes under node --test."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_frontend_plan_logic_node() -> None:
    """Execute tests/js/plan.test.mjs with node --test if Node is installed."""
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js is not available in environment")

    test_file = Path(__file__).parent / "js" / "plan.test.mjs"
    assert test_file.exists(), f"Test file {test_file} does not exist"

    result = subprocess.run(
        [node_bin, "--test", str(test_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"Node test failed with exit code {result.returncode}:\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
