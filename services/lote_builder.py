# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

from rpa_rm_faturamento.supabase.models import ItemAFaturar, LoteFaturamento, LoteRpa

_TODOS = "TODOS"


def build_lotes(itens: List[ItemAFaturar], logger=None) -> List[LoteFaturamento]:
    grupos: dict[tuple, list[ItemAFaturar]] = defaultdict(list)
    itens_todos: List[ItemAFaturar] = []

    # 1ª passagem: agrupa itens com centro_custo específico por (filial, fornecedor, centro_custo)
    for item in itens:
        if not item.filial or not item.cnpj_fornecedor:
            if logger:
                logger.warning(
                    "LOTE",
                    "Item ignorado por falta de filial ou fornecedor",
                    item=item.cod_prd,
                )
            continue

        if item.centro_custo.upper() == _TODOS:
            itens_todos.append(item)
        else:
            grupos[(item.filial, item.cnpj_fornecedor, item.centro_custo, item.cod_comprador)].append(item)

    # 2ª passagem: distribui itens "TODOS" nos grupos existentes de mesma filial+fornecedor+comprador.
    # Se não existir nenhum grupo para aquela combinação, cria um grupo próprio "TODOS".
    for item in itens_todos:
        chaves_match = [
            k for k in grupos
            if k[0] == item.filial and k[1] == item.cnpj_fornecedor and k[3] == item.cod_comprador
        ]
        if chaves_match:
            for chave in chaves_match:
                grupos[chave].append(item)
        else:
            grupos[(item.filial, item.cnpj_fornecedor, _TODOS, item.cod_comprador)].append(item)

    lotes: List[LoteFaturamento] = []

    for (filial, fornecedor, centro_custo, cod_comprador), itens_grupo in grupos.items():
        movimentos = sorted({i.numero_movimento for i in itens_grupo if i.numero_movimento})
        tipo_frete = _pick_value(itens_grupo, "tipo_frete", logger, "frete")
        cod_pagamento = _pick_value(itens_grupo, "cod_pagamento", logger, "pagamento")
        dias_entrega = _pick_int(
            itens_grupo, "dias_entrega_fornecedor", logger, "dias_entrega_fornecedor", default=10
        )
        numero_lof = _pick_value(itens_grupo, "numero_lof", logger, "numero_lof")

        lotes.append(
            LoteFaturamento(
                lote_id=0,
                filial=filial,
                cnpj_fornecedor=fornecedor,
                centro_custo=centro_custo,
                itens=itens_grupo,
                movimentos_origem=movimentos,
                cod_comprador=cod_comprador,
                tipo_frete=tipo_frete,
                cod_pagamento=cod_pagamento,
                dias_entrega_fornecedor=dias_entrega,
                numero_lof=numero_lof,
            )
        )

    # ordenacao deterministica
    lotes.sort(key=lambda l: (l.filial, l.cnpj_fornecedor, l.centro_custo, l.cod_comprador))
    return lotes


def build_lote_from_rpa(
    lote_rpa: LoteRpa,
    itens: List[ItemAFaturar],
    logger=None,
) -> LoteFaturamento:
    """Constrói LoteFaturamento a partir de um LoteRpa já persistido e seus itens."""
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


def _pick_value(itens: List[ItemAFaturar], attr: str, logger, label: str) -> str:
    valores = {getattr(i, attr) for i in itens if getattr(i, attr)}
    if len(valores) > 1 and logger:
        logger.warning(
            "LOTE",
            f"Multiplos valores de {label} no mesmo lote. Usando o primeiro.",
            payload={"valores": sorted(list(valores))},
        )

    if valores:
        return sorted(list(valores))[0]
    return ""


def _pick_int(
    itens: List[ItemAFaturar],
    attr: str,
    logger,
    label: str,
    default: int,
) -> int:
    valores = {getattr(i, attr) for i in itens if getattr(i, attr) is not None}
    if len(valores) > 1 and logger:
        logger.warning(
            "LOTE",
            f"Multiplos valores de {label} no mesmo lote. Usando o primeiro.",
            payload={"valores": sorted(list(valores))},
        )

    if valores:
        return sorted(list(valores))[0]
    return default
