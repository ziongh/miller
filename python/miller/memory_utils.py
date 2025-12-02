"""
Memory utilities for checkpoint, recall, and plan tools.

Memories are stored as Markdown files with YAML frontmatter:
- Human-readable and editable
- Indexed by Miller (frontmatter + content searchable)
- Git-friendly diffs

File structure:
- .memories/YYYY-MM-DD/HHMMSS_XXXX.md (checkpoints)
- .memories/plans/plan_slug.md (plans)

Format:
---
id: checkpoint_abc123_def456
type: checkpoint
timestamp: 1234567890
tags: [tag1, tag2]
git:
  branch: main
  commit: abc1234
---

Description text here (markdown supported)
"""

import json
import re
import secrets
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


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
    Generate checkpoint filename: HHMMSS_XXXX.md

    Returns:
        Filename string like "180200_abd3.md"

    Examples:
        >>> filename = generate_checkpoint_filename()
        >>> assert filename.endswith(".md")
        >>> assert len(filename) == 14  # HHMMSS (6) + _ + XXXX (4) + .md (3)
    """
    now = datetime.now()
    time_str = now.strftime("%H%M%S")
    random_suffix = secrets.token_hex(2)  # 4 hex chars
    return f"{time_str}_{random_suffix}.md"


def get_checkpoint_path(timestamp: int) -> Path:
    """
    Get full path for checkpoint file based on timestamp.

    Creates path: .memories/YYYY-MM-DD/HHMMSS_XXXX.md
    Uses UTC timezone for consistency.

    Args:
        timestamp: Unix timestamp (seconds since epoch)

    Returns:
        Path object for checkpoint file

    Examples:
        >>> import time
        >>> now = int(time.time())
        >>> path = get_checkpoint_path(now)
        >>> assert ".memories" in str(path)
        >>> assert path.suffix == ".md"
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


def write_memory_file(file_path: Path, metadata: dict[str, Any], content: str) -> None:
    """
    Write memory file as Markdown with YAML frontmatter.

    Format:
        ---
        id: checkpoint_xxx
        type: checkpoint
        ...
        ---

        Content goes here (markdown supported)

    Args:
        file_path: Path to .md file
        metadata: Dictionary of frontmatter fields (id, type, timestamp, etc.)
        content: Main content (description for checkpoints, full content for plans)

    Examples:
        >>> write_memory_file(
        ...     Path(".memories/2025-01-01/120000_abc1.md"),
        ...     {"id": "checkpoint_xxx", "type": "checkpoint"},
        ...     "Fixed the bug in auth"
        ... )
    """
    # Create parent directory if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the markdown file
    frontmatter = yaml.dump(metadata, default_flow_style=False, sort_keys=True, allow_unicode=True)
    markdown = f"---\n{frontmatter}---\n\n{content}\n"

    # Write with UTF-8 encoding
    file_path.write_text(markdown, encoding="utf-8")


def read_memory_file(file_path: Path) -> tuple[dict[str, Any], str]:
    """
    Read memory file with YAML frontmatter.

    Also supports legacy JSON format for backward compatibility.

    Args:
        file_path: Path to .md or .json file

    Returns:
        Tuple of (metadata dict, content string)
        For JSON files, content is the 'description' or 'content' field

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file format is invalid

    Examples:
        >>> metadata, content = read_memory_file(Path(".memories/2025-01-01/test.md"))
        >>> print(metadata["id"])
        checkpoint_xxx
    """
    text = file_path.read_text(encoding="utf-8")

    # Handle legacy JSON format
    if file_path.suffix == ".json":
        data = json.loads(text)
        # Extract content from description (checkpoints) or content (plans)
        content = data.pop("description", data.pop("content", ""))
        return data, content

    # Parse markdown with YAML frontmatter
    if not text.startswith("---"):
        raise ValueError(f"Invalid memory file format: {file_path} (missing frontmatter)")

    # Find the end of frontmatter
    end_marker = text.find("\n---", 3)
    if end_marker == -1:
        raise ValueError(f"Invalid memory file format: {file_path} (unclosed frontmatter)")

    frontmatter_text = text[4:end_marker]  # Skip opening ---\n
    content = text[end_marker + 4:].strip()  # Skip closing ---\n

    metadata = yaml.safe_load(frontmatter_text)
    if metadata is None:
        metadata = {}

    return metadata, content


def migrate_json_to_markdown(json_path: Path) -> Path:
    """
    Migrate a JSON memory file to Markdown format.

    Args:
        json_path: Path to .json file

    Returns:
        Path to new .md file

    Examples:
        >>> md_path = migrate_json_to_markdown(Path(".memories/2025-01-01/120000_abc1.json"))
        >>> print(md_path)
        .memories/2025-01-01/120000_abc1.md
    """
    # Read JSON
    data = read_json_file(json_path)

    # Extract content field
    if "content" in data:
        # Plan file
        content = data.pop("content")
    elif "description" in data:
        # Checkpoint file
        content = data.pop("description")
    else:
        content = ""

    # Write markdown
    md_path = json_path.with_suffix(".md")
    write_memory_file(md_path, data, content)

    return md_path


def migrate_all_memories(memories_dir: Path = Path(".memories")) -> dict[str, int]:
    """
    Migrate all JSON memory files to Markdown format.

    Args:
        memories_dir: Root memories directory

    Returns:
        Dict with counts: {"migrated": N, "skipped": N, "errors": N}

    Examples:
        >>> stats = migrate_all_memories()
        >>> print(f"Migrated {stats['migrated']} files")
    """
    stats = {"migrated": 0, "skipped": 0, "errors": 0}

    if not memories_dir.exists():
        return stats

    for json_file in memories_dir.rglob("*.json"):
        md_file = json_file.with_suffix(".md")

        # Skip if already migrated
        if md_file.exists():
            stats["skipped"] += 1
            continue

        try:
            migrate_json_to_markdown(json_file)
            stats["migrated"] += 1
        except Exception as e:
            import logging
            logging.getLogger("miller.memory").warning(f"Failed to migrate {json_file}: {e}")
            stats["errors"] += 1

    return stats


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
