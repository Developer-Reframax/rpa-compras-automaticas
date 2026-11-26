# -*- coding: utf-8 -*-
"""Etapas login, navegacao e solicitacao (filtro)."""
import subprocess
import time

import psutil

import w32 as win32  # noqa
import uia_min
import teclado
from comum import (checar_dialogo, limpar_campo, esperar_janela, esperar_sumir, frente, digitar_campo, focar)
from medidor import log

TITULO_LOGIN = "TOTVS"
TRECHO_PRINCIPAL = "TOTVS Linha RM"
TITULO_SOL = "Solicitação de Compras (Gestão Compras)"
TITULO_FILTROS = "Filtros - Solicitação de Compras (Gestão Compras)"
FILTRO_PENDENTES = "09 - Pendentes/Parc.Recebido"


def _mesmo_exe(a, b):
    import os
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def achar_pid(processo="RM.exe", exe=None):
    """PID do RM. Com exe, so aceita o processo daquele caminho (homologacao e producao tem o mesmo
    nome RM.exe: nunca faturar no RM errado)."""
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info["name"] or "").lower() != processo.lower():
            continue
        if exe and not _mesmo_exe(p.info.get("exe") or "", exe):
            continue
        return p.pid
    return 0


def janela_principal(ctx):
    for h in win32.janelas_topo(ctx.pid):
        if TRECHO_PRINCIPAL in win32.titulo(h) and "Window.8" in win32.classe(h):
            return h
    return 0


# ------------------------------------------------------------------ login
def login(ctx):
    if not ctx.pid:
        log(f"   RM nao esta aberto: iniciando {ctx.cred['exe']}")
        subprocess.Popen([ctx.cred["exe"]])
        ctx.pid = win32.esperar(lambda: achar_pid(ctx.cred["processo"], ctx.cred["exe"]), 60, "processo RM")

    def estado():
        m = janela_principal(ctx)
        if m:
            return ("principal", m)
        lg = win32.achar_janela(ctx.pid, exato=TITULO_LOGIN)
        if lg:
            return ("login", lg)
        return None

    tipo, h = win32.esperar(estado, 180, "tela de login ou janela principal", intervalo=0.25)
    if tipo == "principal":
        log("   ja logado (janela principal aberta)")
        ctx.main = h
        return

    # Campos por Win32: os dois EDIT visiveis da tela; o de senha tem ES_PASSWORD.
    edits = [c for c in win32.filhos(h, True) if "EDIT" in win32.classe(c)]
    senha_h = next((c for c in edits if win32.estilo(c) & win32.ES_PASSWORD), 0)
    usuario_h = next((c for c in edits if c != senha_h), 0)
    if not (usuario_h and senha_h):
        raise RuntimeError(f"tela de login: campos nao encontrados (edits={edits})")
    frente(h)
    if win32.texto(usuario_h).strip().lower() != ctx.cred["usuario"].strip().lower():
        digitar_campo(usuario_h, ctx.cred["usuario"], tab=False)
    digitar_campo(senha_h, ctx.cred["senha"], tab=False)
    teclado.atalho("enter")

    def pronto():
        d = win32.dialogo_rm(ctx.pid)
        if d:
            checar_dialogo(ctx, "login")
        return janela_principal(ctx)

    ctx.main = win32.esperar(pronto, 180, "janela principal apos login", intervalo=0.25)
    # espera o RM terminar de carregar (janela habilitada e titulo final sem o prefixo de versao)
    win32.esperar(lambda: win32.habilitada(ctx.main), 60, "janela principal habilitada", intervalo=0.25)


# ------------------------------------------------------------------ navegacao
def _form_solicitacao(ctx):
    """MDI child ja aberto da Solicitacao de Compras (titulo comeca com TITULO_SOL + ' - Filial')."""
    for c in win32.filhos(ctx.main):
        t = win32.titulo(c)
        if t.startswith(TITULO_SOL + " - Filial") and "Window.8" in win32.classe(c):
            return c
    return 0


