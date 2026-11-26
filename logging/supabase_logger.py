# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict


class SupabaseLogger:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table = table_name

    def insert(self, record: Dict[str, Any]) -> None:
        try:
            self._client.table(self._table).insert(record).execute()
        except Exception:
            # Nunca interrompe o fluxo por falha de log
            pass
