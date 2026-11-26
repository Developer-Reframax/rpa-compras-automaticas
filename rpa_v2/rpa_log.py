# -*- coding: utf-8 -*-
"""Log no MESMO padrao do v1 (rpa_rm_faturamento/logging/logger.py + supabase_logger.py):
um JSON por linha no console e em arquivo rotativo, e insert na tabela de logs (rpa_logs) que
nunca interrompe o fluxo. Mesmos campos: execution_id, timestamp, level, step, message, payload,
movimento_origem, movimento_destino, filial, fornecedor, lote_id, item, duration_ms."""
from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional


class SupabaseLogger:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table = table_name

    def insert(self, record: Dict[str, Any]) -> None:
        try:
            self._client.table(self._table).insert(record).execute()
        except Exception:
            pass  # nunca interrompe o fluxo por falha de log


class RpaLogger:
    def __init__(self, execution_id: str, logger: logging.Logger, supabase_logger: Optional[SupabaseLogger]):
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


def build_logger(settings: dict, supabase_client, execution_id: str) -> RpaLogger:
    logger = logging.getLogger("rpa_rm_faturamento")
    logger.setLevel(getattr(logging, str(settings["log_level"]).upper(), logging.INFO))
    logger.propagate = False
    if not logger.handlers:
        console = logging.StreamHandler()
        console.setLevel(logger.level)
        console.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console)
        log_dir = os.path.dirname(settings["log_file_path"])
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        arquivo = RotatingFileHandler(settings["log_file_path"], maxBytes=settings["log_max_bytes"],
                                      backupCount=settings["log_backup_count"], encoding="utf-8")
        arquivo.setLevel(logger.level)
        arquivo.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(arquivo)
    supa = SupabaseLogger(supabase_client, settings["supabase_table_logs"]) if supabase_client else None
    return RpaLogger(execution_id, logger, supa)


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
