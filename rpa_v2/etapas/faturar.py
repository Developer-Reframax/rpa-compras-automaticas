# -*- coding: utf-8 -*-
"""Etapas marcar movimentos, receber e wizard Faturar / Receber."""
import time

import w32 as win32  # noqa
import uia_min
import teclado
from comum import (rolar_pagina, checar_dialogo, esperar_janela, frente, ler_grid, exigir_colunas, texto_limpo)
from medidor import log
from erros import MovimentoNaoEncontradoError

TITULO_WIZARD = "Faturar / Receber"
COL_MOV = "Nº do Movimento"
COL_X = "[x]"


def _grid_da_visao(ctx):
    try:
        return win32.esperar(lambda: uia_min.mapa_nomes(ctx.form_sol, {"MainView"}).get("MainView"), 30,
                             "grid MainView da Solicitacao", intervalo=0.5)
    except win32.TempoEsgotado:
        raise RuntimeError("grid MainView da Solicitacao nao encontrado em 30s")


def _selecionado(v: str) -> bool:
    v = (v or "").strip().lower()
    return bool(v) and not v.startswith("não") and not v.startswith("nao")


def marcar(ctx):
    alvos = {m.lstrip("0") for m in ctx.lote["movimentos"]}
    grid = _grid_da_visao(ctx)
    frente(ctx.main)
    marcados = set()
    vistos_assinatura = None
    for pagina in range(40):
        headers, linhas, area = ler_grid(grid)
        exigir_colunas(headers, [COL_MOV, COL_X], "Solicitacao")
        if pagina == 0:
            ctx.med.marca("grid solicitacao lido", linhas=len(linhas))
        for ln in linhas:
            mov = ln.get(COL_MOV).lstrip("0")
            if mov not in alvos or mov in marcados:
                continue
            if _selecionado(ln.get(COL_X)):
                marcados.add(mov)
                continue
            cel = ln.celulas.get(COL_X)
            if cel is None:
                raise RuntimeError(f"linha do movimento {mov} sem celula [x]")
            l, t, r, b = cel.rect
            if cel.fora_da_tela or b > area[3] - 2 or t < area[1]:
                continue  # linha cortada na borda: sera tratada na proxima pagina
            # Clique UNICO e espera. Um 2o clique so depois de reler a linha e confirmar que ficou
            # desmarcada (clicar de novo no escuro DESMARCA, se o 1o clique tiver pegado com atraso).
            for tentativa in range(2):
                teclado.clicar(*cel.centro)
                try:
                    win32.esperar(lambda: _selecionado(ln.get_atual(COL_X)), 3, f"[x] do {mov}", intervalo=0.15)
                    marcados.add(mov)
                    break
                except win32.TempoEsgotado:
                    _, relidas, _ = ler_grid(grid)
                    atual = next((x for x in relidas if x.get(COL_MOV).lstrip("0") == mov), None)
                    if atual is not None and _selecionado(atual.get(COL_X)):
                        marcados.add(mov)
                        break
                    log(f"   [x] do {mov} continua desmarcado apos reler (tentativa {tentativa + 1})")
            else:
                raise RuntimeError(f"nao consegui marcar o movimento {mov}")
        if marcados >= alvos:
            break
        assinatura = tuple(ln.get(COL_MOV) for ln in linhas)
        if assinatura == vistos_assinatura:
            break  # fim do grid
        vistos_assinatura = assinatura
        if not rolar_pagina(grid):
            break  # sem barra de rolagem ou ja no fim
    faltam = alvos - marcados
    ctx.qtd_marcados = len(marcados)
    if not marcados:
        # v1: nenhum movimento encontrado -> MovimentoNaoEncontradoError (lote ERRO, segue)
        raise MovimentoNaoEncontradoError(
            f"Movimentos nao encontrados na tabela RM: {list(ctx.lote['movimentos'])}")
    if faltam:
        # v1 segue com os que encontrou (qtd > 0); registra o que faltou
        log(f"   ATENCAO: movimentos nao encontrados no grid: {sorted(faltam)}")
        ctx.log_warning("SELECAO", "Movimentos do lote nao encontrados na tabela do RM (parcial)",
                        payload={"nao_encontrados": sorted(faltam)})
    # conferencia final: os marcados continuam marcados (clique em linha nao desmarcou outra)
    headers, linhas, _ = ler_grid(grid)
    visiveis = {ln.get(COL_MOV).lstrip("0"): _selecionado(ln.get(COL_X)) for ln in linhas}
    perdidos = [m for m in marcados if m in visiveis and not visiveis[m]]
    if perdidos:
        raise RuntimeError(f"movimentos desmarcados apos marcar outros: {perdidos}")
    ctx.med.marca("movimentos marcados", movimentos=sorted(marcados))


