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


def _eh_principal(h, protegidas=()):
    if h in protegidas:
        return True
    return TRECHO_PRINCIPAL in win32.texto(h, 2000) and "Window.8" in win32.classe(h)


def janelas_extras(pid, protegidas=()):
    """Janelas a fechar. NUNCA inclui a principal (pelo handle guardado e pelo titulo) nem o login.
    Janela cujo titulo nao pode ser lido (RM ocupado) e ignorada nesta rodada - nunca fechar no escuro."""
    res = []
    for h in win32.janelas_topo(pid):
        if h in protegidas:
            continue
        t = win32.texto(h, 2000)
        if "Window.0" in win32.classe(h) and not t:
            continue  # janela auxiliar oculta do WinForms
        if not t and win32.classe(h) not in ("#32770", "#32768"):
            continue  # titulo ilegivel agora: nao arrisca
        if (TRECHO_PRINCIPAL in t and "Window.8" in win32.classe(h)) or t == "TOTVS":
            continue
        res.append(h)
    return res


def _texto_janela(h, limite=300):
    partes = []
    for c in win32.filhos(h, True):
        if any(k in win32.classe(c) for k in ("STATIC", "EDIT", "Static", "Edit")):
            t = win32.texto(c).strip()
            if t:
                partes.append(t)
    return " | ".join(partes)[:limite]


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


def limpar_janelas(ctx, timeout=90.0, max_fechamentos=15) -> bool:
    """Fecha o que sobrou de um lote. Limite de fechamentos: se o RM continuar abrindo janelas (ex.: 'Erro'
    em loop), desiste e devolve False (o orquestrador trata como erro critico)."""
    protegidas = {h for h in (getattr(ctx, "main", 0),) if h}
    fechamentos = 0
    vistas_texto = set()
    fim = time.perf_counter() + timeout
    while time.perf_counter() < fim:
        extras = janelas_extras(ctx.pid, protegidas)
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
        if alvo in protegidas or _eh_principal(alvo, protegidas):
            time.sleep(0.5)
            continue
        if fechamentos >= max_fechamentos:
            log(f"   limpeza: limite de {max_fechamentos} fechamentos atingido; desistindo")
            return False
        if t not in vistas_texto:
            vistas_texto.add(t)
            log(f"   limpeza: janela {t!r} conteudo: {_texto_janela(alvo)!r}")
        log(f"   limpeza: fechando {t!r}")
        win32.user32.PostMessageW(alvo, win32.WM_CLOSE, 0, 0)
        fechamentos += 1
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
    minha = win32.sessao_atual()
    procs = [p for p in psutil.process_iter(attrs=["name", "exe"])
             if eh_alvo(p) and win32.sessao_do_processo(p.pid) == minha]
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
