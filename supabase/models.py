# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, List, Optional


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
        preco_float: Optional[float]
        if preco is None:
            preco_float = None
        else:
            try:
                preco_float = float(preco)
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


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


@dataclass(frozen=True)
class LoteFaturamento:
    lote_id: int
    filial: str
    cnpj_fornecedor: str
    centro_custo: str
    itens: list[ItemAFaturar]
    movimentos_origem: list[str]
    cod_comprador: str
    tipo_frete: str
    cod_pagamento: str
    dias_entrega_fornecedor: int
    numero_lof: str

    @property
    def itens_ids(self) -> list[int]:
        return [item.id for item in self.itens]


@dataclass(frozen=True)
class LoteRpa:
    """Representa uma linha da tabela lotes_faturamento_rpa."""
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
