import sys
from loguru import logger
from olmas_kashey.core.settings import settings

def configure_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level.value,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> | {extra}",
    )
    logger.add(
        "logs/olmas_kashey.log",
        rotation="10 MB",
        retention="1 week",
        level=settings.log_level.value,
        compression="zip",
        enqueue=True, # Thread-safe
        backtrace=True,
        diagnose=True, # Be careful with diagnose in prod as it might leak vars, but useful for now
    )

    # Intercept standard logging
    import logging
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = logging.currentframe(), 2
            while frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

configure_logging()
