# -*- coding: utf-8 -*-


class RpaError(Exception):
    pass


class RpaTimeoutError(TimeoutError):
    pass


class MovimentoNaoEncontradoError(RpaError):
    """
    Levantada quando nenhum dos movimentos do lote foi localizado na tabela
    do RM (MarcarMovimentos retornou 0). O orquestrador captura essa exceção
    para marcar os itens do lote como NAO FATURADO e reiniciar o ciclo.
    """
    pass


class ErroRecebimentoRMError(MovimentoNaoEncontradoError):
    """
    Levantada quando o RM exibe uma janela de erro imediatamente após clicar
    em Receber (ex.: 'Não existem itens a serem faturados').
    Por herdar de MovimentoNaoEncontradoError, recebe o mesmo tratamento no
    orquestrador: registra o erro em log, marca os itens como NAO FATURADO
    e reinicia o ciclo.
    """
    pass


class ErroRMDuranteFaturamentoError(MovimentoNaoEncontradoError):
    """
    Levantada quando o RM exibe uma janela de erro durante o processamento do
    faturamento — após confirmar o movimento ou durante o progresso do wizard
    'Faturar/Receber' (ex.: 'Movimento fora das datas parametrizadas de
    fechamento de estoque!').
    Por herdar de MovimentoNaoEncontradoError, o orquestrador captura esta
    exceção, registra em log, marca os itens do lote como NAO FATURADO e
    reinicia o ciclo para o próximo lote.
    """
    pass


class MovimentoEmFaturamentoError(MovimentoNaoEncontradoError):
    """
    Levantada quando, ao clicar em Receber, o RM exibe o modal padrão
    (Name='RM', ClassName='#32770') com a mensagem
    'Movimento não pode ser alterado, movimento está em faturamento!'.

    Indica que um dos movimentos do lote está bloqueado porque está sendo
    faturado por outra sessão (tipicamente um humano operando o RM ao mesmo
    tempo). É um bloqueio TRANSITÓRIO: o movimento não é inválido, apenas está
    ocupado naquele instante.

    Por herdar de MovimentoNaoEncontradoError, o orquestrador captura esta
    exceção, marca o lote como ERRO e os itens como NAO FATURADO (para
    auditoria) e segue para o próximo lote. Os itens, se ainda pendentes,
    retornam à fila no próximo ciclo agendado (que reconstrói a fila a partir
    dos dados reais do RM).
    """
    pass


class ErroCriticoRMError(RpaError):
    """
    Levantada quando o RPA perde o controle do RM — não consegue detectar um
    estado operacional conhecido (tela desconhecida/sobreposta) ou acumula
    erros inesperados consecutivos que indicam o RM em estado inválido.

    Diferente das demais, NÃO é tratada no nível do lote: o orquestrador a
    captura no nível externo do ciclo, fecha completamente o RM, reconstrói a
    fila a partir da verdade real do RM e reinicia o ciclo (limitado por um
    número máximo de recuperações para evitar loop infinito).
    """
    pass


class ReconstrucaoFilaError(RpaError):
    """
    Levantada quando uma etapa da reconstrução da fila falha (limpeza no
    Supabase ou invocação de uma das edge functions de montagem da fila).
    """
    pass
