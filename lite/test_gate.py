"""LT2 done-criteria checks for gate.py. Run: python -m pytest lite/ -q"""

import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).parent / "gate.py"

SPEC = """\
config:
  test_cmd: "python -m pytest -q"
items:
  - id: good-item
    description: Add a title_case helper.
    acceptance_criteria:
      - "title_case('hello world') returns 'Hello World'"
      - "pytest covers the case and the suite passes"
    deps: []
  - id: thin-item
    description: Make it better.
    acceptance_criteria:
      - "works"
    deps: []
"""


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "nightcrew.yaml").write_text(SPEC)
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_lib.py").write_text(
        "from lib import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    git(tmp_path, "checkout", "-qb", "work")
    return tmp_path


def run_gate(repo, *args):
    return subprocess.run(
        [sys.executable, str(GATE), *args, "--repo", str(repo)],
        capture_output=True,
        text=True,
    )


def commit_all(repo):
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "change")


def test_spec_parses_and_flags_thin_item(repo):
    r = run_gate(repo, "spec")
    assert "good-item: ok" in r.stdout
    assert "thin-item: underspecified" in r.stdout
    assert r.returncode == 1


def test_clean_diff_passes(repo):
    (repo / "lib.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return a * b\n"
    )
    (repo / "test_lib.py").write_text(
        "from lib import add, mul\n\ndef test_add():\n    assert add(1, 2) == 3\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n"
    )
    commit_all(repo)
    r = run_gate(repo)
    assert "GATE: PASS" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0


def test_deleted_test_blocked(repo):
    (repo / "test_lib.py").write_text("from lib import add\n")
    commit_all(repo)
    r = run_gate(repo)
    assert r.returncode == 1
    assert "test function removed: test_add" in r.stdout


def test_failing_suite_blocked(repo):
    (repo / "lib.py").write_text("def add(a, b):\n    return a - b\n")
    commit_all(repo)
    r = run_gate(repo)
    assert r.returncode == 1
    assert "test_cmd exited" in r.stdout


def test_missing_test_cmd_blocked(repo):
    (repo / "nightcrew.yaml").write_text("config: {}\nitems: []\n")
    r = run_gate(repo)
    assert r.returncode == 2
