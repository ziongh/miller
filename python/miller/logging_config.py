"""
Logging configuration for Miller MCP server.

CRITICAL: MCP servers MUST NOT log to stdout/stderr!
stdout is reserved for JSON-RPC messages. Any text output will break
the MCP protocol and cause client disconnects.

All logs go to file: .miller/logs/miller-YYYY-MM-DD.log (new file each day)
"""

import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    backup_count: int = 30,  # Keep 30 days of logs
) -> logging.Logger:
    """
    Set up file-based logging for Miller with daily rotation.

    Args:
        log_dir: Directory for log files (default: .miller/logs)
        level: Logging level (default: INFO)
        backup_count: Number of daily backup files to keep (default: 30 days)

    Returns:
        Configured logger instance
    """
    # Default log directory
    if log_dir is None:
        log_dir = Path.cwd() / ".miller" / "logs"

    # Ensure log directory exists
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create logger
    logger = logging.getLogger("miller")
    logger.setLevel(level)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    # Create daily rotating file handler
    # Log filename format: miller-YYYY-MM-DD.log
    log_file = log_dir / f"miller-{datetime.now().strftime('%Y-%m-%d')}.log"
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when="midnight",  # Rotate at midnight
        interval=1,  # Every 1 day
        backupCount=backup_count,
        encoding="utf-8",
    )

    # Flush immediately after each write (ensures errors are visible immediately)
    # Without this, Python may buffer log writes and errors might not appear
    # in the log file until much later (or never, if the process crashes)
    class FlushingHandler(logging.handlers.TimedRotatingFileHandler):
        """Handler that flushes after every emit for immediate visibility."""

        def emit(self, record):
            super().emit(record)
            self.flush()

    # Replace with flushing version
    file_handler.close()
    file_handler = FlushingHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )

    # Format with timestamp, level, module, and message
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(file_handler)

    # Log initial message
    logger.info("=" * 60)
    logger.info("Miller MCP Server - Logging Initialized")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Log level: {logging.getLevelName(level)}")
    logger.info(f"Rotation: Daily at midnight, keeping {backup_count} days")
    logger.info("=" * 60)

    return logger


def get_logger(name: str = "miller") -> logging.Logger:
    """
    Get Miller logger instance.

    Args:
        name: Logger name (default: "miller")

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
