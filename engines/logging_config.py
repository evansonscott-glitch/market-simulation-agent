"""
Philo Ventures Market Simulator — Logging Configuration

Provides structured, level-aware logging across all modules.
Replaces all print statements with proper logging that:
  - Filters sensitive data (API keys, tokens) from log output
  - Supports configurable log levels via config or env var
  - Outputs structured format with timestamps and module context
  - Can route to file, stdout, or both
"""
import logging
import os
import re
import sys
from typing import Optional


# ── Sensitive Data Filter ──
class SensitiveDataFilter(logging.Filter):
    """
    Redacts API keys, tokens, and other sensitive data from log messages.
    Catches common patterns: Bearer tokens, API keys, base64-encoded secrets.
    """

    PATTERNS = [
        # OpenAI-style API keys: sk-...
        (re.compile(r'(sk-[a-zA-Z0-9]{20,})'), r'sk-***REDACTED***'),
        # Generic API key patterns in key=value or key: value
        (re.compile(r'(api[_-]?key\s*[=:]\s*)["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
         r'\1***REDACTED***'),
        # Bearer tokens
        (re.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]{20,})', re.IGNORECASE),
         r'\1***REDACTED***'),
        # Generic token patterns
        (re.compile(r'(token\s*[=:]\s*)["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE),
         r'\1***REDACTED***'),
        # Slack tokens: xoxb-, xoxp-, xapp-
        (re.compile(r'(xox[bpa]-[a-zA-Z0-9\-]{10,})'), r'xox*-***REDACTED***'),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacement in self.PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        # Also filter args if they contain strings
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact(v) for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(a) for a in record.args)
        return True

    def _redact(self, value):
        if isinstance(value, str):
            for pattern, replacement in self.PATTERNS:
                value = pattern.sub(replacement, value)
        return value


# ── Formatter ──
class SimulatorFormatter(logging.Formatter):
    """
    Clean, readable log format for the simulator.
    Includes timestamp, level, module, and message.
    """

    FORMATS = {
        logging.DEBUG: "\033[90m%(asctime)s [DEBUG] %(name)s: %(message)s\033[0m",
        logging.INFO: "%(asctime)s [INFO]  %(name)s: %(message)s",
        logging.WARNING: "\033[33m%(asctime)s [WARN]  %(name)s: %(message)s\033[0m",
        logging.ERROR: "\033[31m%(asctime)s [ERROR] %(name)s: %(message)s\033[0m",
        logging.CRITICAL: "\033[1;31m%(asctime)s [CRIT]  %(name)s: %(message)s\033[0m",
    }

    PLAIN_FORMAT = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"

    def __init__(self, use_color: bool = True):
        super().__init__(datefmt="%Y-%m-%d %H:%M:%S")
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color and sys.stderr.isatty():
            fmt = self.FORMATS.get(record.levelno, self.PLAIN_FORMAT)
        else:
            fmt = self.PLAIN_FORMAT
        self._style._fmt = fmt
        return super().format(record)


# ── Module-level Logger Cache ──
_initialized = False


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    use_color: bool = True,
) -> None:
    """
    Initialize the logging system for the simulator.

    Call this once at startup (in run.py). All modules that call
    get_logger() will inherit this configuration.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional path to a log file. If provided, logs go to both
                  stdout and the file.
        use_color: Whether to use ANSI color codes in terminal output.
    """
    global _initialized

    # Resolve level from string
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Get the root logger for our namespace
    root_logger = logging.getLogger("philo_sim")
    root_logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # Sensitive data filter
    sensitive_filter = SensitiveDataFilter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(SimulatorFormatter(use_color=use_color))
    console_handler.addFilter(sensitive_filter)
    root_logger.addHandler(console_handler)

    # File handler (if requested)
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(SimulatorFormatter(use_color=False))
        file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger under the philo_sim namespace.

    Usage in any module:
        from engines.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("Something happened")

    Args:
        name: Module name (typically __name__).

    Returns:
        A configured logging.Logger instance.
    """
    global _initialized
    if not _initialized:
        # Auto-initialize with defaults if setup_logging hasn't been called
        setup_logging(
            level=os.getenv("PV_LOG_LEVEL", "INFO"),
        )

    # Create a child logger under our namespace
    if name.startswith("engines."):
        short_name = name.replace("engines.", "")
    elif name == "__main__":
        short_name = "runner"
    else:
        short_name = name

    return logging.getLogger(f"philo_sim.{short_name}")
