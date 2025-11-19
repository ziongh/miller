"""
Workspace Registry - Manages workspace registration and metadata.

This module tracks primary and reference workspaces, their paths, and indexing status.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional


@dataclass
class WorkspaceEntry:
    """Metadata for a registered workspace."""

    workspace_id: str
    name: str
    path: str
    workspace_type: Literal["primary", "reference"]
    created_at: int  # Unix timestamp
    last_indexed: Optional[int] = None
    symbol_count: int = 0
    file_count: int = 0


class WorkspaceRegistry:
    """
    Manages workspace registration and metadata.

    Workspaces are stored in a JSON file at .miller/workspace_registry.json.
    Each workspace has a unique ID generated from its path + name.
    """

    def __init__(self, path: str = ".miller/workspace_registry.json"):
        """
        Initialize workspace registry.

        Args:
            path: Path to registry JSON file
        """
        self.path = Path(path)
        self.workspaces: Dict[str, WorkspaceEntry] = {}
        self._load()

    def add_workspace(
        self,
        path: str,
        name: str,
        workspace_type: Literal["primary", "reference"] = "primary",
    ) -> str:
        """
        Add or update workspace entry.

        Args:
            path: Workspace root path
            name: Display name for workspace
            workspace_type: "primary" or "reference"

        Returns:
            Workspace ID (stable, generated from path)
        """
        workspace_id = self._generate_workspace_id(path, name)

        entry = WorkspaceEntry(
            workspace_id=workspace_id,
            name=name,
            path=str(Path(path).resolve()) if Path(path).exists() else path,
            workspace_type=workspace_type,
            created_at=int(datetime.now().timestamp()),
        )

        self.workspaces[workspace_id] = entry
        self._save()
        return workspace_id

    def _generate_workspace_id(self, path: str, name: str) -> str:
        """
        Generate stable workspace ID from path.

        Uses path hash for uniqueness, name slug for readability.

        Args:
            path: Workspace path
            name: Workspace name

        Returns:
            Workspace ID (format: "name-slug_hash8")
        """
        # Resolve path for stable hashing (if it exists)
        resolved_path = str(Path(path).resolve()) if Path(path).exists() else path

        # Hash path for uniqueness (8 hex chars)
        path_hash = hashlib.sha256(resolved_path.encode()).hexdigest()[:8]

        # Slugify name for readability
        slug = name.lower().replace(" ", "-").replace("_", "-")

        # Remove non-alphanumeric except dashes
        slug = "".join(c for c in slug if c.isalnum() or c == "-")

        return f"{slug}_{path_hash}"

    def list_workspaces(self) -> List[Dict]:
        """
        Return all workspaces as dictionaries.

        Returns:
            List of workspace dicts with all metadata fields
        """
        return [asdict(w) for w in self.workspaces.values()]

    def get_workspace(self, workspace_id: str) -> Optional[WorkspaceEntry]:
        """
        Get specific workspace by ID.

        Args:
            workspace_id: Workspace ID to retrieve

        Returns:
            WorkspaceEntry if found, None otherwise
        """
        return self.workspaces.get(workspace_id)

    def remove_workspace(self, workspace_id: str) -> bool:
        """
        Remove workspace from registry.

        Args:
            workspace_id: Workspace ID to remove

        Returns:
            True if removed, False if not found
        """
        if workspace_id in self.workspaces:
            del self.workspaces[workspace_id]
            self._save()
            return True
        return False

    def update_workspace_stats(
        self, workspace_id: str, symbol_count: int, file_count: int
    ) -> bool:
        """
        Update workspace indexing statistics.

        Args:
            workspace_id: Workspace to update
            symbol_count: Number of symbols indexed
            file_count: Number of files indexed

        Returns:
            True if updated, False if workspace not found
        """
        if workspace_id in self.workspaces:
            self.workspaces[workspace_id].symbol_count = symbol_count
            self.workspaces[workspace_id].file_count = file_count
            self.workspaces[workspace_id].last_indexed = int(datetime.now().timestamp())
            self._save()
            return True
        return False

    def _load(self):
        """Load registry from disk."""
        if self.path.exists():
            with open(self.path) as f:
                data = json.load(f)
                self.workspaces = {k: WorkspaceEntry(**v) for k, v in data.items()}

    def _save(self):
        """Save registry to disk (pretty-printed JSON)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(
                {k: asdict(v) for k, v in self.workspaces.items()}, f, indent=2, sort_keys=True
            )
            # Add trailing newline for git-friendly diffs
            f.write("\n")
