# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import uiautomation as auto

from rpa_rm_faturamento.config import Settings
from rpa_rm_faturamento.logging import RpaLogger
from rpa_rm_faturamento.orchestrator.state_machine import (
    EstadoRM,
    aguardar_fim_atualizacao,
    abrir_rm,
    detectar_estado_rm,
    fechar_rm,
    rm_esta_aberto,
)
from rpa_rm_faturamento.rm.rm_login import realizar_login
from rpa_rm_faturamento.rm.rm_navigation import acessar_solicitacao
from rpa_rm_faturamento.rm.rm_movimento import fechar_abas_tabcontrol
from rpa_rm_faturamento.services.lote_builder import build_lote_from_rpa
from rpa_rm_faturamento.services.faturamento_service import FaturamentoService
from rpa_rm_faturamento.services.fila_service import FilaService
from rpa_rm_faturamento.supabase.repository import DadosLofRepository, LotesRpaRepository
from rpa_rm_faturamento.utils.exceptions import (
    ErroCriticoRMError,
    ErroRMDuranteFaturamentoError,
    MovimentoEmFaturamentoError,
    MovimentoNaoEncontradoError,
)


class RpaOrchestrator:
    # Recuperação crítica: nº máximo de ciclos consecutivos (sem progresso) de
    # "fechar RM + reconstruir fila + reiniciar" antes de desistir e encerrar.
    # Zera a cada lote faturado com sucesso (progresso renova o orçamento).
    MAX_REBUILDS_CRITICOS = 3

    # Erros inesperados consecutivos (sem diálogo limpo do RM e sem progresso)
    # que são interpretados como RM em estado inválido → recuperação crítica.
    LIMITE_ERROS_INESPERADOS = 3

    def __init__(
        self,
        settings: Settings,
        repository: DadosLofRepository,
        lotes_repository: LotesRpaRepository,
        faturamento_service: FaturamentoService,
        fila_service: FilaService,
        logger: RpaLogger,
    ):
        self._settings = settings
        self._repository = repository
        self._lotes_repository = lotes_repository
        self._service = faturamento_service
        self._fila_service = fila_service
        self._logger = logger

    def run(self) -> None:
        """
        Ciclo principal do RPA.

        A cada iteração:
          1. Garante que o RM está operacional (update/login/tela conhecida).
             Se a tela do RM não puder ser detectada por tempo demais → erro
             crítico (recuperação no nível externo).
          2. Lê o próximo lote PENDENTE. Se não houver: encerra.
          3. Marca o lote como EM PROCESSAMENTO e busca seus itens A FATURAR.
          4. Executa o lote:
             a. MovimentoNaoEncontradoError (inclui movimento em faturamento /
                lock e erros padrão do RM): marca lote ERRO + itens NAO FATURADO
                (auditoria) e segue para o próximo lote. Itens ainda pendentes
                retornam à fila no próximo ciclo agendado.
             b. Erro inesperado: marca lote ERRO + itens NAO FATURADO e segue;
                acumula contador — se passar do limite, vira erro crítico.
          5. Sucesso: atualiza itens/lote para FATURADO e segue.

        Recuperação de erro CRÍTICO (RM travado / tela indetectável):
          fecha completamente o RM, reconstrói a fila a partir dos dados reais
          do RM (limpa + cria_produtos → validar → criar-lotes) e reinicia o
          ciclo. Limitado a MAX_REBUILDS_CRITICOS recuperações consecutivas.

        O rebuild NÃO ocorre por lote nem para locks transitórios — apenas na
        recuperação crítica, conforme desenhado.
        """
        auto.SetGlobalSearchTimeout(self._settings.auto_global_search_timeout)

        if not rm_esta_aberto(self._settings.rm_process_name):
            abrir_rm(self._settings.rm_executable_path)

        rebuilds_criticos = 0
        erros_inesperados = 0

        while True:
            try:
                # ── 1. Garante que o RM está operacional ──────────────────────
                self._garantir_estado_operacional()

                # ── 2. Leitura fresca: próximo lote PENDENTE ──────────────────
                lote_rpa = self._lotes_repository.fetch_proximo_lote_pendente()
                if not lote_rpa:
                    self._logger.info(
                        "SUPABASE",
                        "Nenhum lote com status PENDENTE — faturamento concluido",
                    )
                    break

                # ── 3. Marca lote como EM PROCESSAMENTO ──────────────────────
                try:
                    self._lotes_repository.marcar_lote_em_processamento(lote_rpa.id)
                except Exception:
                    self._logger.exception(
                        "SUPABASE",
                        "Falha ao marcar lote como EM PROCESSAMENTO; pulando lote",
                        lote_id=lote_rpa.id,
                        filial=lote_rpa.filial,
                        fornecedor=lote_rpa.cnpj_fornecedor,
                    )
                    time.sleep(1)
                    continue

                # ── 4. Busca itens do lote ────────────────────────────────────
                itens = self._repository.fetch_itens_por_lote(lote_rpa.id)
                if not itens:
                    self._logger.warning(
                        "SUPABASE",
                        "Lote sem itens A FATURAR; marcando lote como ERRO",
                        lote_id=lote_rpa.id,
                        filial=lote_rpa.filial,
                        fornecedor=lote_rpa.cnpj_fornecedor,
                    )
                    try:
                        self._lotes_repository.marcar_lote_erro(lote_rpa.id)
                    except Exception:
                        self._logger.exception(
                            "SUPABASE",
                            "Falha ao marcar lote como ERRO",
                            lote_id=lote_rpa.id,
                        )
                    time.sleep(1)
                    continue

                lote = build_lote_from_rpa(lote_rpa, itens, logger=self._logger)
                movimento_origem = ",".join(lote.movimentos_origem)

                # ── 5. Fecha abas residuais e navega para a tela correta ──────
                self._logger.info("NAVEGACAO", "Fechando abas residuais do TabControl")
                fechar_abas_tabcontrol()
                self._logger.info("NAVEGACAO", "Acessando Solicitacao de Compras")
                acessar_solicitacao()

                # ── 6. Log de início do lote ──────────────────────────────────
                self._logger.info(
                    "FATURAMENTO",
                    "Iniciando faturamento do lote",
                    lote_id=lote.lote_id,
                    filial=lote.filial,
                    fornecedor=lote.cnpj_fornecedor,
                    movimento_origem=movimento_origem,
                    payload={
                        "cod_comprador": lote.cod_comprador,
                        "centro_custo": lote.centro_custo,
                        "numero_lof": lote.numero_lof,
                        "quantidade_itens": len(lote.itens),
                        "nome_fornecedor": lote_rpa.nome_fornecedor,
                    },
                )

                # ── 7. Executa o lote ─────────────────────────────────────────
                try:
                    mensagem_rm = self._service.executar_lote(lote)

                except MovimentoNaoEncontradoError as exc:
                    # Diálogo de erro "limpo" do RM (lock em faturamento,
                    # movimento não encontrado, restrição de data, etc.).
                    # O RM respondeu de forma esperada → não conta como erro
                    # inesperado para o gatilho de recuperação crítica.
                    erros_inesperados = 0
                    self._tratar_erro_rm_no_lote(exc, lote, movimento_origem)
                    time.sleep(1)
                    continue

                except ErroCriticoRMError:
                    # Propaga para a recuperação crítica no nível externo.
                    raise

                except Exception:
                    # Erro inesperado: marca o lote para NÃO deixar pendência
                    # presa em EM PROCESSAMENTO e conta para detectar RM em
                    # estado ruim. (A reconciliação real virá do rebuild no
                    # próximo ciclo agendado ou numa recuperação crítica.)
                    erros_inesperados += 1
                    self._logger.exception(
                        "FATURAMENTO",
                        "Erro inesperado ao processar lote; marcando ERRO/NAO FATURADO",
                        lote_id=lote.lote_id,
                        filial=lote.filial,
                        fornecedor=lote.cnpj_fornecedor,
                        movimento_origem=movimento_origem,
                        payload={"erros_inesperados_consecutivos": erros_inesperados},
                    )
                    self._marcar_lote_falho(
                        lote, movimento_origem, "Erro inesperado durante o processamento"
                    )
                    if erros_inesperados >= self.LIMITE_ERROS_INESPERADOS:
                        raise ErroCriticoRMError(
                            f"{erros_inesperados} erros inesperados consecutivos — "
                            "RM provavelmente em estado invalido"
                        )
                    time.sleep(1)
                    continue

                # ── 8. Atualiza status para FATURADO ──────────────────────────
                try:
                    numero_movimento = self._repository.atualizar_itens_faturados(
                        lote.itens_ids, mensagem_rm
                    )
                    self._lotes_repository.marcar_lote_faturado(lote.lote_id, numero_movimento)
                    self._logger.info(
                        "SUPABASE",
                        "Faturamento do lote concluido com sucesso",
                        lote_id=lote.lote_id,
                        filial=lote.filial,
                        fornecedor=lote.cnpj_fornecedor,
                        movimento_origem=movimento_origem,
                        movimento_destino=numero_movimento,
                        payload={
                            "cod_comprador": lote.cod_comprador,
                            "centro_custo": lote.centro_custo,
                            "numero_lof": lote.numero_lof,
                            "quantidade_itens": len(lote.itens),
                            "nome_fornecedor": lote_rpa.nome_fornecedor,
                        },
                    )
                except Exception:
                    self._logger.exception(
                        "SUPABASE",
                        "Falha ao atualizar status para FATURADO; interrompendo para evitar reprocessamento",
                        lote_id=lote.lote_id,
                        filial=lote.filial,
                        fornecedor=lote.cnpj_fornecedor,
                        movimento_origem=movimento_origem,
                    )
                    break  # interrompe: risco de processar o mesmo lote duas vezes

                # Progresso real → renova os orçamentos de recuperação.
                erros_inesperados = 0
                rebuilds_criticos = 0
                time.sleep(1)  # pausa entre lotes antes de reler o banco

            except ErroCriticoRMError as exc:
                # ── Recuperação de erro crítico ───────────────────────────────
                if rebuilds_criticos >= self.MAX_REBUILDS_CRITICOS:
                    self._logger.error(
                        "RECUPERACAO",
                        "Limite de recuperacoes criticas atingido; encerrando execucao. "
                        "Itens pendentes serao tratados no proximo ciclo agendado.",
                        payload={"erro": str(exc), "max_rebuilds": self.MAX_REBUILDS_CRITICOS},
                    )
                    break

                rebuilds_criticos += 1
                self._logger.warning(
                    "RECUPERACAO",
                    "Erro critico detectado — fechando RM completamente e reconstruindo a fila",
                    payload={
                        "erro": str(exc),
                        "tentativa": rebuilds_criticos,
                        "max": self.MAX_REBUILDS_CRITICOS,
                    },
                )
                self._recuperar_rm_critico()
                erros_inesperados = 0
                continue

        self._logger.info("ORQUESTRADOR", "Execucao finalizada")

    # ──────────────────────────────────────────────────────────────────────────
    # Tratamento de erros de lote
    # ──────────────────────────────────────────────────────────────────────────

    def _tratar_erro_rm_no_lote(self, exc: Exception, lote, movimento_origem: str) -> None:
        """
        Marca o lote como ERRO e os itens como NAO FATURADO (auditoria) após um
        diálogo de erro esperado do RM, distinguindo a origem no log.
        """
        if isinstance(exc, MovimentoEmFaturamentoError):
            step_log = "SELECAO"
            msg_log = (
                "Movimento bloqueado (em faturamento por outra sessao); marcando "
                "lote como ERRO e itens como NAO FATURADO"
            )
        elif isinstance(exc, ErroRMDuranteFaturamentoError):
            step_log = "FATURAMENTO"
            msg_log = (
                "Erro RM durante faturamento; marcando lote como ERRO e itens "
                "como NAO FATURADO"
            )
        else:
            step_log = "SELECAO"
            msg_log = "Movimentos nao encontrados na tabela RM; marcando lote como ERRO"

        self._logger.warning(
            step_log,
            msg_log,
            lote_id=lote.lote_id,
            filial=lote.filial,
            fornecedor=lote.cnpj_fornecedor,
            movimento_origem=movimento_origem,
            payload={"erro": str(exc)},
        )
        try:
            self._repository.marcar_itens_nao_faturado(lote.itens_ids, mensagem=str(exc))
            self._lotes_repository.marcar_lote_erro(lote.lote_id, str(exc))
            self._logger.info(
                "SUPABASE",
                "Itens marcados como NAO FATURADO; lote marcado como ERRO",
                lote_id=lote.lote_id,
                filial=lote.filial,
                fornecedor=lote.cnpj_fornecedor,
                movimento_origem=movimento_origem,
            )
        except Exception:
            self._logger.exception(
                "SUPABASE",
                "Falha ao marcar itens/lote como NAO FATURADO/ERRO",
                lote_id=lote.lote_id,
                filial=lote.filial,
                fornecedor=lote.cnpj_fornecedor,
                movimento_origem=movimento_origem,
            )

    def _marcar_lote_falho(self, lote, movimento_origem: str, motivo: str) -> None:
        """Marca lote ERRO + itens NAO FATURADO após erro inesperado (best-effort)."""
        try:
            self._repository.marcar_itens_nao_faturado(lote.itens_ids, mensagem=motivo)
            self._lotes_repository.marcar_lote_erro(lote.lote_id, motivo)
        except Exception:
            self._logger.exception(
                "SUPABASE",
                "Falha ao marcar lote/itens apos erro inesperado",
                lote_id=lote.lote_id,
                movimento_origem=movimento_origem,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Recuperação crítica
    # ──────────────────────────────────────────────────────────────────────────

    def _recuperar_rm_critico(self) -> None:
        """
        Fecha completamente o RM, reconstrói a fila a partir dos dados reais do
        RM e reabre o RM. O ciclo seguinte aguarda o RM ficar operacional.
        """
        try:
            fechar_rm(self._settings.rm_process_name)
        except Exception:
            self._logger.exception("RECUPERACAO", "Falha ao fechar o RM")

        time.sleep(5)

        try:
            ok = self._fila_service.reconstruir()
            self._logger.info(
                "RECUPERACAO",
                "Reconstrucao da fila concluida" if ok else "Reconstrucao da fila falhou — seguindo mesmo assim",
            )
        except Exception:
            self._logger.exception("RECUPERACAO", "Falha inesperada ao reconstruir a fila")

        try:
            abrir_rm(self._settings.rm_executable_path)
        except Exception:
            self._logger.exception("RECUPERACAO", "Falha ao reabrir o RM")

        time.sleep(5)

    # ──────────────────────────────────────────────────────────────────────────
    # Estado operacional
    # ──────────────────────────────────────────────────────────────────────────

    def _garantir_estado_operacional(self):
        login_attempts = 0
        MAX_LOGIN_ATTEMPTS = 10
        # Tempo (s) tolerado em estado não reconhecido antes de declarar erro
        # crítico. Generoso para não disparar falso-positivo durante startup
        # lento do RM (AVD via RDP).
        MAX_DESCONHECIDO_S = 90
        desconhecido_inicio = None

        while True:
            estado = detectar_estado_rm(
                self._settings.rm_login_window_title,
                self._settings.rm_solicitacao_window_title,
            )

            if estado == EstadoRM.UPDATE:
                self._logger.info("UPDATE", "RM em atualizacao, aguardando finalizar")
                aguardar_fim_atualizacao()
                desconhecido_inicio = None
                continue

            if estado == EstadoRM.LOGIN:
                login_attempts += 1
                if login_attempts > MAX_LOGIN_ATTEMPTS:
                    raise RuntimeError(
                        f"Login falhou apos {MAX_LOGIN_ATTEMPTS} tentativas consecutivas. "
                        "Verifique se a sessao Windows esta ativa e as credenciais estao corretas."
                    )
                self._logger.info(
                    "LOGIN",
                    f"Tela de login detectada, autenticando (tentativa {login_attempts}/{MAX_LOGIN_ATTEMPTS})",
                )
                realizar_login(
                    self._settings.rm_usuario,
                    self._settings.rm_senha,
                    self._settings.rm_login_window_title,
                )
                desconhecido_inicio = None
                continue

            # Login bem-sucedido ou estado transitou para fora do LOGIN — reset
            login_attempts = 0

            if estado in (EstadoRM.PRINCIPAL, EstadoRM.SOLICITACAO):
                return estado

            # Estado desconhecido (None ou janela inesperada). Se persistir além
            # do limite, o RM está travado/indetectável → erro crítico.
            if desconhecido_inicio is None:
                desconhecido_inicio = time.time()
                self._logger.warning(
                    "ESTADO",
                    "Estado do RM nao reconhecido; aguardando estabilizar",
                )
            elif time.time() - desconhecido_inicio > MAX_DESCONHECIDO_S:
                raise ErroCriticoRMError(
                    "Nao foi possivel atingir um estado operacional do RM "
                    "(tela desconhecida ou RM nao responde)"
                )

            time.sleep(1)
