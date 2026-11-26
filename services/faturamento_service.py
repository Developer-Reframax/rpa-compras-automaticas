# -*- coding: utf-8 -*-
from __future__ import annotations

import time

from rpa_rm_faturamento.config import Settings
from rpa_rm_faturamento.logging import RpaLogger
from rpa_rm_faturamento.rm.rm_navigation import obter_janela_principal
from rpa_rm_faturamento.rm.rm_solicitacao import (
    aplicar_filtro_pendentes,
    clicar_receber,
    detectar_erro_apos_receber,
    marcar_movimentos,
    tratar_solicitacao,
    verificar_janela_erro_rm,
)
from rpa_rm_faturamento.rm.rm_wizard import tratar_wizard, selecionar_movimento_destino
from rpa_rm_faturamento.rm.rm_movimento import aguardar_movimento_final, tratar_movimento_final
from rpa_rm_faturamento.supabase.models import LoteFaturamento
from rpa_rm_faturamento.utils.exceptions import ErroRecebimentoRMError, MovimentoNaoEncontradoError


class FaturamentoService:
    def __init__(self, settings: Settings, logger: RpaLogger):
        self._settings = settings
        self._logger = logger

    def executar_lote(self, lote: LoteFaturamento) -> str:
        if not lote.movimentos_origem:
            raise RuntimeError("Lote sem movimentos de origem")
        if not lote.cod_comprador or not lote.cod_pagamento or not lote.tipo_frete:
            raise RuntimeError("Lote sem comprador, pagamento ou frete")

        start = time.perf_counter()

        self._logger.info(
            "SOLICITACAO",
            "Aplicando filtros na Solicitacao de Compras",
            filial=lote.filial,
            fornecedor=lote.cnpj_fornecedor,
        )
        tratar_solicitacao(
            filial=lote.filial,
            tipo_movimento_origem=self._settings.tipo_movimento_origem,
            solicitacao_window_title=self._settings.rm_solicitacao_window_title,
        )
        aplicar_filtro_pendentes()

        main = obter_janela_principal()
        qtd = marcar_movimentos(main, lote.movimentos_origem)

        if qtd <= 0:
            self._logger.warning(
                "SELECAO",
                "Nenhum movimento do lote foi encontrado na tabela do RM",
                filial=lote.filial,
                fornecedor=lote.cnpj_fornecedor,
                payload={"movimentos": list(lote.movimentos_origem)},
            )
            raise MovimentoNaoEncontradoError(
                f"Movimentos nao encontrados na tabela RM: {list(lote.movimentos_origem)}"
            )

        self._logger.info(
            "SELECAO",
            f"{qtd} movimento(s) marcados para receber",
            filial=lote.filial,
            fornecedor=lote.cnpj_fornecedor,
        )

        clicar_receber(main)

        # Após Receber, o RM abre o wizard OU exibe o modal de erro padrão
        # (ex.: "movimento está em faturamento"). Detecta os dois em paralelo:
        # se for o modal, fecha e levanta MovimentoEmFaturamentoError (lock
        # transitório) — o orquestrador marca o lote como ERRO / itens como
        # NAO FATURADO e segue para o próximo lote.
        detectar_erro_apos_receber()

        tratar_wizard(self._settings.max_wait_time)
        selecionar_movimento_destino(
            self._settings.tipo_movimento_destino,
            self._settings.max_wait_time,
        )

        # Após selecionar 1.1.15 e clicar Avançar, o RM pode exibir uma janela
        # de erro (ex.: "Não existem itens a serem faturados") antes de abrir
        # o formulário do movimento. Verificamos antes de aguardar o formulário.
        erro_rm = verificar_janela_erro_rm()
        if erro_rm:
            self._logger.warning(
                "WIZARD",
                "RM retornou erro ao criar movimento destino; abortando lote",
                filial=lote.filial,
                fornecedor=lote.cnpj_fornecedor,
                movimento_origem=",".join(lote.movimentos_origem),
                payload={"mensagem_rm": erro_rm},
            )
            raise ErroRecebimentoRMError(erro_rm)

        # Captura a janela real do movimento para evitar busca global na UIA
        janela_movimento = aguardar_movimento_final(self._settings.max_wait_time)

        numero_lof = lote.numero_lof or "N/A"
        historico = (
            f"Movimento gerado pelo RPA de pedidos automaticos de acordo com o"
            f" contrato LOF de numero: {numero_lof}"
        )

        mensagem_rm = tratar_movimento_final(
            janela=janela_movimento,
            cnpj_fornecedor=lote.cnpj_fornecedor,
            cod_comprador=lote.cod_comprador,
            cod_pagamento=lote.cod_pagamento,
            tipo_frete=lote.tipo_frete,
            historico=historico,
            dias_entrega=lote.dias_entrega_fornecedor,
            itens=lote.itens,
            logger=self._logger,
        )

        duracao_ms = int((time.perf_counter() - start) * 1000)
        self._logger.info(
            "FATURAMENTO",
            "Faturamento concluido",
            filial=lote.filial,
            fornecedor=lote.cnpj_fornecedor,
            duration_ms=duracao_ms,
        )

        return mensagem_rm
