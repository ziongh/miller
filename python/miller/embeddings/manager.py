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
    - Jina-code-embeddings-0.5b model (896 dimensions, 8192 token context)
    - Task-aware prefixes for optimal retrieval (NL→Code vs Code→Code)

    Environment Variables:
    - MILLER_EMBEDDING_MODEL: Override default model (for CPU/low-memory fallback)
    """

    # Default model: Jina-0.5B for deep semantic code understanding
    # Override via MILLER_EMBEDDING_MODEL env var for BGE fallback on CPU
    DEFAULT_MODEL = "jinaai/jina-code-embeddings-0.5b"

    def __init__(self, model_name: str = None, device: str = "auto"):
        """
        Initialize embedding model.

        Args:
            model_name: HuggingFace model identifier (default: Jina-0.5B)
                       Can be overridden via MILLER_EMBEDDING_MODEL env var
            device: Device to use ("auto", "cuda", "mps", "cpu")
        """
        logger = logging.getLogger("miller.embeddings")

        # Dynamic model selection: explicit param > env var > default
        # This allows CPU/low-memory users to fallback to BGE-small
        if model_name is None:
            model_name = os.getenv("MILLER_EMBEDDING_MODEL", self.DEFAULT_MODEL)

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

        # Model configuration for Jina (or any model requiring trust_remote_code)
        # Jina-0.5B requires trust_remote_code for its custom LastTokenPooling
        model_kwargs = {
            "trust_remote_code": True,
        }

        # FP16 optimization for CUDA: doubles throughput, halves VRAM usage
        # RTX 5070 Ti (16GB) can handle Jina-0.5B (~1GB in FP16) with large batches
        if self.device == "cuda":
            model_kwargs["torch_dtype"] = torch.float16
            logger.info("⚡ Using FP16 precision for CUDA (2x throughput)")

        with open(os.devnull, "w") as devnull, redirect_stdout(devnull), redirect_stderr(devnull):
            self.model = SentenceTransformer(
                model_name,
                device=self.device,
                model_kwargs=model_kwargs,
            )

        self.model_name = model_name

        # Set context length for Jina (paper evaluated at 8192 tokens)
        # Can be overridden via MILLER_MAX_SEQ_LENGTH env var to reduce VRAM usage
        # 4096 is usually sufficient for most code files while halving memory per item
        default_seq_length = 8192
        max_seq_length = int(os.getenv("MILLER_MAX_SEQ_LENGTH", str(default_seq_length)))
        self.model.max_seq_length = max_seq_length

        if max_seq_length != default_seq_length:
            logger.info(f"📏 Using custom max sequence length: {max_seq_length} (default: {default_seq_length})")

        # Get embedding dimension from model (896 for Jina, 384 for BGE)
        self.dimensions = self.model.get_sentence_embedding_dimension()

        # Jina paper requirement (Table 1): Task-specific prefixes
        # NL→Code (retrieval) vs Code→Code (similarity) use different prefixes
        self.prefixes = {
            "retrieval_query": "Find the most relevant code snippet given the following query:\n",
            "retrieval_doc": "Candidate code snippet:\n",
            "similarity_query": "Find an equivalent code snippet given the following code snippet:\n",
        }

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

    def _is_large_context_model(self) -> bool:
        """
        Check if current model has a large context window (>2048 tokens).

        Large context models like Jina-0.5B (8192 tokens) require significantly
        more VRAM per batch item compared to small context models like BGE-small (512 tokens).

        Returns:
            True if model has large context (requires conservative batching)
        """
        # Jina models have 8192 token context - 16x larger than BGE's 512
        if "jina" in self.model_name.lower():
            return True

        # Check actual max_seq_length if available
        if hasattr(self.model, "max_seq_length") and self.model.max_seq_length > 2048:
            return True

        return False

    def _calculate_batch_size_from_vram(self, vram_bytes: int) -> int:
        """
        Calculate optimal batch size based on GPU VRAM and model context size.

        Device-specific formulas adjusted for model context:
        - CUDA (large context like Jina-0.5B): (VRAM_GB * 8), clamped to [8, 128]
        - CUDA (small context like BGE): (VRAM_GB * 64), clamped to [64, 2048]
        - DirectML/Others: (VRAM_GB / 6.0) * 30, clamped to [25, 250] - conservative

        Large context models (8192 tokens) require ~16x more VRAM per item than
        small context models (512 tokens), hence the different formulas.

        CUDA rationale:
        - Dedicated NVIDIA GPUs have excellent memory management
        - Large models: 16GB → 128 batch size (prevents VRAM spillover)
        - Small models: 16GB → 1024 batch size (aggressive for throughput)

        DirectML rationale (unchanged):
        - Windows AMD/Intel GPUs are fragile under memory pressure
        - Previous formula tested stable on 6GB A1000

        Args:
            vram_bytes: Total GPU VRAM in bytes

        Returns:
            Optimal batch size
        """
        logger = logging.getLogger("miller.embeddings")

        vram_gb = vram_bytes / 1_073_741_824.0

        if self.device_type == "cuda":
            if self._is_large_context_model():
                # Conservative formula for large context models (Jina-0.5B: 8192 tokens)
                # Formula: VRAM_GB * 1, clamped to [8, 96]
                # 16GB → 16 batch size, 8GB → 8, 4GB → 4
                # This prevents VRAM spillover to shared memory (PCIe bottleneck)
                calculated = int(vram_gb * 1)
                batch_size = max(8, min(16, calculated)) + 1

                logger.info(
                    f"🚀 CUDA (Large Context): {vram_gb:.2f} GB VRAM → Batch size: {batch_size}"
                )
            else:
                # Aggressive formula for small context models (BGE-small: 512 tokens)
                # Formula: VRAM_GB * 64, clamped to [64, 2048]
                # 16GB → 1024 batch size, 8GB → 512, 4GB → 256
                calculated = int(vram_gb * 64)
                batch_size = max(64, min(2048, calculated))

                logger.info(
                    f"🚀 CUDA (Small Context): {vram_gb:.2f} GB VRAM → Batch size: {batch_size}"
                )

            return batch_size

        # Conservative formula for DirectML/MPS/XPU/Others
        # Background: DirectML on Windows is fragile under memory pressure
        # Formula: (VRAM_GB / 6.0) * 30, clamped to [25, 250]
        calculated = int((vram_gb / 6.0) * 30.0)
        batch_size = max(25, min(250, calculated))

        logger.info(
            f"📊 GPU Memory: {vram_gb:.2f} GB → Dynamic batch size: {batch_size} "
            f"(conservative formula)"
        )

        return batch_size

    def calculate_file_batch_size(self) -> int:
        """
        Calculate optimal file batch size based on device type and VRAM.

        File batch size determines how many files are processed before embedding.
        This affects memory pressure - too many files = too many symbols = OOM.

        Device-specific behavior:
        - DirectML (integrated GPU): Conservative (10-15), fragile under memory pressure
        - CPU: Moderate default (50), I/O bound anyway
        - CUDA/MPS/XPU (dedicated GPU): Scale with VRAM (25-100)

        Returns:
            Optimal file batch size (int)
        """
        # DirectML (Intel Arc integrated, AMD APUs) - very conservative
        # These have shared system memory and are fragile under pressure
        if self.device_type == "directml":
            return 15

        # CPU - moderate default, mostly I/O bound anyway
        if self.device_type == "cpu":
            return 50

        # Dedicated GPUs (CUDA, MPS, XPU) - scale with VRAM
        known_gpu_devices = {"cuda", "mps", "xpu"}
        if self.device_type not in known_gpu_devices:
            # Unknown device type - use conservative fallback
            return 30

        vram_bytes = self._detect_gpu_memory_bytes()

        if vram_bytes is None or vram_bytes == 0:
            # VRAM detection failed - use conservative fallback
            return 30

        vram_gb = vram_bytes / 1_073_741_824.0

        # Formula: scale from 25 (2GB) to 100 (16GB+)
        # Linear interpolation: file_batch = 25 + (vram_gb - 2) * 5
        # Clamped to [25, 100]
        calculated = int(25 + (vram_gb - 2) * 5)
        file_batch = max(25, min(100, calculated))

        return file_batch

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

    def embed_query(self, query: str, task: str = "retrieval") -> np.ndarray:
        """
        Embed a single query string with task-appropriate prefix.

        Jina paper requirement: Different tasks use different prefixes for
        optimal retrieval quality.

        Args:
            query: Text to embed
            task: "retrieval" (NL→Code search) or "similarity" (Code→Code comparison)

        Returns:
            L2-normalized embedding vector (dimensions depend on model)
        """
        # Ensure model is loaded on GPU (lazy reload if needed)
        self._ensure_loaded()

        # Apply task-specific prefix (Jina paper Table 1 requirement)
        if task == "similarity":
            prefix = self.prefixes.get("similarity_query", "")
        else:
            prefix = self.prefixes.get("retrieval_query", "")

        full_query = f"{prefix}{query}" if prefix else query

        # Encode and normalize
        embedding = self.model.encode(
            full_query,
            normalize_embeddings=True,  # L2 normalize
            convert_to_numpy=True,
        )
        return embedding.astype(np.float32)

    def embed_batch(self, symbols: list[Any], is_document: bool = True) -> np.ndarray:
        """
        Embed a batch of symbols with code-like formatting.

        Jina-0.5B is an autoregressive model trained on code. We format input
        as pseudo-code (docstring as comment + signature) for better semantic
        understanding compared to simple string concatenation.

        Args:
            symbols: List of PySymbol objects from extraction
            is_document: If True, apply document prefix for indexing (default: True)

        Returns:
            Array of embeddings (N x dimensions), L2-normalized
        """
        if not symbols:
            # Return empty array with correct shape
            return np.empty((0, self.dimensions), dtype=np.float32)

        # Ensure model is loaded on GPU (lazy reload if needed)
        self._ensure_loaded()

        # Build pseudo-code representations for each symbol
        # This format works better for autoregressive models like Jina
        texts = []
        for sym in symbols:
            parts = []

            # 1. Docstring as comment (if available) - helps semantic understanding
            if hasattr(sym, "doc_comment") and sym.doc_comment:
                parts.append(f"/* {sym.doc_comment} */")

            # 2. Signature (most code-like) or fallback to kind + name
            if hasattr(sym, "signature") and sym.signature:
                parts.append(sym.signature)
            else:
                # Fallback: simple declaration format
                kind = getattr(sym, "kind", "symbol").lower()
                parts.append(f"{kind} {sym.name}")

            text = "\n".join(parts)
            texts.append(text)

        # Apply document prefix for indexing (Jina paper requirement)
        if is_document:
            prefix = self.prefixes.get("retrieval_doc", "")
            if prefix:
                texts = [f"{prefix}{t}" for t in texts]

        # Batch encode using dynamically calculated batch size
        # Batch size is calculated once during initialization based on GPU VRAM
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,  # L2 normalize
            convert_to_numpy=True,
            show_progress_bar=False,  # Suppress progress bar for tests
            batch_size=self.batch_size,  # Use dynamically calculated batch size
        )

        return embeddings.astype(np.float32)

    def embed_texts(self, texts: list[str], is_document: bool = True) -> np.ndarray:
        """
        Embed a batch of raw text strings.

        Used for file-level indexing where we don't have symbol objects,
        just raw file content.

        Args:
            texts: List of text strings to embed
            is_document: If True, apply document prefix for indexing (default: True)

        Returns:
            Array of embeddings (N x dimensions), L2-normalized
        """
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)

        # Ensure model is loaded on GPU (lazy reload if needed)
        self._ensure_loaded()

        # Apply document prefix for indexing (Jina paper requirement)
        if is_document:
            prefix = self.prefixes.get("retrieval_doc", "")
            if prefix:
                texts = [f"{prefix}{t}" for t in texts]

        # Batch encode
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=self.batch_size,
        )

        return embeddings.astype(np.float32)
