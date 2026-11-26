# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from rpa_rm_faturamento.supabase.models import ItemAFaturar, LoteRpa

_RE_NUMERO_MOVIMENTO = re.compile(r'N[uú]mero:\s*(\d+)', re.IGNORECASE)


def _extrair_numero_movimento(mensagem: str) -> str:
    match = _RE_NUMERO_MOVIMENTO.search(mensagem)
    if match:
        return match.group(1)
    return "Movimento nao detectado"


class DadosLofRepository:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table = table_name

    def fetch_itens_a_faturar(self) -> List[ItemAFaturar]:
        response = (
            self._client.table(self._table).select("*").eq("status", "A FATURAR").execute()
        )

        data = response.data or []
        return [ItemAFaturar.from_dict(row) for row in data]

    def fetch_itens_por_lote(self, lote_id: int) -> List[ItemAFaturar]:
        response = (
            self._client.table(self._table)
            .select("*")
            .eq("lote_faturamento_id", lote_id)
            .eq("status", "A FATURAR")
            .execute()
        )
        data = response.data or []
        return [ItemAFaturar.from_dict(row) for row in data]

    def deletar_itens_a_faturar(self) -> int:
        """
        Remove os itens com status 'A FATURAR' (fila de entrada).

        Usado na reconstrução da fila — preserva itens FATURADO/NAO FATURADO
        para auditoria e limpa apenas a fila ativa, que será repovoada a partir
        dos dados reais do RM. Retorna a quantidade removida.
        """
        response = (
            self._client.table(self._table)
            .delete(count="exact")
            .eq("status", "A FATURAR")
            .execute()
        )
        return getattr(response, "count", None) or 0

    def marcar_itens_nao_faturado(self, ids: Iterable[int], mensagem: str = "") -> None:
        ids_list = sorted({int(item_id) for item_id in ids if item_id is not None})
        if not ids_list:
            return

        payload: dict = {"status": "NAO FATURADO"}
        if mensagem:
            payload["msg_mov_gerado"] = mensagem[:500]  # trunca para caber no campo

        (
            self._client.table(self._table)
            .update(payload)
            .in_("id", ids_list)
            .execute()
        )

    def atualizar_itens_faturados(self, ids: Iterable[int], mensagem_rm: str) -> str:
        ids_list = sorted({int(item_id) for item_id in ids if item_id is not None})
        if not ids_list:
            return ""

        numero_movimento = _extrair_numero_movimento(mensagem_rm)

        (
            self._client.table(self._table)
            .update({
                "status": "FATURADO",
                "msg_mov_gerado": mensagem_rm,
                "movimento_gerado": numero_movimento,
            })
            .in_("id", ids_list)
            .execute()
        )

        response = (
            self._client.table(self._table)
            .select("id")
            .in_("id", ids_list)
            .eq("status", "FATURADO")
            .execute()
        )

        data = response.data or []
        ids_atualizados = {int(row["id"]) for row in data if row.get("id") is not None}
        ids_esperados = set(ids_list)
        ids_faltantes = sorted(ids_esperados - ids_atualizados)

        if ids_faltantes:
            raise RuntimeError(
                f"Nao foi possivel atualizar status para FATURADO nos ids: {ids_faltantes}"
            )

        return numero_movimento


class LotesRpaRepository:
    _TABLE = "lotes_faturamento_rpa"

    def __init__(self, client):
        self._client = client

    def fetch_proximo_lote_pendente(self) -> Optional[LoteRpa]:
        response = (
            self._client.table(self._TABLE)
            .select("*")
            .eq("status", "PENDENTE")
            .order("id")
            .limit(1)
            .execute()
        )
        data = response.data or []
        if not data:
            return None
        return LoteRpa.from_dict(data[0])

    def marcar_lote_em_processamento(self, lote_id: int) -> None:
        self._client.table(self._TABLE).update(
            {"status": "EM PROCESSAMENTO"}
        ).eq("id", lote_id).execute()

    def marcar_lote_faturado(self, lote_id: int, numero_movimento: str) -> None:
        self._client.table(self._TABLE).update({
            "status": "FATURADO",
            "numero_movimento_destino": numero_movimento,
            "faturado_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", lote_id).execute()

    def marcar_lote_erro(self, lote_id: int, mensagem: str = "") -> None:
        self._client.table(self._TABLE).update(
            {"status": "ERRO"}
        ).eq("id", lote_id).execute()

    def deletar_lotes_nao_finais(self) -> int:
        """
        Remove os lotes em estado não-final ('PENDENTE' e 'EM PROCESSAMENTO').

        Usado na reconstrução da fila — preserva lotes FATURADO/ERRO para
        auditoria e limpa os que serão recriados a partir dos dados reais do RM.
        Inclui 'EM PROCESSAMENTO' para reconciliar órfãos de execuções que
        caíram no meio. Retorna a quantidade removida.
        """
        response = (
            self._client.table(self._TABLE)
            .delete(count="exact")
            .in_("status", ["PENDENTE", "EM PROCESSAMENTO"])
            .execute()
        )
        return getattr(response, "count", None) or 0
