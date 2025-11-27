"""
GPU memory management tool for manual control.

Allows users to manually unload/reload the embedding model to free GPU memory
before launching other GPU-intensive applications.
"""

from miller import server_state


def gpu_memory(action: str = "status") -> str:
    """
    Control GPU memory usage manually.

    This tool allows manual management of GPU memory for power users who want
    to free VRAM before launching other GPU applications (CAD, video editing,
    ML tools, etc.) on memory-constrained GPUs.

    Args:
        action: Control action
            - "status": Show current GPU memory status
            - "unload": Move model to CPU and free GPU memory
            - "reload": Load model back to GPU

    Returns:
        Status message indicating current state

    Example workflows:
        1. Free GPU before launching Blender:
           > gpu_memory(action="unload")
           > [Launch Blender, do work, close Blender]
           > [Miller auto-reloads on next semantic search]

        2. Check current status:
           > gpu_memory(action="status")
           Model on GPU: True
           Batch size: 30
           Device: cuda
           Last use: 120s ago

        3. Manually reload after unload:
           > gpu_memory(action="reload")
    """
    if action == "status":
        if server_state.embeddings is None:
            return "⚠️  Embeddings not initialized yet (server still starting up)"

        on_gpu = server_state.embeddings.is_loaded_on_gpu()
        batch_size = server_state.embeddings.batch_size
        device_type = server_state.embeddings.device_type
        last_use = server_state.embeddings._last_use_time

        # Calculate idle time
        if last_use:
            import time

            idle_seconds = int(time.time() - last_use)
            idle_str = f"{idle_seconds}s ago"
        else:
            idle_str = "never used"

        return (
            f"**GPU Memory Status:**\n"
            f"- Model on GPU: **{on_gpu}**\n"
            f"- Batch size: **{batch_size}** (calculated from VRAM)\n"
            f"- Device: **{device_type}**\n"
            f"- Last use: **{idle_str}**\n"
            f"\n"
            f"_Auto-unload after 5 minutes of inactivity_"
        )

    elif action == "unload":
        if server_state.embeddings is None:
            return "⚠️  Embeddings not initialized yet"

        if not server_state.embeddings.is_loaded_on_gpu():
            return "ℹ️  Model already unloaded from GPU"

        server_state.embeddings.unload()
        return (
            f"✅ **GPU memory freed**\n"
            f"Model moved to CPU. Will automatically reload on next semantic search.\n"
            f"\n"
            f"_You can now launch other GPU applications without memory conflicts._"
        )

    elif action == "reload":
        if server_state.embeddings is None:
            return "⚠️  Embeddings not initialized yet"

        if server_state.embeddings.is_loaded_on_gpu():
            device = server_state.embeddings.device_type
            return f"ℹ️  Model already loaded on {device}"

        server_state.embeddings.reload()
        device = server_state.embeddings.device_type
        return (
            f"✅ **Model reloaded to {device}**\n"
            f"Ready for semantic search operations.\n"
            f"\n"
            f"_Model will auto-unload after 5 minutes of inactivity._"
        )

    else:
        return (
            f"❌ **Unknown action:** `{action}`\n"
            f"\n"
            f"Valid actions:\n"
            f"- `status` - Show current GPU memory status\n"
            f"- `unload` - Free GPU memory (move model to CPU)\n"
            f"- `reload` - Load model back to GPU"
        )
