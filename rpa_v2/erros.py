# -*- coding: utf-8 -*-
"""Excecoes com a MESMA semantica do v1 (rpa_rm_faturamento/utils/exceptions.py)."""


class MovimentoNaoEncontradoError(Exception):
    """Dialogo de erro 'limpo' do RM / movimentos nao encontrados: lote ERRO, itens NAO FATURADO, segue."""


class ErroRecebimentoRMError(MovimentoNaoEncontradoError):
    """RM retornou erro ao criar o movimento destino (apos Executar no wizard)."""


class ErroRMDuranteFaturamentoError(MovimentoNaoEncontradoError):
    """RM mostrou erro durante a confirmacao do movimento."""


class ItemNaoEncontradoError(MovimentoNaoEncontradoError):
    """v2: item do lote nao esta no 1.1.15. O lote falha (movimento cancelado) - nunca gerar parcial."""


class ConferenciaFaturarError(MovimentoNaoEncontradoError):
    """v2: conferencia final do Faturar falhou. Movimento NAO e confirmado (cancelado), lote ERRO."""


class MovimentoEmFaturamentoError(MovimentoNaoEncontradoError):
    """Movimento bloqueado (em faturamento por outra sessao) - erro apos Receber."""


class ErroCriticoRMError(Exception):
    """RM travado / estado indetectavel: fecha o RM, reconstroi a fila e reabre."""


class ReconstrucaoFilaError(Exception):
    """Falha numa edge function da reconstrucao da fila."""
