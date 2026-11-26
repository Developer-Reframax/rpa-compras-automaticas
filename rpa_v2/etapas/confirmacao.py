# -*- coding: utf-8 -*-
"""Etapa confirmacao: OK no 1.1.15, le o numero gerado e fecha as janelas do faturamento."""
import re
import time

import w32 as win32  # noqa
import teclado
from comum import checar_dialogo, frente, ErroRM, esperar_janela
from etapas.movimento import _mov
from medidor import log

RE_NUMERO = re.compile(r"N[uú]mero:\s*(\d+)")
TITULO_AVISO = "Mensagens de Aviso do Movimento"


def confirmacao(ctx):
    mov = _mov(ctx)
    frente(mov)
    teclado.atalho("alt+o")

    # 1) Mensagens de Aviso (numero gerado) ou erro do RM
    def aviso():
        checar_dialogo(ctx, "confirmacao do movimento")
        return win32.achar_janela(ctx.pid, exato=TITULO_AVISO)
    jan_aviso = win32.esperar(aviso, 180, "Mensagens de Aviso do Movimento", intervalo=0.2)
    edit = win32.esperar(lambda: win32.achar_filho(jan_aviso, classe_contem="EDIT"), 5, "texto do aviso")
    msg = win32.texto(edit, 1000)
    log(f"   aviso: {msg!r}")
    mt = RE_NUMERO.search(msg)
    if not mt:
        raise ErroRM(f"numero do movimento nao encontrado na mensagem: {msg!r}")
    ctx.numero_gerado = mt.group(1)
    ctx.mensagem_rm = msg
    ctx.med.marca("movimento gerado", numero=ctx.numero_gerado)
    ok = win32.achar_filho(jan_aviso, classe_contem="BUTTON")
    if ok:
        win32.bm_click(ok)
    else:
        frente(jan_aviso)
        teclado.atalho("enter")
    win32.esperar(lambda: not win32.existe(jan_aviso) or not win32.visivel(jan_aviso), 15, "fechar aviso")

    # 2) Janela do movimento gerado: "Movimento: <N> - 1.1.15" -> OK (Alt+O)
    destino = ctx.lote["tipo_mov_destino"]
    def gerado():
        checar_dialogo(ctx, "movimento gerado")
        return win32.achar_janela(ctx.pid, prefixo=f"Movimento: {ctx.numero_gerado} - {destino}")
    jan_ger = win32.esperar(gerado, 120, f"janela do movimento {ctx.numero_gerado}", intervalo=0.2)
    win32.esperar(lambda: win32.habilitada(jan_ger), 30, "movimento gerado habilitado", intervalo=0.2)
    frente(jan_ger)
    teclado.atalho("alt+o")
    win32.esperar(lambda: not win32.existe(jan_ger) or not win32.visivel(jan_ger), 60, "fechar movimento gerado",
                  intervalo=0.2)

    # 3) Faturar / Receber: a tela final mostra "Execucao concluida" e o botao "&Fechar" (Alt+F).
    #    NAO usar Alt+C: abre "Deseja cancelar a execucao deste processo?".
    # A janela fica oculta enquanto o movimento gerado esta aberto e reaparece depois: espera ela voltar.
    try:
        wiz = esperar_janela(ctx, 30, "Faturar / Receber reaparecer", exato="Faturar / Receber")
    except win32.TempoEsgotado:
        wiz = 0
        log("   ATENCAO: 'Faturar / Receber' nao reapareceu em 30s")
    if wiz:
        def fechar_pronto():
            checar_dialogo(ctx, "processamento do faturamento")
            if not win32.habilitada(wiz) or win32.achar_janela(ctx.pid, exato="Faturamento"):
                return 0
            return win32.achar_filho(wiz, classe_contem="BUTTON", texto_limpo="Fechar")
        fechar = win32.esperar(fechar_pronto, 300, "fim do processamento (botao Fechar)", intervalo=0.3)
        resultado = [win32.texto(c) for c in win32.filhos(wiz, True)
                     if "STATIC" in win32.classe(c) and "conclu" in win32.texto(c).lower()]
        ctx.med.marca("processo do faturamento", resultado=resultado)
        if not any("sucesso" in r.lower() for r in resultado):
            log(f"   ATENCAO: resultado do processo sem 'sucesso': {resultado}")
        win32.bm_click(fechar)
        win32.esperar(lambda: not win32.existe(wiz) or not win32.visivel(wiz), 20, "fechar Faturar / Receber")
    ctx.med.marca("faturamento concluido", numero=ctx.numero_gerado)
    log(f"*** MOVIMENTO GERADO: {ctx.numero_gerado}")
