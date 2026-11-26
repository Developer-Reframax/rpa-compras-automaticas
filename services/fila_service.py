# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from rpa_rm_faturamento.utils.exceptions import ReconstrucaoFilaError


class FilaService:
    """
    Reconstrói a fila de faturamento a partir da verdade real do RM.

    Acionado apenas na recuperação de erro crítico (RM travado / tela
    indetectável). Limpa a fila ativa e reexecuta o mesmo pipeline de montagem
    usado pela edge function `executar_rpa` — porém SEM ligar VM e SEM registrar
    rpa_commands (etapas que não cabem ao robô em execução).

    A reconstrução é também a verificação de idempotência do refaturamento:
    como `cria_produtos_a_faturar` consulta as pendências reais do RM, um
    movimento já faturado (por humano ou pelo próprio RPA antes de uma falha)
    não reaparece na fila — evitando faturamento em duplicidade.

    Ordem (proposital, diferente da executar_rpa): cria → validar → criar-lotes.
    Validar antes de criar-lotes garante que os lotes nasçam apenas com itens
    válidos (em vez de nascerem e serem esvaziados pela validação depois).
    """

    # Ordem de invocação das edge functions na reconstrução.
    FUNCOES_ORDEM = (
        "cria_produtos_a_faturar",
        "validar-itens",
        "criar-lotes-faturamento",
    )

    def __init__(self, client, dados_repo, lotes_repo, logger):
        self._client = client
        self._dados_repo = dados_repo
        self._lotes_repo = lotes_repo
        self._logger = logger

    def reconstruir(self) -> bool:
        """
        Executa a reconstrução completa. Retorna True em caso de sucesso e
        False se a limpeza ou alguma etapa de montagem falhar (o orquestrador
        decide como prosseguir — tipicamente segue o ciclo, que relê a fila).
        """
        self._logger.info("REBUILD", "Iniciando reconstrucao da fila (limpeza + edge functions)")

        # 1) Limpeza — preserva FATURADO/ERRO/NAO FATURADO (auditoria),
        #    remove apenas a fila ativa que será repovoada dos dados reais.
        try:
            itens_removidos = self._dados_repo.deletar_itens_a_faturar()
            lotes_removidos = self._lotes_repo.deletar_lotes_nao_finais()
            self._logger.info(
                "REBUILD",
                "Fila antiga limpa",
                payload={
                    "itens_a_faturar_removidos": itens_removidos,
                    "lotes_removidos": lotes_removidos,
                },
            )
        except Exception:
            self._logger.exception("REBUILD", "Falha ao limpar a fila antiga; abortando reconstrucao")
            return False

        # 2) Reexecuta o pipeline de montagem na ordem cria → validar → criar-lotes.
        for nome in self.FUNCOES_ORDEM:
            try:
                resultado = self._invocar(nome)
                self._logger.info(
                    "REBUILD",
                    f"Edge function '{nome}' executada com sucesso",
                    payload=_resumir_resultado(resultado),
                )
            except ReconstrucaoFilaError as exc:
                self._logger.error(
                    "REBUILD",
                    f"Edge function '{nome}' falhou; reconstrucao abortada",
                    payload={"erro": str(exc)},
                )
                return False

        self._logger.info("REBUILD", "Reconstrucao da fila concluida com sucesso")
        return True

    def _invocar(self, nome: str) -> dict:
        """
        Invoca uma edge function via SDK do Supabase e devolve o JSON de retorno.

        Em status não-2xx o SDK levanta exceção (FunctionsHttpError); aqui a
        capturamos e relançamos como ReconstrucaoFilaError com a mensagem da
        função. `responseType=json` faz o retorno já vir como dict.
        """
        try:
            resp = self._client.functions.invoke(
                nome,
                invoke_options={"responseType": "json"},
            )
        except Exception as exc:
            raise ReconstrucaoFilaError(f"invoke '{nome}' falhou: {exc}") from exc

        # Defensivo: dependendo da versão/serialização, pode vir bytes em vez de dict.
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
    """Extrai do retorno de cada função apenas as contagens úteis para log."""
    if not isinstance(resultado, dict):
        return {}

    chaves = (
        "ok",
        "totalElegiveis",
        "totalInseridos",
        "total_itens",
        "itens_aprovados",
        "itens_reprovados",
        "message",
        "lotes_criados",
    )
    resumo: dict = {}
    for chave in chaves:
        if chave not in resultado:
            continue
        valor = resultado[chave]
        # lotes_criados pode ser uma lista grande — guarda só a contagem.
        if chave == "lotes_criados" and isinstance(valor, list):
            resumo["lotes_criados"] = len(valor)
        else:
            resumo[chave] = valor
    return resumo
