"""
Tests for VRAM-based file batch sizing.

File batch size determines how many files are processed before embedding.
This affects memory pressure - too many files = too many symbols = OOM.

Device-specific behavior:
- DirectML (integrated GPU): Conservative (10-20), fragile under memory pressure
- CUDA/MPS (dedicated GPU): Scale with VRAM (25-100)
- CPU: Moderate default (50), I/O bound anyway
"""

import pytest
from unittest.mock import patch, MagicMock


class TestFileBatchSizeCalculation:
    """Test calculate_file_batch_size method on EmbeddingManager."""

    def test_cpu_returns_moderate_default(self):
        """CPU should use moderate batch size since it's I/O bound."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cpu"
            manager.batch_size = 50  # embedding batch size

            file_batch = manager.calculate_file_batch_size()

            assert file_batch == 50, "CPU should use moderate file batch size"

    def test_directml_is_conservative(self):
        """DirectML (integrated GPU) should use small batches to prevent OOM."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "directml"
            manager.batch_size = 32  # embedding batch size

            file_batch = manager.calculate_file_batch_size()

            # DirectML should be conservative: 10-20 range
            assert 10 <= file_batch <= 20, (
                f"DirectML should use conservative file batch (10-20), got {file_batch}"
            )

    def test_cuda_small_gpu_moderate_batch(self):
        """CUDA with small VRAM (4GB) should use moderate batch."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"
            manager.batch_size = 25  # small GPU embedding batch
            manager._detect_gpu_memory_bytes = lambda: 4 * 1024**3  # 4GB

            file_batch = manager.calculate_file_batch_size()

            # Small GPU: 25-40 range
            assert 25 <= file_batch <= 40, (
                f"4GB CUDA should use moderate file batch (25-40), got {file_batch}"
            )

    def test_cuda_large_gpu_larger_batch(self):
        """CUDA with large VRAM (12GB) should use larger batch."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"
            manager.batch_size = 60  # larger GPU embedding batch
            manager._detect_gpu_memory_bytes = lambda: 12 * 1024**3  # 12GB

            file_batch = manager.calculate_file_batch_size()

            # Large GPU: 50-100 range
            assert 50 <= file_batch <= 100, (
                f"12GB CUDA should use larger file batch (50-100), got {file_batch}"
            )

    def test_cuda_huge_gpu_capped_batch(self):
        """CUDA with huge VRAM (24GB) should cap at reasonable max."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"
            manager.batch_size = 120  # huge GPU embedding batch
            manager._detect_gpu_memory_bytes = lambda: 24 * 1024**3  # 24GB

            file_batch = manager.calculate_file_batch_size()

            # Should cap at 100 to avoid diminishing returns / I/O bottleneck
            assert file_batch <= 100, (
                f"File batch should cap at 100 even for huge GPUs, got {file_batch}"
            )

    def test_mps_apple_silicon_scales_with_vram(self):
        """MPS (Apple Silicon) should scale similarly to CUDA."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "mps"
            manager.batch_size = 40  # ~8GB unified memory
            manager._detect_gpu_memory_bytes = lambda: 8 * 1024**3  # 8GB

            file_batch = manager.calculate_file_batch_size()

            # MPS should behave like CUDA: 35-60 for 8GB
            assert 35 <= file_batch <= 60, (
                f"8GB MPS should use moderate-large file batch (35-60), got {file_batch}"
            )

    def test_xpu_intel_arc_dedicated_scales(self):
        """Intel Arc dedicated GPU (XPU) should scale with VRAM."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "xpu"
            manager.batch_size = 50  # ~8GB VRAM
            manager._detect_gpu_memory_bytes = lambda: 8 * 1024**3  # 8GB

            file_batch = manager.calculate_file_batch_size()

            # XPU dedicated should behave like CUDA
            assert 35 <= file_batch <= 60, (
                f"8GB XPU should use moderate-large file batch (35-60), got {file_batch}"
            )


class TestFileBatchSizeEdgeCases:
    """Edge cases and error handling for file batch sizing."""

    def test_vram_detection_fails_uses_fallback(self):
        """If VRAM detection fails, use safe fallback based on device type."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"
            manager.batch_size = 50
            manager._detect_gpu_memory_bytes = lambda: None  # Detection failed

            file_batch = manager.calculate_file_batch_size()

            # Should use conservative fallback, not crash
            assert 25 <= file_batch <= 50, (
                f"VRAM detection failure should use conservative fallback, got {file_batch}"
            )

    def test_zero_vram_uses_minimum(self):
        """Zero VRAM (impossible but defensive) should use minimum."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"
            manager.batch_size = 25
            manager._detect_gpu_memory_bytes = lambda: 0

            file_batch = manager.calculate_file_batch_size()

            # Should use minimum, not crash or return 0
            assert file_batch >= 10, (
                f"Zero VRAM should use minimum file batch, got {file_batch}"
            )

    def test_unknown_device_type_uses_conservative(self):
        """Unknown device type should use conservative default."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "unknown_future_device"
            manager.batch_size = 50
            manager._detect_gpu_memory_bytes = lambda: 8 * 1024**3

            file_batch = manager.calculate_file_batch_size()

            # Unknown device: be conservative
            assert 25 <= file_batch <= 50, (
                f"Unknown device should use conservative batch, got {file_batch}"
            )


class TestFileBatchSizeIntegration:
    """Integration tests with real EmbeddingManager (requires model)."""

    @pytest.mark.slow
    def test_real_manager_has_file_batch_method(self):
        """Real EmbeddingManager should have calculate_file_batch_size method."""
        from miller.embeddings import EmbeddingManager

        manager = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")

        # Method should exist and return reasonable value
        assert hasattr(manager, 'calculate_file_batch_size')
        file_batch = manager.calculate_file_batch_size()
        assert isinstance(file_batch, int)
        assert 10 <= file_batch <= 100

    @pytest.mark.slow
    def test_file_batch_consistent_with_device(self):
        """File batch should be consistent with detected device type."""
        from miller.embeddings import EmbeddingManager

        manager = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        file_batch = manager.calculate_file_batch_size()

        if manager.device_type == "directml":
            assert file_batch <= 20, "DirectML should use small file batches"
        elif manager.device_type == "cpu":
            assert file_batch == 50, "CPU should use moderate file batches"
        else:
            # CUDA, MPS, XPU - scaled by VRAM
            assert file_batch >= 25, "GPU should use at least 25 file batch"
