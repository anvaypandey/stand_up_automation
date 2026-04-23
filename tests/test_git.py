import subprocess
from unittest.mock import patch, MagicMock
from collectors.git import fetch_git_activity


def _run(stdout="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.returncode = returncode
    return m


def test_commits_returned_for_valid_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    with patch("collectors.git.subprocess.run", return_value=_run("abc1234 Add feature\ndef5678 Fix bug")):
        result = fetch_git_activity([str(tmp_path)], "author")
    assert len(result["repos"]) == 1
    assert result["repos"][0]["name"] == tmp_path.name
    assert result["repos"][0]["commits"] == [
        {"hash": "abc1234", "message": "Add feature"},
        {"hash": "def5678", "message": "Fix bug"},
    ]


def test_repo_without_git_dir_is_skipped(tmp_path, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="collectors.git"):
        result = fetch_git_activity([str(tmp_path)], "author")
    assert result["repos"] == []
    assert "not a valid git repository" in caplog.text


def test_empty_commit_output_excluded_from_repos(tmp_path):
    (tmp_path / ".git").mkdir()
    with patch("collectors.git.subprocess.run", return_value=_run("")):
        result = fetch_git_activity([str(tmp_path)], "author")
    assert result["repos"] == []


def test_multiple_repos_both_included(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir(); (repo_a / ".git").mkdir()
    repo_b.mkdir(); (repo_b / ".git").mkdir()
    with patch("collectors.git.subprocess.run", return_value=_run("aaa1111 Commit")):
        result = fetch_git_activity([str(repo_a), str(repo_b)], "author")
    assert len(result["repos"]) == 2


def test_timeout_skips_repo_with_warning(tmp_path, caplog):
    import logging
    (tmp_path / ".git").mkdir()
    with patch("collectors.git.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
        with caplog.at_level(logging.WARNING, logger="collectors.git"):
            result = fetch_git_activity([str(tmp_path)], "author")
    assert result["repos"] == []
    assert "timed out" in caplog.text


def test_subprocess_exception_skips_repo_with_warning(tmp_path, caplog):
    import logging
    (tmp_path / ".git").mkdir()
    with patch("collectors.git.subprocess.run", side_effect=OSError("git not found")):
        with caplog.at_level(logging.WARNING, logger="collectors.git"):
            result = fetch_git_activity([str(tmp_path)], "author")
    assert result["repos"] == []
    assert "git log failed" in caplog.text


def test_blank_lines_in_output_ignored(tmp_path):
    (tmp_path / ".git").mkdir()
    with patch("collectors.git.subprocess.run", return_value=_run("abc1234 Commit\n\n\ndef5678 Another")):
        result = fetch_git_activity([str(tmp_path)], "author")
    assert len(result["repos"][0]["commits"]) == 2


def test_since_passed_to_git_log(tmp_path):
    from datetime import datetime, timezone
    (tmp_path / ".git").mkdir()
    since = datetime(2026, 4, 20, 9, 0, 0, tzinfo=timezone.utc)
    with patch("collectors.git.subprocess.run", return_value=_run("")) as mock_run:
        fetch_git_activity([str(tmp_path)], "me", since=since)
    cmd = mock_run.call_args.args[0]
    assert any("2026-04-20T09:00:00" in arg for arg in cmd)


def test_empty_repo_list_returns_empty(tmp_path):
    result = fetch_git_activity([], "author")
    assert result == {"repos": []}
