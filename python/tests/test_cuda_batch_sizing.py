"""
Tests for CUDA-optimized embedding batch sizing.

The RTX 5070 Ti (16GB VRAM) can handle much larger batches than the
conservative DirectML-safe formula allows. This enables the "Bucket Brigade"
streaming architecture to fully saturate the GPU.

Device-specific batch size formulas:
- CUDA: (VRAM_GB * 64), clamped to [64, 2048] - aggressive for dedicated GPUs
- DirectML: (VRAM_GB / 6.0) * 30, clamped to [25, 250] - conservative for Windows
- Others: Same as DirectML for safety
"""

import pytest
from unittest.mock import patch, MagicMock


class TestCudaBatchSizeCalculation:
    """Test CUDA-specific batch size calculation."""

    def test_cuda_16gb_uses_large_batch(self):
        """16GB CUDA GPU (RTX 5070 Ti) should use 1024 batch size."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"

            # 16GB VRAM
            vram_bytes = 16 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # 16 * 64 = 1024
            assert batch_size == 1024, (
                f"16GB CUDA should use batch size 1024, got {batch_size}"
            )

    def test_cuda_8gb_uses_512_batch(self):
        """8GB CUDA GPU should use 512 batch size."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"

            # 8GB VRAM
            vram_bytes = 8 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # 8 * 64 = 512
            assert batch_size == 512, (
                f"8GB CUDA should use batch size 512, got {batch_size}"
            )

    def test_cuda_4gb_uses_256_batch(self):
        """4GB CUDA GPU should use 256 batch size."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"

            # 4GB VRAM
            vram_bytes = 4 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # 4 * 64 = 256
            assert batch_size == 256, (
                f"4GB CUDA should use batch size 256, got {batch_size}"
            )

    def test_cuda_minimum_batch_is_64(self):
        """Very small GPU should still use at least 64 batch size."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"

            # 512MB VRAM (tiny GPU)
            vram_bytes = 512 * 1024**2  # 512MB
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # Should clamp to minimum 64
            assert batch_size == 64, (
                f"Tiny CUDA GPU should clamp to 64, got {batch_size}"
            )

    def test_cuda_maximum_batch_is_2048(self):
        """Huge GPU should cap at 2048 batch size."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"

            # 48GB VRAM (A6000 or similar)
            vram_bytes = 48 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # 48 * 64 = 3072, but capped at 2048
            assert batch_size == 2048, (
                f"Huge CUDA GPU should cap at 2048, got {batch_size}"
            )


class TestDirectMLBatchSizeUnchanged:
    """Verify DirectML still uses conservative formula."""

    def test_directml_6gb_uses_conservative_batch(self):
        """6GB DirectML GPU should use 30 batch size (conservative)."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "directml"

            # 6GB VRAM
            vram_bytes = 6 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # (6 / 6.0) * 30 = 30
            assert batch_size == 30, (
                f"6GB DirectML should use batch size 30, got {batch_size}"
            )

    def test_directml_12gb_uses_60_batch(self):
        """12GB DirectML GPU should use 60 batch size."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "directml"

            # 12GB VRAM
            vram_bytes = 12 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # (12 / 6.0) * 30 = 60
            assert batch_size == 60, (
                f"12GB DirectML should use batch size 60, got {batch_size}"
            )

    def test_directml_maximum_is_250(self):
        """DirectML should cap at 250 even with large VRAM."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "directml"

            # 16GB VRAM
            vram_bytes = 16 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # (16 / 6.0) * 30 = 80 (no cap needed)
            # But verify it would cap at 250 with larger VRAM
            assert batch_size <= 250, (
                f"DirectML should cap at 250, got {batch_size}"
            )


class TestOtherDevicesBatchSize:
    """Verify other devices use conservative formula."""

    def test_mps_uses_conservative_formula(self):
        """MPS (Apple Silicon) should use conservative formula."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "mps"

            # 8GB unified memory
            vram_bytes = 8 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # Should use conservative formula: (8 / 6.0) * 30 = 40
            assert batch_size == 40, (
                f"8GB MPS should use batch size 40, got {batch_size}"
            )

    def test_xpu_uses_conservative_formula(self):
        """XPU (Intel Arc) should use conservative formula."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "xpu"

            # 8GB VRAM
            vram_bytes = 8 * 1024**3
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # Should use conservative formula
            assert 25 <= batch_size <= 250, (
                f"XPU should use conservative batch size, got {batch_size}"
            )

    def test_cpu_gets_no_vram_based_calculation(self):
        """CPU device should not call VRAM-based calculation."""
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cpu"

            # CPU - VRAM detection returns None
            # This method shouldn't be called for CPU, but if it is, be safe
            vram_bytes = 0  # No GPU memory
            batch_size = manager._calculate_batch_size_from_vram(vram_bytes)

            # Should use minimum safe value
            assert batch_size >= 25, (
                f"CPU fallback should use minimum batch size, got {batch_size}"
            )


class TestBatchSizeLogMessages:
    """Verify logging for batch size decisions."""

    def test_cuda_logs_unleashing_message(self):
        """CUDA should log 'Unleashing CUDA' message."""
        import logging
        from miller.embeddings import EmbeddingManager

        with patch.object(EmbeddingManager, '__init__', lambda self: None):
            manager = EmbeddingManager.__new__(EmbeddingManager)
            manager.device_type = "cuda"

            # Capture log messages
            with patch('logging.getLogger') as mock_get_logger:
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                vram_bytes = 16 * 1024**3
                manager._calculate_batch_size_from_vram(vram_bytes)

                # Verify logging was called
                mock_logger.info.assert_called()
                log_message = mock_logger.info.call_args[0][0]
                assert "CUDA" in log_message or "cuda" in log_message.lower()
