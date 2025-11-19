"""
Memory utilities for checkpoint, recall, and plan tools.

These utilities support Julie-compatible .memories system:
- Same JSON schema
- Same file naming conventions (HHMMSS_XXXX.json)
- Same directory structure (.memories/YYYY-MM-DD/, .memories/plans/)
- Same ID format ({type}_{8hex}_{6hex})
- Same git context capture
"""

import json
import re
import secrets
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def generate_checkpoint_id(type: str = "checkpoint") -> str:
    """
    Generate checkpoint ID in Julie format: {type}_{8hex}_{6hex}

    Args:
        type: Memory type (checkpoint, decision, learning, observation)

    Returns:
        ID string like "checkpoint_691cb498_2fc504"

    Examples:
        >>> id1 = generate_checkpoint_id("checkpoint")
        >>> assert id1.startswith("checkpoint_")
        >>> assert len(id1) == len("checkpoint_12345678_123456")
    """
    rand1 = secrets.token_hex(4)  # 8 hex chars
    rand2 = secrets.token_hex(3)  # 6 hex chars
    return f"{type}_{rand1}_{rand2}"


def generate_checkpoint_filename() -> str:
    """
    Generate checkpoint filename in Julie format: HHMMSS_XXXX.json

    Returns:
        Filename string like "180200_abd3.json"

    Examples:
        >>> filename = generate_checkpoint_filename()
        >>> assert filename.endswith(".json")
        >>> assert len(filename) == 16  # HHMMSS (6) + _ + XXXX (4) + .json (5)
    """
    now = datetime.now()
    time_str = now.strftime("%H%M%S")
    random_suffix = secrets.token_hex(2)  # 4 hex chars
    return f"{time_str}_{random_suffix}.json"


def get_checkpoint_path(timestamp: int) -> Path:
    """
    Get full path for checkpoint file based on timestamp.

    Creates path: .memories/YYYY-MM-DD/HHMMSS_XXXX.json
    Uses UTC timezone for consistency with Julie.

    Args:
        timestamp: Unix timestamp (seconds since epoch)

    Returns:
        Path object for checkpoint file

    Examples:
        >>> import time
        >>> now = int(time.time())
        >>> path = get_checkpoint_path(now)
        >>> assert ".memories" in str(path)
        >>> assert path.suffix == ".json"
    """
    from datetime import timezone

    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    date_dir = dt.strftime("%Y-%m-%d")
    filename = generate_checkpoint_filename()
    return Path(".memories") / date_dir / filename


def get_git_context() -> dict[str, Any]:
    """
    Capture current git state (branch, commit, dirty status, changed files).

    Returns:
        Dictionary with git context:
        {
            "branch": "main",
            "commit": "abc1234",
            "dirty": True,
            "files_changed": ["file1.py", "file2.py"]
        }

    Falls back gracefully if git is not available or not in a repo.

    Examples:
        >>> context = get_git_context()
        >>> assert "branch" in context
        >>> assert "commit" in context
        >>> assert "dirty" in context
        >>> assert "files_changed" in context
    """
    import logging
    import os

    logger = logging.getLogger("miller.memory")
    cwd = os.getcwd()

    try:
        # First, find the git root directory
        # Match Julie's approach: stdin=DEVNULL prevents hanging on Windows
        git_root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdin=subprocess.DEVNULL,  # CRITICAL: Prevents waiting for input
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
            cwd=cwd,
        )
        git_root = git_root_result.stdout.strip()

        # Get current branch (Julie uses "branch --show-current")
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
            cwd=git_root,
        )
        branch = branch_result.stdout.strip()

        # Get current commit (short hash)
        commit_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
            cwd=git_root,
        )
        commit = commit_result.stdout.strip()

        # Check if working directory is dirty
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
            cwd=git_root,
        )
        dirty = len(status_result.stdout.strip()) > 0

        # Get list of changed files
        files_changed = []
        if dirty:
            for line in status_result.stdout.strip().split("\n"):
                if line:
                    # Format: "XY filename" where XY is status code
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2:
                        files_changed.append(parts[1])

        return {"branch": branch, "commit": commit, "dirty": dirty, "files_changed": files_changed}

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        # Graceful fallback if git is not available or not in a repo
        logger.debug(f"Git context unavailable: {type(e).__name__}: {e}")
        return {"branch": "unknown", "commit": "unknown", "dirty": False, "files_changed": []}
    except Exception as e:
        # Catch any other unexpected exceptions
        logger.warning(f"Unexpected git context error: {type(e).__name__}: {e}")
        return {"branch": "unknown", "commit": "unknown", "dirty": False, "files_changed": []}


