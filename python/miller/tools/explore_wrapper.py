"""
Fast explore tool - Multi-mode code exploration.

Provides fast_explore for type intelligence, similar code detection, and dependency analysis.
"""

from typing import Any, Literal, Union, Optional


async def fast_explore(
    mode: Literal["types", "similar", "dependencies"] = "types",
    type_name: Optional[str] = None,
    symbol: Optional[str] = None,
    depth: int = 3,
    limit: int = 10,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text",
    storage=None,
    vector_store=None,
) -> Union[dict[str, Any], str]:
    """
    Explore codebases with different modes.

    Modes:
    - types: Type intelligence (implementations, hierarchy, return/parameter types)
    - similar: Find semantically similar code (for duplicate detection)
    - dependencies: Trace transitive dependencies (for impact analysis)

    Args:
        mode: Exploration mode
        type_name: Name of type to explore (required for types mode)
        symbol: Symbol name to explore (required for similar/dependencies modes)
        depth: Maximum traversal depth for dependencies mode (1-10, default 3)
        limit: Maximum results (default: 10)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default), "json", "toon", or "auto"
        storage: StorageManager instance (injected by server)

    Returns:
        Dict or formatted string based on output_format
    """
    # INTENTIONALLY HARDCODED: Similarity threshold is 0.7 based on testing.
    # Exposing this would cause agents to iterate through values (0.9, 0.8, 0.7...)
    # wasting tool calls. 0.7 provides good balance of precision and recall.
    SIMILARITY_THRESHOLD = 0.7
    from miller.tools.explore import fast_explore as _fast_explore
    from miller.tools.explore import _format_similar_as_text, _format_dependencies_as_text, _format_explore_as_text
    from miller.storage import StorageManager
    from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
    from miller.workspace_registry import WorkspaceRegistry

    # Get workspace-specific storage and vector store
    workspace_storage = storage
    workspace_vector_store = vector_store

    if workspace != "primary":
        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            error_msg = f"Workspace '{workspace}' not found"
            if output_format == "text":
                return f"Error: {error_msg}"
            return {"error": error_msg}
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
        # For similar mode, we need workspace-specific vector store
        if mode == "similar":
            from miller.embeddings import VectorStore, EmbeddingManager
            vector_path = get_workspace_vector_path(workspace)
            embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
            workspace_vector_store = VectorStore(db_path=str(vector_path), embeddings=embeddings)

    try:
        result = await _fast_explore(
            mode=mode,
            type_name=type_name,
            symbol=symbol,
            threshold=SIMILARITY_THRESHOLD,
            depth=depth,
            storage=workspace_storage,
            vector_store=workspace_vector_store,
            limit=limit,
        )

        # Handle output format
        if output_format == "text":
            if mode == "similar":
                return _format_similar_as_text(result)
            elif mode == "dependencies":
                return _format_dependencies_as_text(result)
            else:
                return _format_explore_as_text(result)
        elif output_format == "toon":
            from miller.toon_types import encode_toon
            return encode_toon(result)
        elif output_format == "auto":
            # Use TOON for large results (≥10 items)
            from miller.toon_types import encode_toon, should_use_toon
            if should_use_toon(result, threshold=10):
                return encode_toon(result)
            return result
        return result
    finally:
        if workspace != "primary" and workspace_storage:
            workspace_storage.close()
