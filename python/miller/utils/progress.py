"""
Progress tracking for Miller operations.

Provides two modes:
1. Log-based (default): Emits log entries at percentage intervals for file-based logging
2. Visual (console): Dynamic tqdm-style progress bar on stderr for HTTP/console mode

The tracker automatically selects the appropriate mode based on:
- console_mode flag (set by HTTP server)
- Whether stderr is connected to a TTY (terminal)
"""

import logging
import sys
import time
from typing import Optional

logger = logging.getLogger("miller.progress")


class ProgressTracker:
    """
    Context-aware progress tracker for long-running operations.

    Supports two output modes:
    - Visual mode: Dynamic progress bar on stderr (HTTP mode + TTY)
    - Log mode: Periodic log entries at 10% intervals (safe for MCP/files)

    Example:
        tracker = ProgressTracker(total=1000, desc="Indexing", console_mode=True)
        for batch in batches:
            process(batch)
            tracker.update(len(batch))
    """

    def __init__(
        self,
        total: int,
        desc: str = "Processing",
        console_mode: bool = False,
        log_interval_percent: float = 10.0,
        log_interval_seconds: float = 30.0,
    ):
        """
        Initialize progress tracker.

        Args:
            total: Total number of items to process
            desc: Description prefix for progress output
            console_mode: If True and stderr is TTY, use visual progress bar
            log_interval_percent: Minimum percentage change before logging (log mode)
            log_interval_seconds: Maximum seconds between log entries (log mode)
        """
        self.total = total
        self.current = 0
        self.desc = desc
        self.start_time = time.time()
        self.last_log_time = 0.0
        self.last_percentage = 0.0
        self.log_interval_percent = log_interval_percent
        self.log_interval_seconds = log_interval_seconds

        # Only use visual bar if:
        # 1. Explicitly enabled (HTTP mode)
        # 2. stderr is connected to a TTY (interactive terminal)
        self.visual_mode = console_mode and sys.stderr.isatty()
        self._bar_length = 30
        self._finished = False

    def update(self, n: int = 1) -> None:
        """
        Update progress by n items.

        Args:
            n: Number of items completed in this update
        """
        self.current += n
        self._emit()

    def _format_time(self, seconds: float) -> str:
        """Format seconds into human-readable string (e.g., '1m 30s')."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"

    def _emit(self) -> None:
        """Emit progress update (visual bar or log entry based on mode)."""
        if self._finished:
            return

        # Calculate progress metrics
        percent = 0.0 if self.total == 0 else (self.current / self.total) * 100
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        remaining_items = self.total - self.current
        eta = remaining_items / rate if rate > 0 else 0

        is_complete = self.current >= self.total

        if self.visual_mode:
            self._emit_visual(percent, rate, eta, is_complete)
        else:
            self._emit_log(percent, eta, is_complete)

        if is_complete:
            self._finished = True

    def _emit_visual(
        self, percent: float, rate: float, eta: float, is_complete: bool
    ) -> None:
        """
        Emit visual progress bar to stderr.

        Output format: Indexing: [=======>   ] 45% (450/1000) 150.0it/s ETA: 4s
        """
        filled_len = (
            int(self._bar_length * self.current // self.total) if self.total else 0
        )
        bar = "=" * filled_len + "-" * (self._bar_length - filled_len)

        # \r to overwrite line, writing to stderr to avoid breaking stdout
        eta_str = self._format_time(eta)
        sys.stderr.write(
            f"\r{self.desc}: [{bar}] {percent:.0f}% "
            f"({self.current}/{self.total}) {rate:.1f}it/s ETA: {eta_str}"
        )
        sys.stderr.flush()

        # Newline when complete to preserve the final state
        if is_complete:
            sys.stderr.write("\n")
            sys.stderr.flush()

    def _emit_log(self, percent: float, eta: float, is_complete: bool) -> None:
        """
        Emit log-based progress at intervals.

        Logs every log_interval_percent% or log_interval_seconds to avoid spam.
        """
        now = time.time()

        # Determine if we should log
        percent_threshold_met = (percent - self.last_percentage) >= self.log_interval_percent
        time_threshold_met = (now - self.last_log_time) > self.log_interval_seconds

        should_log = (
            (percent_threshold_met or time_threshold_met or is_complete)
            and self.current > 0
        )

        if should_log:
            eta_str = self._format_time(eta)
            if is_complete:
                elapsed = time.time() - self.start_time
                elapsed_str = self._format_time(elapsed)
                logger.info(
                    f"{self.desc}: 100% complete ({self.current}/{self.total} files) "
                    f"in {elapsed_str}"
                )
            else:
                logger.info(
                    f"{self.desc}: {percent:.0f}% complete "
                    f"({self.current}/{self.total} files). ETA: {eta_str}"
                )

            self.last_percentage = percent
            self.last_log_time = now

    def finish(self) -> None:
        """
        Force completion of progress tracking.

        Call this if you exit early or want to ensure final state is logged.
        """
        if not self._finished:
            # Set to total to trigger completion logic
            self.current = self.total
            self._emit()


class NoOpProgressTracker:
    """
    No-operation progress tracker for when progress tracking is disabled.

    Useful as a drop-in replacement when you want to skip progress tracking
    without changing calling code.
    """

    def __init__(self, *args, **kwargs):
        pass

    def update(self, n: int = 1) -> None:
        pass

    def finish(self) -> None:
        pass
