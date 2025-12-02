"""
Fast explore tool - Multi-mode code exploration.

Provides fast_explore for type intelligence and semantic similar code detection.

Note: For dependency tracing, use trace_call_path(direction="downstream") instead,
which provides richer features including semantic cross-language discovery.
"""

from typing import Any, Literal, Union, Optional


async def fast_explore(
    mode: Literal["types", "similar", "dead_code", "hot_spots"] = "types",
    type_name: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 10,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text",
    storage=None,
    vector_store=None,
    embeddings=None,
) -> Union[dict[str, Any], str]:
    """
    Explore codebases with different modes.

    Modes:
    - types: Type intelligence (implementations, hierarchy, return/parameter types)
    - similar: Find semantically similar code using TRUE vector embedding similarity
    - dead_code: Find unreferenced symbols (potential cleanup candidates)
    - hot_spots: Find most-referenced symbols (high-impact code)

    Note: For dependency tracing, use trace_call_path(direction="downstream") instead.

    Args:
        mode: Exploration mode ("types", "similar", "dead_code", or "hot_spots")
        type_name: Name of type to explore (required for types mode)
        symbol: Symbol name to explore (required for similar mode)
        limit: Maximum results (default: 10)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default), "json", "toon", or "auto"
        storage: StorageManager instance (injected by server)
        vector_store: VectorStore instance (for similar mode)
        embeddings: EmbeddingManager instance (for similar mode)

    Returns:
        Dict or formatted string based on output_format
    """
    # INTENTIONALLY HARDCODED: Similarity threshold is 0.7 based on testing.
    # Exposing this would cause agents to iterate through values (0.9, 0.8, 0.7...)
    # wasting tool calls. 0.7 provides good balance of precision and recall.
    SIMILARITY_THRESHOLD = 0.7

    from miller.tools.explore import fast_explore as _fast_explore
    from miller.tools.explore import (
        _format_similar_as_text,
        _format_explore_as_text,
        _format_dead_code_as_text,
        _format_hot_spots_as_text,
    )
    from miller.storage import StorageManager
    from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
    from miller.workspace_registry import WorkspaceRegistry

    # Initialize workspace-specific resources
    workspace_storage = storage
    workspace_vector_store = vector_store
    workspace_embeddings = embeddings
    should_close_storage = False

    # Try to get workspace from registry
    registry = WorkspaceRegistry()
    workspace_entry = registry.get_workspace(workspace)

    if workspace_entry:
        # Workspace exists - get workspace-specific storage if not provided
        db_path = get_workspace_db_path(workspace)
        if workspace_storage is None:
            workspace_storage = StorageManager(db_path=str(db_path))
            should_close_storage = True

        # For similar mode, ensure we have vector store and embeddings
        if mode == "similar":
            if workspace_vector_store is None or workspace_embeddings is None:
                # Get from server_state (initialized during server startup)
                from miller import server_state
                if workspace_embeddings is None:
                    workspace_embeddings = server_state.embeddings
                if workspace_vector_store is None:
                    workspace_vector_store = server_state.vector_store

                # If still None, create workspace-specific instances
                if workspace_vector_store is None or workspace_embeddings is None:
                    from miller.embeddings import VectorStore, EmbeddingManager
                    vector_path = get_workspace_vector_path(workspace)
                    if workspace_embeddings is None:
                        workspace_embeddings = EmbeddingManager(
                            model_name="BAAI/bge-small-en-v1.5", device="auto"
                        )
                    if workspace_vector_store is None:
                        workspace_vector_store = VectorStore(
                            db_path=str(vector_path), embeddings=workspace_embeddings
                        )
    elif workspace_storage is None:
        # Workspace not found and no storage provided
        error_msg = f"Workspace '{workspace}' not found"
        if output_format == "text":
            return f"Error: {error_msg}"
        return {"error": error_msg}
    # else: workspace not in registry but storage provided explicitly - use it (test scenario)

    try:
        result = await _fast_explore(
            mode=mode,
            type_name=type_name,
            symbol=symbol,
            threshold=SIMILARITY_THRESHOLD,
            storage=workspace_storage,
            vector_store=workspace_vector_store,
            embeddings=workspace_embeddings,
            limit=limit,
        )

        # Handle output format
        if output_format == "text":
            if mode == "similar":
                return _format_similar_as_text(result)
            elif mode == "dead_code":
                return _format_dead_code_as_text(result)
            elif mode == "hot_spots":
                return _format_hot_spots_as_text(result)
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
        if should_close_storage and workspace_storage:
            workspace_storage.close()
