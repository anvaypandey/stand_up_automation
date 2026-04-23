import logging
import subprocess
from datetime import datetime
from pathlib import Path
from collectors.utils import activity_since

log = logging.getLogger(__name__)


def fetch_git_activity(repo_paths: list[str], author: str, since: datetime | None = None) -> dict:
    """Scan local git repos for commits by author since the activity window.

    Args:
        repo_paths: Absolute paths to git repositories to scan.
        author:     Name or email passed to `git log --author`.
        since:      Activity cutoff; defaults to activity_since().
    """
    cutoff = (since or activity_since()).strftime("%Y-%m-%dT%H:%M:%S")
    activity: dict = {"repos": []}

    for raw_path in repo_paths:
        path = Path(raw_path.strip())

        if not (path / ".git").exists():
            log.warning("Skipping %s — not a valid git repository", path)
            continue

        try:
            result = subprocess.run(
                [
                    "git", "log",
                    f"--since={cutoff}",
                    f"--author={author}",
                    "--oneline",
                    "--no-merges",
                ],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            log.warning("git log timed out for %s — skipping", path)
            continue
        except Exception as e:
            log.warning("git log failed for %s: %s", path, e)
            continue

        commits = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            hash_, _, message = line.partition(" ")
            commits.append({"hash": hash_, "message": message})

        if commits:
            activity["repos"].append({"name": path.name, "commits": commits})

    return activity
