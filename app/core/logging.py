"""日志配置模块 - JSON 格式输出"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Optional

from app.core.config import get_settings


def redacted_exception_info(
    exc: BaseException,
) -> tuple[type[BaseException], BaseException, TracebackType | None]:
    """Keep stack locations without logging exception values, causes or contexts."""
    sanitized = RuntimeError(f"{type(exc).__name__}: exception details redacted")
    return RuntimeError, sanitized, exc.__traceback__


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器，兼容 CLS 等日志服务"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "file": record.filename,
        }

        # 添加额外字段（如果有）
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # 添加进程和线程信息（可选，用于调试）
        if record.levelno >= logging.WARNING:
            log_data["process"] = record.process
            log_data["thread"] = record.thread

        return json.dumps(log_data, ensure_ascii=False, default=str)


class LoggerSetup:
    """日志设置类"""

    _initialized = False

    def __init__(self):
        if not LoggerSetup._initialized:
            self._setup_logger()
            LoggerSetup._initialized = True

    def _setup_logger(self):
        settings = get_settings()

        log_file = Path(settings.LOG_FILE)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # 创建 JSON 格式化器
        json_formatter = JSONFormatter()

        # 创建处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(json_formatter)

        file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
        file_handler.setFormatter(json_formatter)

        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

        # 清除已有的处理器，避免重复
        root_logger.handlers.clear()
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

        # 设置第三方库日志级别
        logging.getLogger("uvicorn").setLevel(logging.INFO)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器"""
    return logging.getLogger(name)


class StructuredLogger:
    """结构化日志记录器，支持附加数据"""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _log(
        self, level: int, message: str, data: Optional[dict] = None, exc_info=None
    ):
        extra = {"extra_data": data} if data else {}
        self._logger.log(level, message, exc_info=exc_info, extra=extra)

    def debug(self, message: str, data: Optional[dict] = None):
        self._log(logging.DEBUG, message, data)

    def info(self, message: str, data: Optional[dict] = None):
        self._log(logging.INFO, message, data)

    def warning(self, message: str, data: Optional[dict] = None):
        self._log(logging.WARNING, message, data)

    def error(self, message: str, data: Optional[dict] = None, exc_info=None):
        self._log(logging.ERROR, message, data, exc_info=exc_info)

    def critical(self, message: str, data: Optional[dict] = None, exc_info=None):
        self._log(logging.CRITICAL, message, data, exc_info=exc_info)


def get_structured_logger(name: str) -> StructuredLogger:
    """获取结构化日志记录器"""
    return StructuredLogger(logging.getLogger(name))


def log_request(logger: logging.Logger, endpoint: str, data: Any = None):
    """记录请求日志"""
    log_data = {"endpoint": endpoint}
    if data:
        log_data["request_data"] = data
    logger.info(json.dumps({"event": "request", **log_data}, ensure_ascii=False))


def log_response(logger: logging.Logger, endpoint: str, data: Any = None):
    """记录响应日志"""
    log_data = {"endpoint": endpoint}
    if data:
        log_data["response_data"] = data
    logger.debug(json.dumps({"event": "response", **log_data}, ensure_ascii=False))


def log_error(logger: logging.Logger, message: str, exc: Optional[Exception] = None):
    """记录错误日志"""
    if exc:
        logger.error(message, exc_info=(type(exc), exc, exc.__traceback__))
    else:
        logger.error(message)
