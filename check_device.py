#!/usr/bin/env python3
"""
Quick diagnostic to check GPU/CPU device availability for embeddings.

Run this to verify hardware acceleration is working before starting Miller.
"""

import torch
import sys

print("=" * 60)
print("Miller Hardware Acceleration Diagnostic")
print("=" * 60)
print()

# Check PyTorch version
print(f"PyTorch version: {torch.__version__}")
print()

# Check CUDA (NVIDIA GPUs)
print("🔍 Checking NVIDIA CUDA:")
if torch.cuda.is_available():
    print(f"  ✅ CUDA available: {torch.version.cuda}")
    print(f"  🎮 GPU count: {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        print(f"  📊 GPU {i}: {torch.cuda.get_device_name(i)}")
        props = torch.cuda.get_device_properties(i)
        print(f"     Memory: {props.total_memory / 1024**3:.1f} GB")
        print(f"     Compute Capability: {props.major}.{props.minor}")
else:
    print("  ❌ CUDA not available")
print()

# Check MPS (Apple Silicon)
print("🔍 Checking Apple Silicon MPS:")
if hasattr(torch.backends, 'mps'):
    if torch.backends.mps.is_available():
        print("  ✅ MPS (Metal Performance Shaders) available")
        print("  🍎 Apple Silicon GPU acceleration enabled")
    else:
        print("  ❌ MPS not available (requires macOS 12.3+ and Apple Silicon)")
else:
    print("  ❌ MPS not supported in this PyTorch version")
print()

# Check DirectML (Windows AMD/Intel GPUs)
print("🔍 Checking DirectML (Windows AMD/Intel):")
try:
    import torch_directml
    if torch_directml.is_available():
        print("  ✅ DirectML available")
        print("  🪟 Windows GPU acceleration enabled (AMD/Intel)")
        device_count = torch_directml.device_count()
        print(f"  📊 DirectML devices: {device_count}")
        for i in range(device_count):
            print(f"     Device {i}: {torch_directml.device_name(i)}")
        directml_available = True
    else:
        print("  ❌ DirectML installed but not available")
        directml_available = False
except ImportError:
    print("  ❌ DirectML not installed")
    print("     Install: pip install torch-directml")
    directml_available = False
print()

# Determine what Miller will use
print("🎯 Miller will use:")
if torch.cuda.is_available():
    device = "cuda"
    print(f"  🚀 CUDA GPU: {torch.cuda.get_device_name(0)}")
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    device = "mps"
    print("  🍎 Apple Silicon MPS")
elif directml_available:
    device = "dml"
    print("  🪟 DirectML (Windows AMD/Intel GPU)")
else:
    device = "cpu"
    print("  💻 CPU (no GPU acceleration)")
print()

# Quick speed test
print("⚡ Quick benchmark:")
from time import time

# Create random tensor
x = torch.randn(1000, 384)

# CPU test
start = time()
_ = torch.mm(x, x.T)
cpu_time = (time() - start) * 1000
print(f"  CPU: {cpu_time:.2f}ms")

# GPU test (if available)
if device in ["cuda", "mps", "dml"]:
    try:
        if device == "dml":
            import torch_directml
            dml_device = torch_directml.device()
            x_gpu = x.to(dml_device)
        else:
            x_gpu = x.to(device)

        # Warmup
        _ = torch.mm(x_gpu, x_gpu.T)
        if device == "cuda":
            torch.cuda.synchronize()

        start = time()
        _ = torch.mm(x_gpu, x_gpu.T)
        if device == "cuda":
            torch.cuda.synchronize()
        gpu_time = (time() - start) * 1000

        speedup = cpu_time / gpu_time
        print(f"  {device.upper()}: {gpu_time:.2f}ms ({speedup:.1f}x faster)")
    except Exception as e:
        print(f"  {device.upper()}: Benchmark failed - {e}")
print()

print("=" * 60)
print("✅ Diagnostic complete!")
print()

if device == "cpu":
    print("⚠️  WARNING: No GPU detected!")
    print("   Embeddings will run on CPU (10-50x slower)")
    print()
    print("   For faster indexing:")
    print("   - macOS: Use Apple Silicon Mac (M1/M2/M3/M4)")
    print("   - Windows/Linux (NVIDIA): Install CUDA toolkit")
    print("   - Windows (AMD/Intel): Install torch-directml")
    print("     pip uninstall torch")
    print("     pip install torch-directml")
else:
    print(f"✅ GPU acceleration enabled ({device.upper()})")
    print("   Embeddings will run on GPU (10-50x faster than CPU)")
    if device == "dml":
        print()
        print("   ⚠️  DirectML is experimental - may have compatibility issues")
        print("   If you encounter errors, switch back to CPU:")
        print("     pip uninstall torch-directml")
        print("     pip install torch")

print("=" * 60)
