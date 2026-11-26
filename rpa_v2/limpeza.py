# -*- coding: utf-8 -*-
"""Volta o RM para a janela principal depois de um erro no lote, SO por Win32 (sem acessibilidade):
fecha dialogos, janela do item, movimento, wizard e telas de filtro. Se nao conseguir, o orquestrador
trata como erro critico (fecha o RM, reconstroi a fila e reabre - igual ao v1)."""
import time

import psutil

import w32 as win32  # noqa
import teclado
from medidor import log

TRECHO_PRINCIPAL = "TOTVS Linha RM"


def _eh_principal(h):
    return TRECHO_PRINCIPAL in win32.titulo(h) and "Window.8" in win32.classe(h)


def janelas_extras(pid):
    res = []
    for h in win32.janelas_topo(pid):
        if _eh_principal(h) or win32.titulo(h) == "TOTVS":  # principal e tela de login nunca sao fechadas
            continue
        if "Window.0" in win32.classe(h) and not win32.titulo(h):
            continue  # janela auxiliar oculta do WinForms
        res.append(h)
    return res


def _botao_para(msg, botoes):
    m = (msg or "").lower()
    if "cancelar a execu" in m and "No" in botoes:
        return "No"      # nao cancela um processo de faturamento em andamento
    if "cancelamento" in m and "Yes" in botoes:
        return "Yes"     # 'Confirma o cancelamento das alteracoes?' -> descarta o movimento com erro
    if "confirma a altera" in m and "No" in botoes:
        return "No"      # nao salva o item de um lote que falhou
    for b in ("OK", "No", "Yes"):
        if b in botoes:
            return b
    return next(iter(botoes), None)


def limpar_janelas(ctx, timeout=90.0) -> bool:
    fim = time.perf_counter() + timeout
    while time.perf_counter() < fim:
        extras = janelas_extras(ctx.pid)
        if not extras:
            return True
        d = win32.dialogo_rm(ctx.pid)
        if d:
            h, msg, botoes = d
            b = _botao_para(msg, botoes)
            log(f"   limpeza: dialogo {msg!r} -> {b}")
            if b:
                win32.clicar_botao_dialogo(h, botoes[b])
            time.sleep(0.6)
            continue
        menus = [h for h in extras if win32.classe(h) == "#32768"]
        if menus:
            teclado.atalho("esc")
            time.sleep(0.3)
            continue
        alvo = next((h for h in extras if win32.habilitada(h)), 0)
        if not alvo:
            time.sleep(0.5)  # ex.: processamento em andamento (janelas desabilitadas)
            continue
        t = win32.titulo(alvo)
        if t == "Faturamento":
            time.sleep(0.5)
            continue
        if t == "Faturar / Receber":
            fechar = win32.achar_filho(alvo, classe_contem="BUTTON", texto_limpo="Fechar")
            if fechar:
                log("   limpeza: Faturar / Receber -> Fechar")
                win32.bm_click(fechar)
                time.sleep(0.8)
                continue
        log(f"   limpeza: fechando {t!r}")
        win32.user32.PostMessageW(alvo, win32.WM_CLOSE, 0, 0)
        time.sleep(0.8)
    return False


def fechar_rm(process_name="RM.exe", exe=None, timeout=10.0) -> int:
    """Como o v1 (state_machine.fechar_rm): terminate e kill no que sobrar - mas so no RM do caminho
    configurado (nao derruba o RM de homologacao/producao que nao e o do robo)."""
    import os
    alvo = (process_name or "").lower()

    def eh_alvo(p):
        if (p.info.get("name") or "").lower() != alvo:
            return False
        if not exe:
            return True
        try:
            return os.path.normcase(p.info.get("exe") or "") == os.path.normcase(os.path.abspath(exe))
        except Exception:
            return False
    procs = [p for p in psutil.process_iter(attrs=["name", "exe"]) if eh_alvo(p)]
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    try:
        _, vivos = psutil.wait_procs(procs, timeout=timeout)
    except Exception:
        vivos = procs
    for p in vivos:
        try:
            p.kill()
        except Exception:
            pass
    return len(procs)
