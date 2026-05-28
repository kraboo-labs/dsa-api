import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class PublishError(RuntimeError):
    """Raised when the dsa-data git push pipeline fails."""


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _has_local_changes(export_dir: Path) -> bool:
    """True if `git status --porcelain` reports anything under data/."""
    result = _run(["git", "status", "--porcelain", "data"], export_dir)
    return bool(result.stdout.strip())


def publish_changes(
    export_dir: Path,
    *,
    branch: str,
    committer_name: str,
    committer_email: str,
    message: str,
    remote: str = "origin",
) -> bool:
    """Stage data/, commit if changed, push to `remote`/`branch`. Returns True
    if a new commit was pushed, False if there was nothing to publish.

    Assumes export_dir is already a git working tree configured with the
    desired remote. Auth (SSH key, token) is the caller's responsibility.
    """
    if not (export_dir / ".git").exists():
        raise PublishError(f"{export_dir} is not a git repository — clone dsa-data first")

    # Configure identity on the working tree so commits are attributable even
    # if the global git identity is unset (e.g. inside a CronJob container).
    _run(["git", "config", "user.name", committer_name], export_dir)
    _run(["git", "config", "user.email", committer_email], export_dir)

    if not _has_local_changes(export_dir):
        logger.info("dsa-data: no changes under data/, skipping push")
        return False

    add = _run(["git", "add", "data"], export_dir)
    if add.returncode != 0:
        raise PublishError(f"git add failed: {add.stderr}")

    commit = _run(["git", "commit", "-m", message], export_dir)
    if commit.returncode != 0:
        # 'nothing to commit' shouldn't happen after the porcelain check, but
        # if it does we treat it as a no-op rather than an error.
        if "nothing to commit" in commit.stdout + commit.stderr:
            return False
        raise PublishError(f"git commit failed: {commit.stderr}")

    push = _run(["git", "push", remote, branch], export_dir)
    if push.returncode != 0:
        raise PublishError(f"git push failed: {push.stderr}")

    logger.info("dsa-data: pushed commit to %s/%s", remote, branch)
    return True
