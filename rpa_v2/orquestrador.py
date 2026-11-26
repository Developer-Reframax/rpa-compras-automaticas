# -*- coding: utf-8 -*-
"""Ciclo de producao do v2 = MESMA logica de lotes do v1 (rpa_rm_faturamento/orchestrator/orchestrator.py),
com as etapas de tela do v2.

A cada iteracao:
  1. Garante o RM operacional (abre/login/janela principal; fecha janelas que sobraram).
  2. Le o proximo lote PENDENTE (ordem por id). Sem lote: encerra.
  3. Marca EM PROCESSAMENTO e busca os itens A FATURAR do lote (sem itens: lote ERRO).
  4. Fatura o lote:
     - MovimentoNaoEncontradoError (e subclasses: lock, erro do RM no wizard/confirmacao):
       lote ERRO + itens NAO FATURADO e segue (nao conta como erro inesperado);
     - erro inesperado: lote ERRO + itens NAO FATURADO, conta; 3 seguidos -> erro critico;
     - sucesso: itens FATURADO (+ numero do movimento) e lote FATURADO. Se essa gravacao falhar,
       interrompe (risco de faturar o mesmo lote duas vezes).
  Erro critico: fecha o RM, reconstroi a fila (edge functions) e reabre. Maximo 3 seguidos.
"""
from __future__ import annotations

import time

import w32 as win32  # noqa
import uia_min
from comum import ErroRM
from erros import (ErroCriticoRMError, ErroRecebimentoRMError, ErroRMDuranteFaturamentoError,
                   MovimentoEmFaturamentoError, MovimentoNaoEncontradoError)
from etapas import confirmacao, faturar, inicio, itens, movimento
from limpeza import fechar_rm, limpar_janelas
from medidor import log
from supa import build_lote_from_rpa, lote_para_v2


