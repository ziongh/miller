"""
Embedding generation with sentence-transformers.

Manages GPU detection, model loading, and batch embedding generation.
Uses L2 normalization for cosine similarity in vector search.
"""

import logging
import os
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import numpy as np
import torch
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

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed a single query string.

        Args:
            query: Text to embed

        Returns:
            L2-normalized embedding vector (384 dimensions)
        """
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

        # Batch encode with optimized batch size for GPU throughput
        # Larger batches = better GPU utilization (amortize overhead)
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,  # L2 normalize
            convert_to_numpy=True,
            show_progress_bar=False,  # Suppress progress bar for tests
            batch_size=256,  # Optimized for GPU (32 default is too small)
        )

        return embeddings.astype(np.float32)