def receber(ctx):
    tb = uia_min.mapa_nomes(ctx.form_sol, {"customToolBar"}).get("customToolBar")
    if not tb:
        raise RuntimeError("toolbar com o botao Receber nao encontrada")
    arv = uia_min.ler_arvore(tb)
    b = arv.busca(lambda n: n.tipo == uia_min.T_BUTTON and n.nome == "Receber")
    if b is None:
        raise RuntimeError("botao Receber nao encontrado")
    frente(ctx.main)
    teclado.clicar(*b.centro)
    esperar_janela(ctx, 30, "janela Faturar / Receber", exato=TITULO_WIZARD)


def auto_valor(el) -> str:
    """Value atual de um elemento UIA (1 chamada)."""
    import uiautomation as auto
    try:
        return auto.Control.CreateControlFromElement(el).GetValuePattern().Value or ""
    except Exception:
        return ""


def _botao_next(jan):
    for c in win32.filhos(jan, True):
        if "BUTTON" in win32.classe(c) and texto_limpo(win32.texto(c)).startswith(("Avançar", "Executar")):
            return c
    return 0


def wizard(ctx):
    jan = esperar_janela(ctx, 10, "janela Faturar / Receber", exato=TITULO_WIZARD)
    frente(jan)
    # Pagina 1: "Agrupar Todos" (radio nativo) e Avancar (Alt+R), ate o botao virar "Executar".
    for _ in range(5):
        checar_dialogo(ctx, "wizard")
        nxt = win32.esperar(lambda: _botao_next(jan), 10, "botao Avancar/Executar")
        if texto_limpo(win32.texto(nxt)).startswith("Executar"):
            break
        radio = win32.achar_filho(jan, classe_contem="BUTTON", texto_limpo="Agrupar Todos")
        if radio and not uia_min.radio_marcado(radio):
            win32.bm_click(radio)
            win32.esperar(lambda: uia_min.radio_marcado(radio), 3, "radio Agrupar Todos marcado")
        antes = win32.texto(nxt)
        frente(jan)
        teclado.atalho("alt+r")
        win32.esperar(lambda: win32.texto(nxt) != antes or not win32.visivel(radio or nxt)
                      or win32.dialogo_rm(ctx.pid), 15, "wizard avancar")
    else:
        raise RuntimeError("wizard nao chegou na pagina Executar")
    checar_dialogo(ctx, "wizard")

    # Pagina 2: grid de tipos de movimento (DataGridView pequeno). Confere/seleciona 1.1.15.
    destino = ctx.lote["tipo_mov_destino"]
    grid = uia_min.mapa_nomes(jan, {"grdTipoMovimento"}).get("grdTipoMovimento")
    if not grid:
        raise RuntimeError("grid grdTipoMovimento nao encontrado")

    def celula_destino():
        a = uia_min.ler_arvore(grid)
        return a.busca(lambda n: n.nome.startswith("Código Row") and n.valor == destino)

    def focada_destino():
        try:
            f = uia_min.IUIA.GetFocusedElement()
            nome = f.CurrentName or ""
            valor = auto_valor(f)
            return (nome, valor) if nome.startswith("Código Row") and valor == destino else None
        except Exception:
            return None

    # SEMPRE seleciona a linha do destino e confere a celula focada antes de executar
    # (nao supor que a primeira linha esteja selecionada). Ate 3 tentativas; sem conferencia, NAO executa.
    nome = None
    for tentativa in range(1, 4):
        cel = win32.esperar(celula_destino, 15, f"tipo {destino} no grid do wizard", intervalo=0.2)
        frente(jan)
        teclado.clicar(*cel.centro)
        try:
            nome, _ = win32.esperar(focada_destino, 3, f"celula focada = {destino}", intervalo=0.1)
            break
        except win32.TempoEsgotado:
            log(f"   wizard: {destino} nao ficou focado (tentativa {tentativa})")
            time.sleep(0.5)
    if nome is None:
        raise RuntimeError(f"wizard: nao consegui selecionar o tipo {destino}; NAO executei")
    ctx.med.marca("wizard: tipo destino selecionado e conferido", celula=nome)
    frente(jan)
    teclado.atalho("alt+r")  # Executar
    ctx.mov = esperar_janela(ctx, 180, "janela do movimento 1.1.15", prefixo="Movimento: -1 - " + destino)