class OrquestradorV2:
    MAX_REBUILDS_CRITICOS = 3
    LIMITE_ERROS_INESPERADOS = 3

    def __init__(self, ctx, settings, dados_repo, lotes_repo, fila_service, logger, lote_fixo=None, max_lotes=None):
        self.lote_fixo = lote_fixo      # --lote: processa so este lote (se PENDENTE)
        self.max_lotes = max_lotes      # --max-lotes: para apos N lotes processados
        self.ctx = ctx
        self.settings = settings
        self.dados = dados_repo
        self.lotes = lotes_repo
        self.fila = fila_service
        self.logger = logger

    # ------------------------------------------------------------------ ciclo
    def run(self) -> None:
        rebuilds_criticos = 0
        erros_inesperados = 0
        processados = 0
        while True:
            try:
                if self.max_lotes is not None and processados >= self.max_lotes:
                    self.logger.info("ORQUESTRADOR", f"Limite de {self.max_lotes} lote(s) desta execucao atingido")
                    break
                self._garantir_estado_operacional()

                if self.lote_fixo is not None:
                    lote_rpa = None if processados else self.lotes.fetch_lote_pendente_por_id(self.lote_fixo)
                else:
                    lote_rpa = self.lotes.fetch_proximo_lote_pendente()
                if not lote_rpa:
                    self.logger.info("SUPABASE", "Nenhum lote com status PENDENTE — faturamento concluido")
                    break

                try:
                    self.lotes.marcar_lote_em_processamento(lote_rpa.id)
                except Exception:
                    self.logger.exception("SUPABASE", "Falha ao marcar lote como EM PROCESSAMENTO; pulando lote",
                                          lote_id=lote_rpa.id, filial=lote_rpa.filial,
                                          fornecedor=lote_rpa.cnpj_fornecedor)
                    time.sleep(1)
                    continue

                itens_lote = self.dados.fetch_itens_por_lote(lote_rpa.id)
                if not itens_lote:
                    self.logger.warning("SUPABASE", "Lote sem itens A FATURAR; marcando lote como ERRO",
                                        lote_id=lote_rpa.id, filial=lote_rpa.filial,
                                        fornecedor=lote_rpa.cnpj_fornecedor)
                    try:
                        self.lotes.marcar_lote_erro(lote_rpa.id)
                    except Exception:
                        self.logger.exception("SUPABASE", "Falha ao marcar lote como ERRO", lote_id=lote_rpa.id)
                    time.sleep(1)
                    continue

                processados += 1
                lote = build_lote_from_rpa(lote_rpa, itens_lote, logger=self.logger)
                movimento_origem = ",".join(lote.movimentos_origem)
                info_lote = {
                    "cod_comprador": lote.cod_comprador,
                    "centro_custo": lote.centro_custo,
                    "numero_lof": lote.numero_lof,
                    "quantidade_itens": len(lote.itens),
                    "nome_fornecedor": lote_rpa.nome_fornecedor,
                }

                self.logger.info("NAVEGACAO", "Fechando abas residuais do TabControl")
                self.logger.info("NAVEGACAO", "Acessando Solicitacao de Compras")
                self.logger.info("FATURAMENTO", "Iniciando faturamento do lote", lote_id=lote.lote_id,
                                 filial=lote.filial, fornecedor=lote.cnpj_fornecedor,
                                 movimento_origem=movimento_origem, payload=info_lote)

                try:
                    mensagem_rm = self._executar_lote(lote)
                except MovimentoNaoEncontradoError as exc:
                    erros_inesperados = 0
                    self._tratar_erro_rm_no_lote(exc, lote, movimento_origem)
                    self._limpar_apos_erro()
                    time.sleep(1)
                    continue
                except ErroCriticoRMError:
                    raise
                except Exception:
                    erros_inesperados += 1
                    self.logger.exception("FATURAMENTO",
                                          "Erro inesperado ao processar lote; marcando ERRO/NAO FATURADO",
                                          lote_id=lote.lote_id, filial=lote.filial,
                                          fornecedor=lote.cnpj_fornecedor, movimento_origem=movimento_origem,
                                          payload={"erros_inesperados_consecutivos": erros_inesperados})
                    self._marcar_lote_falho(lote, movimento_origem, "Erro inesperado durante o processamento")
                    if erros_inesperados >= self.LIMITE_ERROS_INESPERADOS:
                        raise ErroCriticoRMError(f"{erros_inesperados} erros inesperados consecutivos — "
                                                 "RM provavelmente em estado invalido")
                    self._limpar_apos_erro()
                    time.sleep(1)
                    continue

                try:
                    numero_movimento = self.dados.atualizar_itens_faturados(lote.itens_ids, mensagem_rm)
                    self.lotes.marcar_lote_faturado(lote.lote_id, numero_movimento)
                    self.logger.info("SUPABASE", "Faturamento do lote concluido com sucesso",
                                     lote_id=lote.lote_id, filial=lote.filial, fornecedor=lote.cnpj_fornecedor,
                                     movimento_origem=movimento_origem, movimento_destino=numero_movimento,
                                     payload=info_lote)
                except Exception:
                    self.logger.exception("SUPABASE", "Falha ao atualizar status para FATURADO; interrompendo "
                                          "para evitar reprocessamento", lote_id=lote.lote_id, filial=lote.filial,
                                          fornecedor=lote.cnpj_fornecedor, movimento_origem=movimento_origem)
                    break

                erros_inesperados = 0
                rebuilds_criticos = 0
                time.sleep(1)

            except ErroCriticoRMError as exc:
                if rebuilds_criticos >= self.MAX_REBUILDS_CRITICOS:
                    self.logger.error("RECUPERACAO", "Limite de recuperacoes criticas atingido; encerrando execucao. "
                                      "Itens pendentes serao tratados no proximo ciclo agendado.",
                                      payload={"erro": str(exc), "max_rebuilds": self.MAX_REBUILDS_CRITICOS})
                    break
                rebuilds_criticos += 1
                self.logger.warning("RECUPERACAO",
                                    "Erro critico detectado — fechando RM completamente e reconstruindo a fila",
                                    payload={"erro": str(exc), "tentativa": rebuilds_criticos,
                                             "max": self.MAX_REBUILDS_CRITICOS})
                self._recuperar_rm_critico()
                erros_inesperados = 0
                continue

        self.logger.info("ORQUESTRADOR", "Execucao finalizada")

    # ------------------------------------------------------------------ um lote (etapas do v2)
    def _executar_lote(self, lote) -> str:
        if not lote.movimentos_origem:
            raise RuntimeError("Lote sem movimentos de origem")
        if not lote.cod_comprador or not lote.cod_pagamento or not lote.tipo_frete:
            raise RuntimeError("Lote sem comprador, pagamento ou frete")
        ctx = self.ctx
        ctx.lote = lote_para_v2(lote, self.settings)
        ctx.log_ctx = {"lote_id": lote.lote_id, "filial": lote.filial, "fornecedor": lote.cnpj_fornecedor}
        ctx.mov = ctx.form_sol = 0
        ctx.numero_gerado = None
        ctx.mensagem_rm = ""
        inicio_t = time.perf_counter()

        with ctx.med.etapa(f"lote {lote.lote_id}: navegacao"):
            inicio.navegacao(ctx)
        self.logger.info("SOLICITACAO", "Aplicando filtros na Solicitacao de Compras",
                         filial=lote.filial, fornecedor=lote.cnpj_fornecedor)
        with ctx.med.etapa(f"lote {lote.lote_id}: solicitacao"):
            inicio.solicitacao(ctx)
        with ctx.med.etapa(f"lote {lote.lote_id}: marcar"):
            try:
                faturar.marcar(ctx)
            except MovimentoNaoEncontradoError:
                self.logger.warning("SELECAO", "Nenhum movimento do lote foi encontrado na tabela do RM",
                                    filial=lote.filial, fornecedor=lote.cnpj_fornecedor,
                                    payload={"movimentos": list(lote.movimentos_origem)})
                raise
        self.logger.info("SELECAO", f"{ctx.qtd_marcados} movimento(s) marcados para receber",
                         filial=lote.filial, fornecedor=lote.cnpj_fornecedor)
        with ctx.med.etapa(f"lote {lote.lote_id}: receber"):
            try:
                faturar.receber(ctx)
            except ErroRM as e:
                raise MovimentoEmFaturamentoError(getattr(e, "mensagem", str(e))) from e
        with ctx.med.etapa(f"lote {lote.lote_id}: wizard"):
            try:
                faturar.wizard(ctx)
            except ErroRM as e:
                msg = getattr(e, "mensagem", str(e))
                self.logger.warning("WIZARD", "RM retornou erro ao criar movimento destino; abortando lote",
                                    filial=lote.filial, fornecedor=lote.cnpj_fornecedor,
                                    movimento_origem=",".join(lote.movimentos_origem),
                                    payload={"mensagem_rm": msg})
                raise ErroRecebimentoRMError(msg) from e
        with ctx.med.etapa(f"lote {lote.lote_id}: movimento"):
            movimento.movimento(ctx)
        with ctx.med.etapa(f"lote {lote.lote_id}: itens"):
            itens.itens(ctx)
        with ctx.med.etapa(f"lote {lote.lote_id}: confirmacao"):
            try:
                confirmacao.confirmacao(ctx)
            except ErroRM as e:
                raise ErroRMDuranteFaturamentoError(getattr(e, "mensagem", str(e))) from e

        self.logger.info("FATURAMENTO", "Faturamento concluido", filial=lote.filial,
                         fornecedor=lote.cnpj_fornecedor,
                         duration_ms=int((time.perf_counter() - inicio_t) * 1000))
        return ctx.mensagem_rm

    # ------------------------------------------------------------------ erros de lote (igual v1)
    def _tratar_erro_rm_no_lote(self, exc, lote, movimento_origem):
        if isinstance(exc, MovimentoEmFaturamentoError):
            step_log = "SELECAO"
            msg_log = ("Movimento bloqueado (em faturamento por outra sessao); marcando lote como ERRO e "
                       "itens como NAO FATURADO")
        elif isinstance(exc, ErroRMDuranteFaturamentoError):
            step_log = "FATURAMENTO"
            msg_log = "Erro RM durante faturamento; marcando lote como ERRO e itens como NAO FATURADO"
        else:
            step_log = "SELECAO"
            msg_log = "Movimentos nao encontrados na tabela RM; marcando lote como ERRO"
        self.logger.warning(step_log, msg_log, lote_id=lote.lote_id, filial=lote.filial,
                            fornecedor=lote.cnpj_fornecedor, movimento_origem=movimento_origem,
                            payload={"erro": str(exc)})
        try:
            self.dados.marcar_itens_nao_faturado(lote.itens_ids, mensagem=str(exc))
            self.lotes.marcar_lote_erro(lote.lote_id, str(exc))
            self.logger.info("SUPABASE", "Itens marcados como NAO FATURADO; lote marcado como ERRO",
                             lote_id=lote.lote_id, filial=lote.filial, fornecedor=lote.cnpj_fornecedor,
                             movimento_origem=movimento_origem)
        except Exception:
            self.logger.exception("SUPABASE", "Falha ao marcar itens/lote como NAO FATURADO/ERRO",
                                  lote_id=lote.lote_id, filial=lote.filial, fornecedor=lote.cnpj_fornecedor,
                                  movimento_origem=movimento_origem)

    def _marcar_lote_falho(self, lote, movimento_origem, motivo):
        try:
            self.dados.marcar_itens_nao_faturado(lote.itens_ids, mensagem=motivo)
            self.lotes.marcar_lote_erro(lote.lote_id, motivo)
        except Exception:
            self.logger.exception("SUPABASE", "Falha ao marcar lote/itens apos erro inesperado",
                                  lote_id=lote.lote_id, movimento_origem=movimento_origem)

    def _limpar_apos_erro(self):
        """Fecha o que sobrou do lote com erro. Sem sucesso -> erro critico (fecha o RM)."""
        if not limpar_janelas(self.ctx):
            raise ErroCriticoRMError("Nao foi possivel fechar as janelas do lote com erro")

    # ------------------------------------------------------------------ estado / recuperacao
    def _garantir_estado_operacional(self):
        ctx = self.ctx
        ctx.pid = inicio.achar_pid(ctx.cred["processo"], ctx.cred["exe"])
        if ctx.pid and inicio.janela_principal(ctx) and not limpar_janelas(ctx, timeout=60):
            raise ErroCriticoRMError("RM com janelas que nao fecham (estado desconhecido)")
        for tentativa in range(1, 4):
            try:
                inicio.login(ctx)
                return
            except ErroRM as e:
                self.logger.warning("LOGIN", f"Falha no login (tentativa {tentativa}/3)",
                                    payload={"erro": getattr(e, "mensagem", str(e))})
                limpar_janelas(ctx, timeout=15)
            except win32.TempoEsgotado as e:
                raise ErroCriticoRMError("Nao foi possivel atingir um estado operacional do RM "
                                         f"(tela desconhecida ou RM nao responde): {e}") from e
        raise RuntimeError("Login falhou apos 3 tentativas consecutivas. Verifique a sessao Windows e as credenciais.")

    def _recuperar_rm_critico(self):
        try:
            n = fechar_rm(self.ctx.cred["processo"], self.ctx.cred["exe"])
            log(f"   RM encerrado ({n} processo(s))")
        except Exception:
            self.logger.exception("RECUPERACAO", "Falha ao fechar o RM")
        time.sleep(5)
        uia_min._NOMES.clear()  # handles do RM antigo nao valem mais
        self.ctx.pid = 0
        self.ctx.main = self.ctx.form_sol = self.ctx.mov = 0
        try:
            ok = self.fila.reconstruir()
            self.logger.info("RECUPERACAO", "Reconstrucao da fila concluida" if ok
                             else "Reconstrucao da fila falhou — seguindo mesmo assim")
        except Exception:
            self.logger.exception("RECUPERACAO", "Falha inesperada ao reconstruir a fila")
        # o RM e reaberto pela etapa de login no proximo ciclo (Popen do executavel)
