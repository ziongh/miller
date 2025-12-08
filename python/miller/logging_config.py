"""
Logging configuration for Miller MCP server.

CRITICAL: MCP servers MUST NOT log to stdout/stderr in stdio mode!
stdout is reserved for JSON-RPC messages. Any text output will break
the MCP protocol and cause client disconnects.

HTTP mode is different - we can safely log to stderr since HTTP uses
its own transport, not stdout/stdin.

All logs go to file: .miller/logs/miller-YYYY-MM-DD.log (new file each day)
Console logging can be enabled for HTTP mode via console=True parameter.
"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    backup_count: int = 30,  # Keep 30 days of logs
    console: bool = False,  # Enable console logging (safe for HTTP mode)
) -> logging.Logger:
    """
    Set up file-based logging for Miller with daily rotation.

    Args:
        log_dir: Directory for log files (default: .miller/logs)
        level: Logging level (default: INFO)
        backup_count: Number of daily backup files to keep (default: 30 days)
        console: If True, also log to stderr (useful for HTTP mode)

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

    # Check existing handlers to avoid duplicates
    has_file_handler = any(
        isinstance(h, logging.handlers.TimedRotatingFileHandler)
        for h in logger.handlers
    )
    has_console_handler = any(
        isinstance(h, logging.StreamHandler) and h.stream == sys.stderr
        for h in logger.handlers
    )

    # If file handler exists and no console requested, nothing to do
    if has_file_handler and (not console or has_console_handler):
        return logger

    # Format with timestamp, level, module, and message
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Add file handler if missing
    if not has_file_handler:
        log_file = log_dir / f"miller-{datetime.now().strftime('%Y-%m-%d')}.log"

        # Flush immediately after each write (ensures errors are visible immediately)
        # Without this, Python may buffer log writes and errors might not appear
        # in the log file until much later (or never, if the process crashes)
        class FlushingHandler(logging.handlers.TimedRotatingFileHandler):
            """Handler that flushes after every emit for immediate visibility."""

            def emit(self, record):
                super().emit(record)
                self.flush()

        file_handler = FlushingHandler(
            log_file,
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Log initial message
        logger.info("=" * 60)
        logger.info("Miller MCP Server - Logging Initialized")
        logger.info(f"Log file: {log_file}")
        logger.info(f"Log level: {logging.getLevelName(level)}")
        logger.info(f"Rotation: Daily at midnight, keeping {backup_count} days")
        logger.info("=" * 60)

    # Add console handler if requested and missing
    if console and not has_console_handler:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        logger.info("Console logging enabled (HTTP mode)")

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
