import subprocess
from pathlib import Path

import pytest

from apps.scraper.publish import PublishError, publish_changes


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=True)


def _init_local_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare 'remote' and a working tree that pushes to it."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _run("git", "init", "--bare", "-b", "main", cwd=remote)

    work = tmp_path / "work"
    work.mkdir()
    _run("git", "init", "-b", "main", cwd=work)
    _run("git", "remote", "add", "origin", str(remote), cwd=work)
    # Initial commit so 'main' exists on the remote.
    (work / "README.md").write_text("seed\n")
    _run("git", "config", "user.name", "seed", cwd=work)
    _run("git", "config", "user.email", "seed@example.com", cwd=work)
    _run("git", "add", "README.md", cwd=work)
    _run("git", "commit", "-m", "seed", cwd=work)
    _run("git", "push", "-u", "origin", "main", cwd=work)
    return remote, work


def _publish_kwargs() -> dict:
    return {
        "branch": "main",
        "committer_name": "bot",
        "committer_email": "bot@example.com",
        "message": "data: test commit",
    }


def test_publish_commits_and_pushes_new_data(tmp_path: Path):
    remote, work = _init_local_remote(tmp_path)
    data_dir = work / "data"
    data_dir.mkdir()
    (data_dir / "trusted-flaggers.json").write_text("[]")

    pushed = publish_changes(work, **_publish_kwargs())
    assert pushed is True

    # Verify the bare remote has the new commit.
    log = _run("git", "log", "--oneline", "main", cwd=remote).stdout
    assert "data: test commit" in log


def test_publish_returns_false_when_nothing_changed(tmp_path: Path):
    remote, work = _init_local_remote(tmp_path)
    # Seed a data file and push it once.
    (work / "data").mkdir()
    (work / "data" / "trusted-flaggers.json").write_text("[]")
    publish_changes(work, **_publish_kwargs())

    # Second call: no new changes under data/.
    pushed = publish_changes(work, **_publish_kwargs())
    assert pushed is False

    log = _run("git", "log", "--oneline", "main", cwd=remote).stdout
    # Only seed + first publish commit; second call must not have added.
    assert log.count("data: test commit") == 1


def test_publish_raises_when_not_a_git_repo(tmp_path: Path):
    with pytest.raises(PublishError, match="not a git repository"):
        publish_changes(tmp_path, **_publish_kwargs())
