"""
Embedding generation with sentence-transformers.

Manages GPU detection, model loading, and batch embedding generation.
Uses L2 normalization for cosine similarity in vector search.
"""

import logging
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Optional

import numpy as np
import torch

# WORKAROUND: DirectML doesn't support torch.inference_mode() properly
# It throws "RuntimeError: Cannot set version_counter for inference tensor"
# Patch inference_mode BEFORE importing sentence_transformers because the decorator
# is applied at import time. See: https://github.com/microsoft/DirectML/issues/622
def _apply_directml_inference_mode_patch() -> bool:
    """
    Patch torch.inference_mode for DirectML compatibility if DirectML is available.
    Must be called BEFORE importing sentence_transformers.

    Returns:
        True if patch was applied, False otherwise
    """
    try:
        import torch_directml

        if torch_directml.is_available():
            # Store original for potential restoration
            if not hasattr(torch, "_original_inference_mode"):
                torch._original_inference_mode = torch.inference_mode

            # Replace with no_grad-based implementation
            torch.inference_mode = (
                lambda mode=True: torch.no_grad() if mode else torch.enable_grad()
            )
            return True
    except ImportError:
        pass
    return False


_DIRECTML_PATCHED = _apply_directml_inference_mode_patch()

# NOW we can safely import sentence_transformers
from sentence_transformers import SentenceTransformer


