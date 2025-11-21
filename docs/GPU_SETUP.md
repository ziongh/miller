# GPU Setup for Miller (PyTorch)

Miller uses PyTorch for embeddings. **GPU acceleration is 10-50x faster than CPU** for embedding generation.

## Quick Start by Platform

### macOS (Apple Silicon)
```bash
# Standard PyPI version includes MPS (Metal Performance Shaders) support
uv pip install torch

# Miller auto-detects MPS and uses GPU acceleration
```

### Windows/Linux with NVIDIA GPU
```bash
# Use uv (faster, better dependency resolution)
uv pip install torch --index-url https://download.pytorch.org/whl/cu130

# This installs: torch 2.9.1+cu130 (CUDA 13.0 support)
# Works with: Python 3.10-3.14, NVIDIA drivers 527.41+
# Supports: RTX 20/30/40/50 series, A100, H100, etc.
```

### Linux with AMD GPU
```bash
# ROCm support for AMD GPUs (Radeon RX 6000/7000 series, Instinct, etc.)
uv pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
```

### Linux/Windows with Intel Arc GPU
```bash
# Intel XPU support for Arc A-Series, Data Center GPU Max/Flex
pip install torch --index-url https://download.pytorch.org/whl/nightly/xpu
# Note: Requires Intel GPU drivers installed first
```

---

## Verification

After installation, verify GPU is detected:

```bash
# Quick check
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# Full check
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# Miller-specific check
python -c "from miller.embeddings import EmbeddingManager; mgr = EmbeddingManager(); print(f'Miller using: {mgr.device}')"
```

### Expected Output by Platform

**NVIDIA GPU (CUDA):**
- `CUDA available: True`
- `GPU: NVIDIA GeForce RTX 4080`
- `Miller using: cuda`

**AMD GPU (ROCm on Linux):**
- `CUDA available: True` (ROCm uses CUDA API)
- `GPU: AMD Radeon RX 7900 XTX`
- `Miller using: cuda` (with ROCm backend)

**Intel Arc (XPU):**
- `XPU available: True`
- `GPU: Intel Arc A770`
- `Miller using: xpu`

**Apple Silicon (MPS):**
- `MPS available: True`
- `Miller using: mps`

---

## Troubleshooting

### Problem: "CUDA available: False"

**1. Wrong PyTorch version installed (CPU-only):**
```bash
# Check installed version
python -c "import torch; print(torch.__version__)"

# If it shows "2.9.1+cpu", you have CPU-only version
# Uninstall and reinstall with CUDA:
uv pip uninstall torch
uv pip install torch --index-url https://download.pytorch.org/whl/cu130
```

**2. NVIDIA drivers not installed:**
- Windows: Install from https://www.nvidia.com/Download/index.aspx
- Linux: `sudo apt install nvidia-driver-535` (or latest)
- Verify: `nvidia-smi` should show your GPU

**3. Python version mismatch:**
- CUDA 13.0 index: Python 3.10-3.14 supported
- CUDA 12.4 index: Python 3.9-3.13 supported
- CUDA 12.1 index: Python 3.9-3.12 supported

### Problem: "No module named 'torch'"

Miller's `pyproject.toml` lists `torch>=2.0` as a dependency, but **this installs CPU-only version by default**. You must manually install the GPU-enabled version using the commands above.

### Problem: AMD GPU on Linux not detected

**1. ROCm not installed:**
```bash
# Verify ROCm PyTorch is installed
python -c "import torch; print(hasattr(torch.version, 'hip'))"

# Should print "True" - if "False", reinstall with ROCm:
pip uninstall torch
uv pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
```

**2. ROCm drivers not installed:**
- Install AMD GPU drivers and ROCm runtime
- Check: `rocm-smi` should show your GPU
- See: https://rocm.docs.amd.com/projects/install-on-linux/

### Problem: Intel Arc GPU not detected

**1. XPU PyTorch not installed:**
```bash
# Verify XPU support
python -c "import torch; print(hasattr(torch, 'xpu'))"

# Should print "True" - if "False", install XPU version:
pip uninstall torch
pip install torch --index-url https://download.pytorch.org/whl/nightly/xpu
```

**2. Intel GPU drivers not installed:**
- Linux: Install Intel GPU drivers + compute runtime
- Windows: Install latest Intel Arc drivers
- Verify: GPU should appear in device manager/lspci

---

## DirectML (Windows Fallback)

If you have an AMD or Intel GPU on Windows, you can use DirectML:

```bash
uv pip install torch-directml
```

Miller will auto-detect DirectML and use it for GPU acceleration (though CUDA on NVIDIA is faster).

---

## Performance Impact

**Embedding generation speed (100 symbols):**

| Device | Speed | Notes |
|--------|-------|-------|
| CPU | ~8-10 seconds | Slowest fallback |
| GPU (CUDA - NVIDIA) | ~0.5-1 second | Fastest, most mature |
| GPU (ROCm - AMD) | ~0.7-1.5 seconds | Native AMD |
| GPU (XPU - Intel Arc) | ~1-2 seconds | Native Intel |
| GPU (MPS - Apple Silicon) | ~1-2 seconds | macOS only |
| GPU (DirectML - Windows) | ~2-3 seconds | Universal fallback |

**Device Priority (Auto-Detection Order):**
1. CUDA (NVIDIA)
2. ROCm (AMD on Linux)
3. XPU (Intel Arc)
4. MPS (Apple Silicon)
5. DirectML (Windows AMD/Intel fallback)
6. CPU

**On large codebases (1000+ files), GPU acceleration saves minutes to hours.**

---

## CUDA Version Selection

**Why CUDA 13.0 (`cu130`) is recommended:**
- PyTorch 2.9.1 added CUDA 13.0 support
- CUDA 12.x indexes (`cu121`, `cu124`) only have wheels up to Python 3.13
- CUDA 13.0 index has Python 3.14 wheels
- CUDA is backward compatible (cu130 binaries work with CUDA 12.x/13.x drivers)

**Alternative CUDA versions:**
```bash
uv pip install torch --index-url https://download.pytorch.org/whl/cu130  # CUDA 13.0 (recommended)
uv pip install torch --index-url https://download.pytorch.org/whl/cu124  # CUDA 12.4
uv pip install torch --index-url https://download.pytorch.org/whl/cu121  # CUDA 12.1
```
