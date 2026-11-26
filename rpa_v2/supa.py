# -*- coding: utf-8 -*-
"""Supabase no v2 = COPIA do comportamento do v1 (mesmas tabelas, filtros, status e ordem):
- rpa_rm_faturamento/supabase/{client,models,repository}.py
- rpa_rm_faturamento/services/{lote_builder,fila_service}.py
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, List, Optional

from erros import ReconstrucaoFilaError

FUNCTION_CLIENT_TIMEOUT_S = 180  # igual ao v1 (validar-itens pode levar ~60s)


def get_supabase_client(settings: dict):
    from supabase import ClientOptions, create_client
    options = ClientOptions(function_client_timeout=FUNCTION_CLIENT_TIMEOUT_S)
    return create_client(settings["supabase_url"], settings["supabase_key"], options=options)


# ------------------------------------------------------------------ modelos (v1: supabase/models.py)
def _format_aliquota(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, (int, float, Decimal)):
        return str(value).replace(".", ",")
    return str(value).replace(".", ",")


def _format_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


@dataclass(frozen=True)
class ItemAFaturar:
    id: int
    numero_movimento: str
    cod_prd: str
    cnpj_fornecedor: str
    preco_unitario: Optional[float]
    ipi: str
    icms: str
    cod_comprador: str
    tipo_frete: str
    filial: str
    cod_pagamento: str
    dias_entrega_fornecedor: Optional[int]
    status: str
    msg_mov_gerado: Optional[str]
    centro_custo: str
    numero_lof: str

    @staticmethod
    def from_dict(row: dict) -> "ItemAFaturar":
        preco = row.get("preco_unitario")
        try:
            preco_float = None if preco is None else float(preco)
        except Exception:
            preco_float = None
        return ItemAFaturar(
            id=int(row["id"]),
            numero_movimento=_format_text(row.get("numero_movimento")),
            cod_prd=_format_text(row.get("cod_prd")),
            cnpj_fornecedor=_format_text(row.get("cnpj_fornecedor")),
            preco_unitario=preco_float,
            ipi=_format_aliquota(row.get("IPI")),
            icms=_format_aliquota(row.get("ICMS")),
            cod_comprador=_format_text(row.get("cod_comprador")),
            tipo_frete=_format_text(row.get("tipo_frete")),
            filial=_format_text(row.get("filial")),
            cod_pagamento=_format_text(row.get("cod_pagamento")),
            dias_entrega_fornecedor=_to_int(row.get("dias_entrega_fornecedor")),
            status=_format_text(row.get("status")),
            msg_mov_gerado=row.get("msg_mov_gerado"),
            centro_custo=_format_text(row.get("centro_custo")),
            numero_lof=_format_text(row.get("numero_lof")),
        )


@dataclass(frozen=True)
class LoteFaturamento:
    lote_id: int
    filial: str
    cnpj_fornecedor: str
    centro_custo: str
    itens: list
    movimentos_origem: list
    cod_comprador: str
    tipo_frete: str
    cod_pagamento: str
    dias_entrega_fornecedor: int
    numero_lof: str

    @property
    def itens_ids(self) -> list:
        return [item.id for item in self.itens]


@dataclass(frozen=True)
class LoteRpa:
    id: int
    status: str
    cnpj_fornecedor: str
    nome_fornecedor: Optional[str]
    cod_comprador: str
    numero_lof: Optional[int]
    filial: str
    centro_custo: str
    quantidade_itens: int
    numeros_movimento_origem: List[str]
    numero_movimento_destino: Optional[str]

    @staticmethod
    def from_dict(row: dict) -> "LoteRpa":
        return LoteRpa(
            id=int(row["id"]),
            status=_format_text(row.get("status")),
            cnpj_fornecedor=_format_text(row.get("cnpj_fornecedor")),
            nome_fornecedor=row.get("nome_fornecedor"),
            cod_comprador=_format_text(row.get("cod_comprador")),
            numero_lof=_to_int(row.get("numero_lof")),
            filial=_format_text(row.get("filial")),
            centro_custo=_format_text(row.get("centro_custo") or ""),
            quantidade_itens=int(row.get("quantidade_itens") or 0),
            numeros_movimento_origem=list(row.get("numeros_movimento_origem") or []),
            numero_movimento_destino=row.get("numero_movimento_destino"),
        )


# ------------------------------------------------------------------ repositorios (v1: supabase/repository.py)
_RE_NUMERO_MOVIMENTO = re.compile(r'N[uú]mero:\s*(\d+)', re.IGNORECASE)


def extrair_numero_movimento(mensagem: str) -> str:
    match = _RE_NUMERO_MOVIMENTO.search(mensagem or "")
    return match.group(1) if match else "Movimento nao detectado"


class DadosLofRepository:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table = table_name

    def fetch_itens_por_lote(self, lote_id: int) -> List[ItemAFaturar]:
        response = (
            self._client.table(self._table)
            .select("*")
            .eq("lote_faturamento_id", lote_id)
            .eq("status", "A FATURAR")
            .execute()
        )
        return [ItemAFaturar.from_dict(row) for row in (response.data or [])]

    def deletar_itens_a_faturar(self) -> int:
        response = (
            self._client.table(self._table).delete(count="exact").eq("status", "A FATURAR").execute()
        )
        return getattr(response, "count", None) or 0

    def marcar_itens_nao_faturado(self, ids: Iterable[int], mensagem: str = "") -> None:
        ids_list = sorted({int(i) for i in ids if i is not None})
        if not ids_list:
            return
        payload: dict = {"status": "NAO FATURADO"}
        if mensagem:
            payload["msg_mov_gerado"] = mensagem[:500]
        self._client.table(self._table).update(payload).in_("id", ids_list).execute()

    def atualizar_itens_faturados(self, ids: Iterable[int], mensagem_rm: str) -> str:
        ids_list = sorted({int(i) for i in ids if i is not None})
        if not ids_list:
            return ""
        numero_movimento = extrair_numero_movimento(mensagem_rm)
        (
            self._client.table(self._table)
            .update({"status": "FATURADO", "msg_mov_gerado": mensagem_rm, "movimento_gerado": numero_movimento})
            .in_("id", ids_list)
            .execute()
        )
        response = (
            self._client.table(self._table).select("id").in_("id", ids_list).eq("status", "FATURADO").execute()
        )
        ids_atualizados = {int(r["id"]) for r in (response.data or []) if r.get("id") is not None}
        faltantes = sorted(set(ids_list) - ids_atualizados)
        if faltantes:
            raise RuntimeError(f"Nao foi possivel atualizar status para FATURADO nos ids: {faltantes}")
        return numero_movimento


class LotesRpaRepository:
    _TABLE = "lotes_faturamento_rpa"

    def __init__(self, client):
        self._client = client

    def fetch_proximo_lote_pendente(self) -> Optional[LoteRpa]:
        response = (
            self._client.table(self._TABLE).select("*").eq("status", "PENDENTE").order("id").limit(1).execute()
        )
        data = response.data or []
        return LoteRpa.from_dict(data[0]) if data else None

    def fetch_lote_pendente_por_id(self, lote_id: int) -> Optional[LoteRpa]:
        """So para execucao controlada (--lote): o lote indicado, se ainda estiver PENDENTE."""
        response = (
            self._client.table(self._TABLE).select("*").eq("id", lote_id).eq("status", "PENDENTE").limit(1).execute()
        )
        data = response.data or []
        return LoteRpa.from_dict(data[0]) if data else None

    def marcar_lote_em_processamento(self, lote_id: int) -> None:
        self._client.table(self._TABLE).update({"status": "EM PROCESSAMENTO"}).eq("id", lote_id).execute()

    def marcar_lote_faturado(self, lote_id: int, numero_movimento: str) -> None:
        self._client.table(self._TABLE).update({
            "status": "FATURADO",
            "numero_movimento_destino": numero_movimento,
            "faturado_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", lote_id).execute()

    def marcar_lote_erro(self, lote_id: int, mensagem: str = "") -> None:
        self._client.table(self._TABLE).update({"status": "ERRO"}).eq("id", lote_id).execute()

    def deletar_lotes_nao_finais(self) -> int:
        response = (
            self._client.table(self._TABLE)
            .delete(count="exact")
            .in_("status", ["PENDENTE", "EM PROCESSAMENTO"])
            .execute()
        )
        return getattr(response, "count", None) or 0


# ------------------------------------------------------------------ lote (v1: services/lote_builder.py)
def _pick_value(itens, attr, logger, label) -> str:
    valores = {getattr(i, attr) for i in itens if getattr(i, attr)}
    if len(valores) > 1 and logger:
        logger.warning("LOTE", f"Multiplos valores de {label} no mesmo lote. Usando o primeiro.",
                       payload={"valores": sorted(list(valores))})
    return sorted(list(valores))[0] if valores else ""


def _pick_int(itens, attr, logger, label, default: int) -> int:
    valores = {getattr(i, attr) for i in itens if getattr(i, attr) is not None}
    if len(valores) > 1 and logger:
        logger.warning("LOTE", f"Multiplos valores de {label} no mesmo lote. Usando o primeiro.",
                       payload={"valores": sorted(list(valores))})
    return sorted(list(valores))[0] if valores else default


def build_lote_from_rpa(lote_rpa: LoteRpa, itens: List[ItemAFaturar], logger=None) -> LoteFaturamento:
    tipo_frete = _pick_value(itens, "tipo_frete", logger, "frete")
    cod_pagamento = _pick_value(itens, "cod_pagamento", logger, "pagamento")
    dias_entrega = _pick_int(itens, "dias_entrega_fornecedor", logger, "dias_entrega_fornecedor", default=10)
    movimentos = sorted({i.numero_movimento for i in itens if i.numero_movimento})
    return LoteFaturamento(
        lote_id=lote_rpa.id,
        filial=lote_rpa.filial,
        cnpj_fornecedor=lote_rpa.cnpj_fornecedor,
        centro_custo=lote_rpa.centro_custo,
        itens=itens,
        movimentos_origem=movimentos,
        cod_comprador=lote_rpa.cod_comprador,
        tipo_frete=tipo_frete,
        cod_pagamento=cod_pagamento,
        dias_entrega_fornecedor=dias_entrega,
        numero_lof=str(lote_rpa.numero_lof) if lote_rpa.numero_lof else "",
    )


def lote_para_v2(lote: LoteFaturamento, settings: dict) -> dict:
    """Converte o LoteFaturamento (formato v1) no dicionario usado pelas etapas do v2.
    Mesmas regras do v1: comprador com 5 digitos, entrega = hoje + dias, historico da LOF."""
    comprador = lote.cod_comprador
    if comprador.isdigit():
        comprador = comprador.zfill(5)
    numero_lof = lote.numero_lof or "N/A"
    return {
        "lote_id": lote.lote_id,
        "filial": lote.filial,
        "tipo_mov_origem": settings["tipo_movimento_origem"],
        "tipo_mov_destino": settings["tipo_movimento_destino"],
        "movimentos": list(lote.movimentos_origem),
        "cnpj_fornecedor": lote.cnpj_fornecedor,
        "cod_comprador": comprador,
        "cod_pagamento": lote.cod_pagamento,
        "tipo_frete": lote.tipo_frete,
        "data_entrega": (date.today() + timedelta(days=int(lote.dias_entrega_fornecedor or 10))).strftime("%d/%m/%Y"),
        "justificativa": ("Movimento gerado pelo RPA de pedidos automaticos de acordo com o"
                          f" contrato LOF de numero: {numero_lof}"),
        "itens": [
            {"id": i.id, "seq": None, "cod_prd": i.cod_prd, "preco": i.preco_unitario,
             "ipi": i.ipi, "icms": i.icms, "movimento": i.numero_movimento}
            for i in lote.itens
        ],
    }


# ------------------------------------------------------------------ fila (v1: services/fila_service.py)
class FilaService:
    """Reconstrucao da fila SO na recuperacao critica (igual ao v1): limpa a fila ativa e chama as
    edge functions cria_produtos_a_faturar -> validar-itens -> criar-lotes-faturamento."""

    FUNCOES_ORDEM = ("cria_produtos_a_faturar", "validar-itens", "criar-lotes-faturamento")

    def __init__(self, client, dados_repo, lotes_repo, logger):
        self._client = client
        self._dados_repo = dados_repo
        self._lotes_repo = lotes_repo
        self._logger = logger

    def reconstruir(self) -> bool:
        self._logger.info("REBUILD", "Iniciando reconstrucao da fila (limpeza + edge functions)")
        try:
            itens_removidos = self._dados_repo.deletar_itens_a_faturar()
            lotes_removidos = self._lotes_repo.deletar_lotes_nao_finais()
            self._logger.info("REBUILD", "Fila antiga limpa",
                              payload={"itens_a_faturar_removidos": itens_removidos,
                                       "lotes_removidos": lotes_removidos})
        except Exception:
            self._logger.exception("REBUILD", "Falha ao limpar a fila antiga; abortando reconstrucao")
            return False
        for nome in self.FUNCOES_ORDEM:
            try:
                resultado = self._invocar(nome)
                self._logger.info("REBUILD", f"Edge function '{nome}' executada com sucesso",
                                  payload=_resumir_resultado(resultado))
            except ReconstrucaoFilaError as exc:
                self._logger.error("REBUILD", f"Edge function '{nome}' falhou; reconstrucao abortada",
                                   payload={"erro": str(exc)})
                return False
        self._logger.info("REBUILD", "Reconstrucao da fila concluida com sucesso")
        return True

    def _invocar(self, nome: str) -> dict:
        try:
            resp = self._client.functions.invoke(nome, invoke_options={"responseType": "json"})
        except Exception as exc:
            raise ReconstrucaoFilaError(f"invoke '{nome}' falhou: {exc}") from exc
        if isinstance(resp, (bytes, bytearray)):
            try:
                resp = json.loads(resp.decode("utf-8"))
            except Exception:
                return {}
        if isinstance(resp, dict):
            if resp.get("error"):
                raise ReconstrucaoFilaError(f"'{nome}' retornou erro: {resp.get('error')}")
            return resp
        return {}


def _resumir_resultado(resultado) -> dict:
    if not isinstance(resultado, dict):
        return {}
    chaves = ("ok", "totalElegiveis", "totalInseridos", "total_itens", "itens_aprovados",
              "itens_reprovados", "message", "lotes_criados")
    resumo: dict = {}
    for chave in chaves:
        if chave not in resultado:
            continue
        valor = resultado[chave]
        if chave == "lotes_criados" and isinstance(valor, list):
            resumo["lotes_criados"] = len(valor)
        else:
            resumo[chave] = valor
    return resumo