class EmbeddingManager:
    """
    Manages embedding generation with sentence-transformers.

    Features:
    - GPU auto-detection (CUDA, MPS/Metal, or CPU)
    - Batch encoding for performance
    - L2 normalization for cosine similarity
    - BGE-small model (384 dimensions)
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", device: str = "auto"):
        """
        Initialize embedding model.

        Args:
            model_name: HuggingFace model identifier
            device: Device to use ("auto", "cuda", "mps", "cpu")
        """
        logger = logging.getLogger("miller.embeddings")

        # Auto-detect device with priority: CUDA > ROCm > XPU > MPS > DirectML > CPU
        # device_type: string identifier for logging/display ("cuda", "mps", "directml", "cpu")
        # device: actual value to pass to PyTorch (string or torch.device object)
        if device == "auto":
            if torch.cuda.is_available():
                self.device = "cuda"
                self.device_type = "cuda"
                gpu_name = torch.cuda.get_device_name(0)
                logger.info(f"🚀 Using CUDA GPU: {gpu_name}")
            elif self._check_rocm_available():
                # ROCm support (AMD GPUs on Linux)
                # Requires: pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
                self.device = "cuda"  # ROCm uses CUDA API
                self.device_type = "cuda"
                gpu_name = torch.cuda.get_device_name(0)
                logger.info(f"🔴 Using AMD GPU with ROCm: {gpu_name}")
            elif self._check_xpu_available():
                # Intel Arc/Data Center GPU support (Linux/Windows)
                # Requires: pip install torch --index-url https://download.pytorch.org/whl/nightly/xpu
                self.device = "xpu"
                self.device_type = "xpu"
                gpu_name = self._get_xpu_device_name()
                logger.info(f"🔷 Using Intel XPU: {gpu_name}")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self.device = "mps"
                self.device_type = "mps"
                logger.info(
                    "🍎 Using Apple Silicon MPS (Metal Performance Shaders) for GPU acceleration"
                )
            elif self._check_directml_available():
                # DirectML support (Windows AMD/Intel GPUs via torch-directml)
                # Requires: pip install torch-directml
                # IMPORTANT: Must use torch_directml.device() - PyTorch doesn't understand "dml"
                import torch_directml

                self.device = torch_directml.device()  # Returns torch.device("privateuseone:0")
                self.device_type = "directml"
                # Note: inference_mode patch is applied at module level (before SentenceTransformer import)
                logger.info("🪟 Using DirectML for GPU acceleration (AMD/Intel GPU on Windows)")
            else:
                self.device = "cpu"
                self.device_type = "cpu"
                logger.info("💻 Using CPU (no GPU detected)")
        else:
            self.device = device
            self.device_type = device if isinstance(device, str) else str(device)
            logger.info(f"🎯 Using manually specified device: {device}")

        # Load model (suppress stdout/stderr to keep MCP protocol clean)
        # SentenceTransformer downloads models and writes progress to stdout,
        # which breaks MCP's JSON-RPC protocol (stdout must be clean)
        #
        # IMPORTANT: Set offline mode to prevent HuggingFace from doing network
        # "freshness checks" on cached models. Without this, each check can timeout
        # after 10s with retries, causing 20-30s delays on first search.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        with open(os.devnull, "w") as devnull, redirect_stdout(devnull), redirect_stderr(devnull):
            self.model = SentenceTransformer(model_name, device=self.device)

        self.model_name = model_name

        # Get embedding dimension from model
        self.dimensions = self.model.get_sentence_embedding_dimension()

        logger.info(
            f"✅ Embedding model loaded: {model_name} ({self.dimensions}D vectors on {self.device_type})"
        )

        # Track last usage for auto-unload (Julie-style GPU memory management)
        self._last_use_time: Optional[float] = None
        self._original_device = self.device  # Remember original device for reload

        # Calculate optimal batch size based on GPU memory (Julie's DirectML-safe formula)
        vram_bytes = self._detect_gpu_memory_bytes()
        if vram_bytes:
            self.batch_size = self._calculate_batch_size_from_vram(vram_bytes)
        else:
            # Conservative fallback (Julie's default)
            self.batch_size = 50
            logger.info(f"⚙️  Using default batch size: {self.batch_size} (GPU memory detection unavailable)")

    def _check_rocm_available(self) -> bool:
        """
        Check if ROCm is available (AMD GPUs on Linux).

        ROCm requires PyTorch built with ROCm support:
        pip install torch --index-url https://download.pytorch.org/whl/rocm6.2

        Returns:
            True if ROCm is available, False otherwise
        """
        try:
            # ROCm uses the CUDA API, but torch.version.hip is set
            return (
                hasattr(torch.version, "hip")
                and torch.version.hip is not None
                and torch.cuda.is_available()
            )
        except Exception:
            return False

    def _check_xpu_available(self) -> bool:
        """
        Check if Intel XPU is available (Intel Arc/Data Center GPUs).

        XPU requires PyTorch built with XPU support:
        pip install torch --index-url https://download.pytorch.org/whl/nightly/xpu

        Returns:
            True if XPU is available, False otherwise
        """
        try:
            # Intel XPU support added in PyTorch 2.5+
            return hasattr(torch, "xpu") and torch.xpu.is_available()
        except Exception:
            return False

    def _get_xpu_device_name(self) -> str:
        """
        Get Intel XPU device name.

        Returns:
            Device name string
        """
        try:
            return torch.xpu.get_device_name(0)
        except Exception:
            return "Intel XPU Device"

    def _detect_gpu_memory_bytes(self) -> Optional[int]:
        """
        Detect total GPU VRAM in bytes (platform-specific).

        Returns:
            Total VRAM in bytes, or None if detection fails
        """
        logger = logging.getLogger("miller.embeddings")

        if self.device_type == "cpu":
            return None  # CPU mode, no GPU memory

        if self.device_type == "cuda":
            return self._detect_cuda_memory()
        elif self.device_type == "directml":
            return self._detect_directml_memory()
        elif self.device_type == "xpu":
            return self._detect_xpu_memory()
        elif self.device_type == "mps":
            return self._detect_mps_memory()

        return None

    def _detect_cuda_memory(self) -> Optional[int]:
        """
        Detect CUDA GPU memory via PyTorch API.

        Returns:
            Total VRAM in bytes, or None if detection fails
        """
        try:
            # PyTorch provides total memory directly
            total_memory = torch.cuda.get_device_properties(0).total_memory
            vram_gb = total_memory / 1_073_741_824.0
            logger = logging.getLogger("miller.embeddings")
            logger.info(f"📊 Detected CUDA GPU memory: {vram_gb:.2f} GB")
            return total_memory
        except Exception as e:
            logger = logging.getLogger("miller.embeddings")
            logger.warning(f"Failed to detect CUDA memory: {e}")
            return None

    def _detect_directml_memory(self) -> Optional[int]:
        """
        Detect DirectML GPU memory via WMI (Windows).

        Uses WMI as a simpler alternative to DXGI ctypes implementation.
        Falls back to default batch size if detection fails.

        Returns:
            Total VRAM in bytes, or None if detection fails
        """
        logger = logging.getLogger("miller.embeddings")

        try:
            import wmi

            # Query WMI for GPU information
            w = wmi.WMI()
            gpus = w.Win32_VideoController()

            if not gpus:
                logger.warning("No GPUs found via WMI")
                return None

            # Find GPU with most dedicated VRAM (matches Julie's DXGI logic)
            max_vram = 0
            selected_gpu = None

            for gpu in gpus:
                if hasattr(gpu, 'AdapterRAM') and gpu.AdapterRAM:
                    vram_bytes = int(gpu.AdapterRAM)
                    if vram_bytes > max_vram:
                        max_vram = vram_bytes
                        selected_gpu = gpu

            if max_vram > 0 and selected_gpu:
                vram_gb = max_vram / 1_073_741_824.0
                gpu_name = getattr(selected_gpu, 'Name', 'Unknown GPU')
                logger.info(f"📊 Detected DirectML GPU: {gpu_name} ({vram_gb:.2f} GB)")
                return max_vram
            else:
                logger.warning("No GPU with dedicated VRAM found via WMI")
                return None

        except ImportError:
            logger.warning("WMI module not available - install with: pip install wmi")
            return None
        except Exception as e:
            logger.warning(f"Failed to detect DirectML memory via WMI: {e}")
            return None

    def _detect_xpu_memory(self) -> Optional[int]:
        """
        Detect Intel XPU memory via PyTorch XPU API.

        Returns:
            Total VRAM in bytes, or None if detection fails
        """
        logger = logging.getLogger("miller.embeddings")

        try:
            if hasattr(torch, 'xpu') and hasattr(torch.xpu, 'get_device_properties'):
                total_memory = torch.xpu.get_device_properties(0).total_memory
                vram_gb = total_memory / 1_073_741_824.0
                logger.info(f"📊 Detected Intel XPU memory: {vram_gb:.2f} GB")
                return total_memory
        except Exception as e:
            logger.warning(f"Failed to detect XPU memory: {e}")

        return None

    def _detect_mps_memory(self) -> Optional[int]:
        """
        Detect Apple MPS memory.

        Note: PyTorch MPS doesn't expose total memory easily.
        We use a conservative default for Apple Silicon.

        Returns:
            None (use default batch size for MPS)
        """
        logger = logging.getLogger("miller.embeddings")

        # MPS doesn't expose total memory in PyTorch
        # Apple Silicon has unified memory architecture
        # Conservative approach: use default batch size
        logger.info("ℹ️  MPS memory detection not available - using default batch size")
        return None

    def _calculate_batch_size_from_vram(self, vram_bytes: int) -> int:
        """
        Calculate optimal batch size using Julie's DirectML-safe formula.

        Formula: batch_size = (VRAM_GB / 6.0) * 30
        Clamped to [25, 250] range

        This formula is 40% more conservative than the original, specifically
        tuned for DirectML fragility and tested on 6GB A1000.

        Real-world validation:
        - 6GB A1000 @ 97.6% util: batch_size=50 → 55s batch + crash
        - 6GB A1000: batch_size=30 → stable operation ✅

        Args:
            vram_bytes: Total GPU VRAM in bytes

        Returns:
            Optimal batch size (clamped to [25, 250])
        """
        logger = logging.getLogger("miller.embeddings")

        vram_gb = vram_bytes / 1_073_741_824.0

        # Julie's DirectML-safe formula (40% more conservative)
        # Background: DirectML on Windows is more fragile under memory pressure than CUDA
        # Previous formula used total VRAM without accounting for already-allocated memory
        calculated = int((vram_gb / 6.0) * 30.0)

        # Clamp to safe range [25, 250]
        # - Minimum 25: Ensures reasonable performance even on small GPUs
        # - Maximum 250: Avoid timeout issues and excessive failure blast radius
        batch_size = max(25, min(250, calculated))

        logger.info(
            f"📊 GPU Memory: {vram_gb:.2f} GB → Dynamic batch size: {batch_size} "
            f"(Julie's DirectML-safe formula)"
        )

        return batch_size

    def _check_directml_available(self) -> bool:
        """
        Check if DirectML is available (Windows AMD/Intel GPU acceleration).

        DirectML requires torch-directml package:
        pip install torch-directml

        Returns:
            True if DirectML is available, False otherwise
        """
        try:
            import torch_directml

            # DirectML uses "privateuseone" backend in PyTorch
            return torch_directml.is_available()
        except ImportError:
            return False

    def is_loaded_on_gpu(self) -> bool:
        """
        Check if model is currently loaded on GPU.

        Returns:
            True if model is on GPU device, False if on CPU
        """
        if self.device_type == "cpu":
            return False  # CPU device, never on GPU

        # Check model's actual device
        try:
            # SentenceTransformer wraps a transformers model
            model_device = str(self.model.device)
            return "cpu" not in model_device.lower()
        except Exception:
            # Fallback: assume still on original device
            return True

    def unload(self) -> None:
        """
        Move model to CPU and free GPU memory.

        Following Julie's pattern: instead of dropping the model entirely,
        we move it to CPU for faster reload (2-3s vs 6s from scratch).
        """
        logger = logging.getLogger("miller.embeddings")

        if self.device_type == "cpu":
            logger.debug("Model already on CPU, nothing to unload")
            return

        if not self.is_loaded_on_gpu():
            logger.debug("Model already unloaded from GPU")
            return

        logger.info(f"🗑️  Unloading embedding model from {self.device_type} to free GPU memory...")

        # Move model to CPU
        self.model = self.model.to("cpu")

        # Free GPU cache
        if self.device_type == "cuda":
            torch.cuda.empty_cache()
            logger.info("✅ GPU memory freed (CUDA cache cleared)")
        elif self.device_type == "directml":
            # DirectML doesn't have explicit cache clearing
            logger.info("✅ GPU memory freed (DirectML model moved to CPU)")
        elif self.device_type == "xpu":
            # Intel XPU cache clearing if available
            try:
                torch.xpu.empty_cache()
                logger.info("✅ GPU memory freed (XPU cache cleared)")
            except Exception:
                logger.info("✅ GPU memory freed (XPU model moved to CPU)")
        elif self.device_type == "mps":
            # MPS doesn't have explicit cache clearing in PyTorch
            logger.info("✅ GPU memory freed (MPS model moved to CPU)")

    def reload(self) -> None:
        """
        Reload model to GPU when needed (lazy reload).

        Called automatically by _ensure_loaded() before embedding operations.
        """
        logger = logging.getLogger("miller.embeddings")

        if self.device_type == "cpu":
            # CPU device, nothing to reload
            return

        if self.is_loaded_on_gpu():
            logger.debug("Model already loaded on GPU")
            return

        logger.info(f"🔄 Reloading embedding model to {self.device_type}...")

        # Move model back to original GPU device
        self.model = self.model.to(self._original_device)

        logger.info(f"✅ Model reloaded to {self.device_type}")

    def _ensure_loaded(self) -> None:
        """
        Ensure model is loaded on GPU before use (lazy reload if needed).

        Internal helper called by embed_query() and embed_batch().
        """
        if not self.is_loaded_on_gpu():
            self.reload()

        # Update last use timestamp (for auto-unload tracking)
        self._last_use_time = time.time()

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed a single query string.

        Args:
            query: Text to embed

        Returns:
            L2-normalized embedding vector (384 dimensions)
        """
        # Ensure model is loaded on GPU (lazy reload if needed)
        self._ensure_loaded()

        # Encode and normalize
        embedding = self.model.encode(
            query,
            normalize_embeddings=True,  # L2 normalize
            convert_to_numpy=True,
        )
        return embedding.astype(np.float32)

    def embed_batch(self, symbols: list[Any]) -> np.ndarray:
        """
        Embed a batch of symbols.

        Args:
            symbols: List of PySymbol objects from extraction

        Returns:
            Array of embeddings (N x 384), L2-normalized
        """
        if not symbols:
            # Return empty array with correct shape
            return np.empty((0, self.dimensions), dtype=np.float32)

        # Ensure model is loaded on GPU (lazy reload if needed)
        self._ensure_loaded()

        # Build text representations for each symbol
        texts = []
        for sym in symbols:
            # Combine name, signature, doc comment for rich representation
            parts = [sym.name]

            if hasattr(sym, "signature") and sym.signature:
                parts.append(sym.signature)

            if hasattr(sym, "doc_comment") and sym.doc_comment:
                parts.append(sym.doc_comment)

            text = " ".join(parts)
            texts.append(text)

        # Batch encode using dynamically calculated batch size
        # Batch size is calculated once during initialization based on GPU VRAM
        # using Julie's DirectML-safe formula: (VRAM_GB / 6.0) * 30
        # This prevents OOM crashes and GPU thrashing on memory-constrained GPUs
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,  # L2 normalize
            convert_to_numpy=True,
            show_progress_bar=False,  # Suppress progress bar for tests
            batch_size=self.batch_size,  # Use dynamically calculated batch size
        )

        return embeddings.astype(np.float32)
