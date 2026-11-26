# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
import os
import traceback
from typing import Any, Dict, Optional

from rpa_rm_faturamento.config import Settings
from rpa_rm_faturamento.logging.supabase_logger import SupabaseLogger


class RpaLogger:
    def __init__(
        self,
        execution_id: str,
        logger: logging.Logger,
        supabase_logger: Optional[SupabaseLogger],
    ):
        self._execution_id = execution_id
        self._logger = logger
        self._supabase_logger = supabase_logger

    def info(self, step: str, message: str, **kwargs):
        self._log(logging.INFO, step, message, **kwargs)

    def warning(self, step: str, message: str, **kwargs):
        self._log(logging.WARNING, step, message, **kwargs)

    def error(self, step: str, message: str, **kwargs):
        self._log(logging.ERROR, step, message, **kwargs)

    def exception(self, step: str, message: str, **kwargs):
        payload = kwargs.pop("payload", {}) or {}
        payload["stacktrace"] = traceback.format_exc()
        self._log(logging.ERROR, step, message, payload=payload, **kwargs)

    def _log(self, level: int, step: str, message: str, **kwargs):
        payload = kwargs.pop("payload", None)
        record = {
            "execution_id": self._execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": logging.getLevelName(level),
            "step": step,
            "message": message,
            "payload": _safe_payload(payload),
            "movimento_origem": kwargs.pop("movimento_origem", None),
            "movimento_destino": kwargs.pop("movimento_destino", None),
            "filial": kwargs.pop("filial", None),
            "fornecedor": kwargs.pop("fornecedor", None),
            "lote_id": kwargs.pop("lote_id", None),
            "item": kwargs.pop("item", None),
            "duration_ms": kwargs.pop("duration_ms", None),
        }

        self._logger.log(level, json.dumps(record, ensure_ascii=False))

        if self._supabase_logger:
            self._supabase_logger.insert(record)


def build_logger(settings: Settings, supabase_client, execution_id: str) -> RpaLogger:
    logger = logging.getLogger("rpa_rm_faturamento")
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        # Console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logger.level)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console_handler)

        # Arquivo rotativo
        log_dir = os.path.dirname(settings.log_file_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            settings.log_file_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(file_handler)

    supa_logger = None
    if supabase_client:
        supa_logger = SupabaseLogger(supabase_client, settings.supabase_table_logs)

    return RpaLogger(execution_id, logger, supa_logger)


def _safe_payload(payload: Any) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    try:
        json.dumps(payload)
        return payload  # type: ignore[return-value]
    except Exception:
        return {"value": str(payload)}
