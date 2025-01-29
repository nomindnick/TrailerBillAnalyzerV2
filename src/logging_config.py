import logging
import logging.config
import os
from typing import Dict, Any

def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure logging for the application.

    Args:
        log_level: Desired logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%H:%M:%S"
            },
            "simple": {
                "format": "%(message)s"
            }
        },
        "filters": {
            "exclude_api_calls": {
                "()": "src.logging_config.APICallFilter"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "standard",
                "filters": ["exclude_api_calls"],
                "stream": "ext://sys.stdout"
            },
            "file": {
                "class": "logging.FileHandler",
                "level": "DEBUG",
                "formatter": "standard",
                "filename": os.path.join("logs", "application.log"),
                "mode": "a"
            }
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": True
            },
            "src.section_matcher": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "src.impact_analyzer": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "src.bill_scraper": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            }
        }
    }

    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # Apply the configuration
    logging.config.dictConfig(config)

class APICallFilter(logging.Filter):
    """Filter out API call details while keeping important process information."""

    def filter(self, record: logging.LogRecord) -> bool:
        # List of patterns to filter out
        api_patterns = [
            "API request:",
            "API response:",
            "Request ID:",
            "completion.create",
            "chat.completions.create"
        ]

        # Check if the log message contains any of the patterns
        if any(pattern in str(record.msg) for pattern in api_patterns):
            return False

        return True

def get_module_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module with the correct configuration.

    Args:
        name: Name of the module (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)