def slugify_title(title: str) -> str:
    """
    Convert plan title to slug for filename/ID.

    Converts to lowercase, replaces spaces with hyphens, removes special chars.

    Args:
        title: Plan title like "Add Search Feature"

    Returns:
        Slug like "add-search-feature"

    Examples:
        >>> slugify_title("Add Search")
        'add-search'
        >>> slugify_title("Fix Bug #123")
        'fix-bug-123'
        >>> slugify_title("Implement User Authentication")
        'implement-user-authentication'
    """
    # Convert to lowercase
    slug = title.lower()

    # Replace spaces with hyphens
    slug = slug.replace(" ", "-")

    # Remove special characters except hyphens and alphanumeric
    slug = re.sub(r"[^a-z0-9-]", "", slug)

    # Remove consecutive hyphens
    slug = re.sub(r"-+", "-", slug)

    # Remove leading/trailing hyphens
    slug = slug.strip("-")

    return slug


def write_json_file(file_path: Path, data: dict[str, Any]) -> None:
    """
    Write JSON data to file with Julie-compatible formatting.

    Creates parent directories if needed, writes with indent=2 and sorted keys,
    adds trailing newline.

    Args:
        file_path: Path to JSON file
        data: Dictionary to serialize

    Examples:
        >>> from pathlib import Path
        >>> write_json_file(Path(".memories/test.json"), {"id": "test"})
    """
    # Create parent directory if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write with Julie's standard formatting
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")  # Trailing newline for git-friendly diffs


def read_json_file(file_path: Path) -> dict[str, Any]:
    """
    Read and parse JSON file.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON data as dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON

    Examples:
        >>> from pathlib import Path
        >>> data = read_json_file(Path(".memories/test.json"))
    """
    with open(file_path) as f:
        return json.load(f)


def normalize_tags(tags: list[str]) -> list[str]:
    """
    Normalize tags to lowercase hyphenated format.

    Args:
        tags: List of tags like ["TDD-Plan", "Julie_Compatibility", "phase planning"]

    Returns:
        Normalized tags like ["tdd-plan", "julie-compatibility", "phase-planning"]

    Examples:
        >>> normalize_tags(["TDD-Plan", "Julie_Compatibility"])
        ['tdd-plan', 'julie-compatibility']
        >>> normalize_tags(["phase planning", "Test Tag"])
        ['phase-planning', 'test-tag']
    """
    normalized = []
    for tag in tags:
        # Convert to lowercase
        normalized_tag = tag.lower()

        # Replace underscores and spaces with hyphens
        normalized_tag = normalized_tag.replace("_", "-")
        normalized_tag = normalized_tag.replace(" ", "-")

        # Remove special characters except hyphens and alphanumeric
        normalized_tag = re.sub(r"[^a-z0-9-]", "", normalized_tag)

        # Remove consecutive hyphens
        normalized_tag = re.sub(r"-+", "-", normalized_tag)

        # Remove leading/trailing hyphens
        normalized_tag = normalized_tag.strip("-")

        if normalized_tag:  # Only add non-empty tags
            normalized.append(normalized_tag)

    return normalized