def navegacao(ctx):
    ctx.main = ctx.main or janela_principal(ctx)
    if not ctx.main:
        raise RuntimeError("janela principal do RM nao encontrada")
    # Fecha a visao antiga da Solicitacao (se houver) para comecar limpo, como o v1.
    antigo = _form_solicitacao(ctx)
    if antigo:
        log("   fechando visao antiga da Solicitacao de Compras")
        win32.user32.PostMessageW(antigo, win32.WM_CLOSE, 0, 0)
        win32.esperar(lambda: not win32.existe(antigo) or not win32.visivel(antigo), 10, "fechar visao antiga")

    if win32.achar_janela(ctx.pid, exato=TITULO_SOL):
        log("   tela Solicitacao ja aberta")
        return
    # KeyTips (Alt,C,O,S) testadas: nao abriram a tela e deixaram o ribbon em modo KeyTip,
    # engolindo o clique seguinte. Caminho usado: le o ribbon (1 chamada), seleciona a aba e clica.
    rib = uia_min.mapa_nomes(ctx.main, {"mdiRibbonControl"}).get("mdiRibbonControl")
    if not rib:
        raise RuntimeError("ribbon nao encontrado")
    arv = uia_min.ler_arvore(rib)
    aba = arv.busca(lambda n: n.tipo == uia_min.T_TABITEM and n.nome == "Compras")
    aba.selecionar()
    def botao():
        a = uia_min.ler_arvore(rib)
        return a.busca(lambda n: n.tipo == uia_min.T_BUTTON and n.nome == "Solicitação de Compra")
    # Clique de mouse: Invoke via UIA fica bloqueado enquanto o RM mostra a janela modal.
    # Ate 3 tentativas (apos fechar um lote com erro o RM as vezes ignora o 1o clique).
    for tentativa in range(1, 4):
        aba = uia_min.ler_arvore(rib).busca(lambda n: n.tipo == uia_min.T_TABITEM and n.nome == "Compras")
        if aba is not None:
            try:
                aba.selecionar()
            except Exception:
                pass
        b = win32.esperar(botao, 5, "botao Solicitacao de Compra", intervalo=0.2)
        frente(ctx.main)
        teclado.clicar(*b.centro)
        try:
            esperar_janela(ctx, 15, "janela Solicitacao", exato=TITULO_SOL)
            break
        except win32.TempoEsgotado:
            log(f"   tela Solicitacao nao abriu (tentativa {tentativa}); clicando de novo")
            teclado.atalho("esc")
    else:
        raise win32.TempoEsgotado("janela Solicitacao nao abriu apos 3 tentativas")
    ctx.med.marca("ribbon: aba Compras + clique em Solicitacao de Compra")


# ------------------------------------------------------------------ solicitacao + filtro
def solicitacao(ctx):
    lote = ctx.lote
    jan = esperar_janela(ctx, 15, "janela Solicitacao", exato=TITULO_SOL)
    frente(jan)
    m = uia_min.mapa_nomes(jan, {"lkpCODFILIALCode", "cTipoMovCode", "btnOk"})
    if len(m) < 3:
        raise RuntimeError(f"campos da tela Solicitacao nao encontrados: {m}")
    filial_h, tipo_h, ok_h = m["lkpCODFILIALCode"], m["cTipoMovCode"], m["btnOk"]

    if win32.texto(filial_h).strip() != lote["filial"]:
        digitar_campo(filial_h, lote["filial"], tab=True)
    # Tipo de movimento: campo com mascara; caractere a caractere (protecao do v1 para AVD).
    focar(tipo_h)
    limpar_campo()
    teclado.atalho("home")
    teclado.digitar(lote["tipo_mov_origem"], intervalo=0.05)
    teclado.atalho("tab")
    win32.esperar(lambda: win32.habilitada(ok_h), 10, "botao OK habilitado")
    lido = win32.texto(tipo_h)
    if lido.replace("_", "") != lote["tipo_mov_origem"]:
        raise RuntimeError(f"tipo de movimento ficou {lido!r}")
    win32.bm_click(ok_h)

    # Tela de filtros: seleciona o filtro e Executar (Alt+E).
    filtros = esperar_janela(ctx, 30, "tela de Filtros", exato=TITULO_FILTROS)
    frente(filtros)
    lista_h = win32.esperar(lambda: win32.achar_filho(filtros, classe_contem="SysListView32"), 10, "lista de filtros")
    arv = uia_min.ler_arvore(lista_h)
    item = arv.busca(lambda n: n.tipo == uia_min.T_LISTITEM and n.nome == FILTRO_PENDENTES)
    if item is None:
        raise RuntimeError(f"filtro '{FILTRO_PENDENTES}' nao encontrado na lista")
    item.selecionar()
    frente(filtros)
    teclado.atalho("alt+e")
    try:
        esperar_sumir(filtros, 8, "tela de Filtros fechar (Alt+E)")
        ctx.med.marca("filtro via Alt+E")
    except win32.TempoEsgotado:
        log("   Alt+E nao executou; duplo clique no filtro (como o v1)")
        teclado.clicar(*item.centro, duplo=True)
        esperar_sumir(filtros, 15, "tela de Filtros fechar (duplo clique)")
    checar_dialogo(ctx, "filtro")

    # Visao da Solicitacao aberta com o grid carregado.
    ctx.form_sol = win32.esperar(lambda: _form_solicitacao(ctx), 60, "visao da Solicitacao aberta", intervalo=0.2)
