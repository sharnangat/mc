import logging
import sys

from app.config import settings

# Third-party libraries that log noisily at INFO/DEBUG and drown out application logs.
_QUIET_LOGGERS = ("httpx", "httpcore", "sentence_transformers", "urllib3", "asyncio")


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (e.g. uvicorn --reload re-importing this module)

    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
