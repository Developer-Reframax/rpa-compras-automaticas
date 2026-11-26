# -*- coding: utf-8 -*-
"""Etapa itens: marca Faturar no grid e percorre os itens com Ctrl+PgDn dentro da janela do item,
preenchendo preco (e tributos) so dos itens a faturar."""
import re
import time

import w32 as win32  # noqa
import uia_min
import teclado
from config_v2 import num_br
from comum import (limpar_campo, rolar_pagina, checar_dialogo, frente, focar, digitar_campo, abrir_secao, ler_grid,
                   exigir_colunas, so_digitos, esperar_texto)
from etapas.movimento import _mov
from medidor import log
from erros import ConferenciaFaturarError, ItemNaoEncontradoError

COL_SEQ = "Nº Sequencial"
COL_PRD = "Produto"
COL_FAT = "Faturar"
RE_TITULO_ITEM = re.compile(r"^Item de Movimento:\s*(\d+)\s*-\s*(\S+)")


# ------------------------------------------------------------------ grid de itens
def _grid_itens(ctx, mov):
    def achar():
        return uia_min.mapa_nomes(mov, {"MainView"}).get("MainView")
    return win32.esperar(achar, 15, "grid de itens do 1.1.15", intervalo=0.3)


def _eh_true(v):
    return (v or "").strip().lower() in ("true", "sim", "verdadeiro", "1", "selecionado")


def _num(v) -> float:
    try:
        return float(str(v if v is not None else 0).replace(",", "."))
    except Exception:
        return 0.0


def _confirmar_faturar(ctx, grid, clicados, rodadas=3):
    """O grid so grava o valor do checkbox quando o foco sai da celula; ler logo apos o clique mostra
    o valor ANTIGO. Por isso: clica UMA vez em cada alvo, tira o foco da celula (clique no Nº Sequencial
    da ultima linha clicada), rele as linhas e so clica de novo nas que realmente ficaram falsas.
    Nunca repetir o clique sem essa conferencia (o 2o clique DESMARCA)."""
    pend = list(clicados)  # [(it, seq)]
    for rodada in range(1, rodadas + 1):
        ultimo_seq = pend[-1][1]
        _, linhas, _ = ler_grid(grid)
        por_seq = {ln.get(COL_SEQ): ln for ln in linhas}
        neutra = por_seq.get(ultimo_seq)
        if neutra is not None and not neutra.celulas[COL_SEQ].fora_da_tela:
            teclado.clicar(*neutra.celulas[COL_SEQ].centro)
        time.sleep(0.4)
        _, linhas, _ = ler_grid(grid)
        por_seq = {ln.get(COL_SEQ): ln for ln in linhas}
        falsos = [(it, seq) for it, seq in pend if seq in por_seq and not _eh_true(por_seq[seq].get(COL_FAT))]
        if not falsos:
            return
        log(f"   Faturar ainda falso apos gravar (rodada {rodada}): {[it['cod_prd'] for it, _ in falsos]}")
        if rodada == rodadas:
            break
        for it, seq in falsos:
            cel = por_seq[seq].celulas.get(COL_FAT)
            if cel is None or cel.fora_da_tela:
                raise RuntimeError(f"celula Faturar fora da tela para {it['cod_prd']}")
            teclado.clicar(*cel.centro)
            time.sleep(0.15)
        pend = falsos
    raise RuntimeError(f"nao consegui marcar Faturar dos itens {[it['cod_prd'] for it, _ in pend]}")


def _levar_linha_para_tela(linhas, alvo_ln):
    """Linha fora da area visivel: clica no Nº Sequencial de uma linha visivel e anda com as setas ate a
    linha alvo - o grid rola sozinho ate a linha focada. (A leitura leve traz TODAS as linhas, inclusive
    as fora da tela, na ordem do grid.)"""
    visiveis = [l for l in linhas if not l.celulas[COL_SEQ].fora_da_tela]
    if not visiveis:
        return False
    idx_alvo = linhas.index(alvo_ln)
    base = min(visiveis, key=lambda l: abs(linhas.index(l) - idx_alvo))
    teclado.clicar(*base.celulas[COL_SEQ].centro)
    time.sleep(0.2)
    passos = idx_alvo - linhas.index(base)
    tecla = "down" if passos > 0 else "up"
    for _ in range(abs(passos)):
        teclado.atalho(tecla, pausa=0.04)
    time.sleep(0.4)
    return True


def _caixa_pesquisa(ctx):
    """Caixa 'Search Box' do painel de pesquisa do grid (DevExpress Find Panel), se estiver aberta."""
    return uia_min.mapa_nomes(ctx.mov, {"Search Box"}, classes=["EDIT"]).get("Search Box")


def _pesquisar(ctx, grid, linhas, texto):
    """Plano B para linha fora da tela: pesquisa do grid (Ctrl+F) com o codigo do produto. O grid passa
    a mostrar so as linhas que contem o texto. Retorna o hwnd da caixa de pesquisa (para limpar depois)."""
    caixa = _caixa_pesquisa(ctx)
    if not caixa:
        visiveis = [l for l in linhas if not l.celulas[COL_SEQ].fora_da_tela]
        if not visiveis:
            return 0
        teclado.clicar(*visiveis[0].celulas[COL_SEQ].centro)
        time.sleep(0.2)
        teclado.atalho("ctrl+f")
        try:
            caixa = win32.esperar(lambda: _caixa_pesquisa(ctx), 3, "painel de pesquisa do grid", intervalo=0.2)
        except win32.TempoEsgotado:
            log("   pesquisa do grid nao abriu (Ctrl+F)")
            return 0
    digitar_campo(caixa, texto, tab=False)
    teclado.atalho("enter")
    time.sleep(0.8)
    log(f"   pesquisa do grid: {texto}")
    return caixa


def _limpar_pesquisa(caixa):
    """Tira o filtro da pesquisa (todas as linhas voltam) e fecha o painel."""
    if not caixa or not win32.existe(caixa):
        return
    digitar_campo(caixa, "", tab=False)
    teclado.atalho("enter")
    time.sleep(0.6)
    teclado.atalho("esc")
    time.sleep(0.3)


def _focar_linha_visivel(linhas, ultima=False):
    """Clica no Nº Sequencial de uma linha visivel (da foco de teclado ao grid e grava edicoes pendentes)."""
    visiveis = [l for l in linhas if not l.celulas[COL_SEQ].fora_da_tela]
    if not visiveis:
        return False
    teclado.clicar(*(visiveis[-1] if ultima else visiveis[0]).celulas[COL_SEQ].centro)
    time.sleep(0.2)
    return True


def _marcar_visiveis(ctx, grid, linhas, pend, usadas):
    """Marca (1 clique) os alvos cujas linhas estao visiveis nesta leitura e confere apos gravar."""
    clicados = []
    for it in list(pend):
        cands = [ln for ln in linhas if ln.get(COL_PRD) == it["cod_prd"] and ln.get(COL_SEQ) not in usadas]
        if not cands:
            continue
        ln = next((c for c in cands if it.get("seq") and c.get(COL_SEQ) == str(it["seq"])), cands[0])
        ja_marcado = _eh_true(ln.get(COL_FAT))
        cel = ln.celulas.get(COL_FAT)
        if not ja_marcado and (cel is None or cel.fora_da_tela):
            continue  # ainda fora da area visivel: proxima pagina
        it["_seq_rm"] = ln.get(COL_SEQ)
        usadas.add(it["_seq_rm"])
        pend.remove(it)
        if not ja_marcado:
            teclado.clicar(*cel.centro)   # UM clique; conferencia depois que o grid gravar
            time.sleep(0.15)
            clicados.append((it, it["_seq_rm"]))
    if clicados:
        _confirmar_faturar(ctx, grid, clicados)


def marcar_faturar(ctx, grid, alvos):
    """Marca Faturar de cada alvo numa linha DISTINTA do grid (mesmo produto pode repetir quando ha
    varias solicitacoes). O RM so expoe as linhas proximas da area visivel, entao:
      1. percorre o grid por paginas (clique numa linha + PgDn) marcando o que aparecer;
      2. plano B: pesquisa do grid (Ctrl+F) pelo codigo de cada produto que ainda faltar;
      3. item que nem assim aparece: FALHA o lote (nunca gerar movimento parcial).
    Retorna (celula Nº Sequencial da 1a linha, houve_rolagem)."""
    usadas, pend = set(), list(alvos)
    primeira, rolou = None, False
    vistas = set()
    linhas = []
    for pagina in range(200):
        headers, linhas, area = ler_grid(grid)
        if pagina == 0:
            exigir_colunas(headers, [COL_SEQ, COL_PRD, COL_FAT], "de itens")
            ctx.med.marca("grid de itens lido", linhas=len(linhas), colunas=headers)
            primeira = linhas[0].celulas.get(COL_SEQ) if linhas else None
        _marcar_visiveis(ctx, grid, linhas, pend, usadas)
        if not pend:
            break
        seqs = {ln.get(COL_SEQ) for ln in linhas}
        if pagina > 0 and seqs <= vistas:
            break  # nenhuma linha nova: fim do grid
        vistas |= seqs
        if not _focar_linha_visivel(linhas, ultima=True):
            break
        teclado.atalho("pgdn")
        time.sleep(0.5)
        rolou = True
    # plano B: pesquisa pelo codigo do produto (filtra o grid inteiro, inclusive linhas nunca lidas)
    for it in list(pend):
        caixa = _pesquisar(ctx, grid, linhas, it["cod_prd"])
        if not caixa:
            break
        rolou = True
        try:
            _, linhas, _ = ler_grid(grid)
            _marcar_visiveis(ctx, grid, linhas, [it] if it in pend else [], usadas)
            if it.get("_seq_rm"):
                pend.remove(it)
        finally:
            _limpar_pesquisa(caixa)
            _, linhas, _ = ler_grid(grid)
    if pend:
        faltam = [i["cod_prd"] for i in pend]
        for c in faltam:
            ctx.log_warning("ITEM", "Produto nao encontrado no grid apos varredura completa", item=c)
        raise ItemNaoEncontradoError(f"Itens do lote nao encontrados no movimento 1.1.15: {faltam}")
    ctx.med.marca("Faturar marcado", itens=[(i["cod_prd"], i.get("_seq_rm")) for i in alvos])
    return primeira, rolou


def _ler_todas_linhas(grid):
    """Volta ao topo e percorre o grid por paginas juntando TODAS as linhas (por Nº Sequencial)."""
    _, linhas, _ = ler_grid(grid)
    if _focar_linha_visivel(linhas):
        teclado.atalho("ctrl+home")
        time.sleep(0.5)
    todas = {}
    for _ in range(200):
        _, linhas, _ = ler_grid(grid)
        novas = [ln for ln in linhas if ln.get(COL_SEQ) not in todas]
        for ln in linhas:
            todas[ln.get(COL_SEQ)] = ln
        if not novas or not _focar_linha_visivel(linhas, ultima=True):
            break
        teclado.atalho("pgdn")
        time.sleep(0.5)
    return todas


# ================================================================== grid de itens por TECLADO
# O RM de producao fica lento quando o grid de itens e lido pela acessibilidade (custo cresce a cada
# leitura). Aqui o grid e percorrido com as setas e so a CELULA FOCADA (e o valor da sua linha, que traz
# todas as colunas separadas por ';') e consultada: 3-4 chamadas pequenas por linha.

def _cabecalho_grid(grid):
    """Le SO os cabecalhos (nome + retangulo) e o retangulo da area de linhas. Leve."""
    raiz = uia_min.ler_arvore(grid, uia_min.ESCOPO_ELEMENTO | uia_min.ESCOPO_FILHOS, tentativas=4, limite_s=10.0)
    cab = raiz.filho(nome="Cabeçalho")
    painel = raiz.filho(nome="Painel de dados")
    if cab is None or painel is None:
        raise RuntimeError("grid de itens sem cabecalho/painel de dados")
    cab = uia_min.reler(cab, uia_min.ESCOPO_ELEMENTO | uia_min.ESCOPO_FILHOS)
    return {"colunas": [(h.nome, h.rect) for h in cab.filhos()], "painel": painel.rect}


def _celula_no_ponto(x, y):
    """(coluna, linha, valor_da_linha, retangulo) da celula no ponto da tela. 1 hit-test + 2 leituras."""
    f = uia_min.IUIA.ElementFromPoint(uia_min.ponto(x, y))
    nome = f.CurrentName or ""
    if " linha " not in nome:
        return None
    coluna, linha = nome.rsplit(" linha ", 1)
    pai = uia_min.IUIA.RawViewWalker.GetParentElement(f)
    valor_linha = (pai.GetCurrentPropertyValue(uia_min.P_VALUE) if pai else "") or ""
    r = f.CurrentBoundingRectangle
    return coluna, linha, str(valor_linha), (r.left, r.top, r.right, r.bottom)


def _percorrer(cab, acao, max_linhas=5000):
    """Percorre TODAS as linhas com a seta para baixo. A linha focada e localizada por hit-test na coluna
    Faturar: desce uma altura de linha por passo e, quando o grid comeca a rolar, fica na ultima linha
    visivel. Cada passo confere o numero da linha ('linha N'). acao(seq, prd, fat, rect, linha)."""
    nomes = [n for n, _ in cab["colunas"]]
    rects = dict(cab["colunas"])
    i_seq, i_prd, i_fat = nomes.index(COL_SEQ), nomes.index(COL_PRD), nomes.index(COL_FAT)
    pl, pt, pr, pb = cab["painel"]
    fl, ft, fr, fb = rects[COL_FAT]
    x = (fl + fr) // 2
    sl, st, sr, sb = rects[COL_SEQ]
    # foco no grid: clique no Nº Sequencial da 1a linha (nunca no Faturar: o clique alterna) e topo
    teclado.clicar((sl + sr) // 2, max(sb, pt) + 9)
    time.sleep(0.25)
    teclado.atalho("ctrl+home")
    time.sleep(0.4)
    y = max(fb, pt) + 9
    c = win32.esperar(lambda: _celula_no_ponto(x, y), 3, "1a linha do grid de itens", intervalo=0.1)
    altura = max(c[3][3] - c[3][1], 12)
    y = (c[3][1] + c[3][3]) // 2
    y_ultimo = pb - altura // 2 - 2
    vistas = []
    for _ in range(max_linhas):
        c = _celula_no_ponto(x, y)
        if c is None or c[0] != COL_FAT:
            raise RuntimeError(f"hit-test fora da coluna Faturar em ({x},{y}): {c}")
        _, linha, valor_linha, rect = c
        if vistas and linha == vistas[-1]:
            break  # seta para baixo nao andou: ultima linha
        if vistas and vistas[-1].isdigit() and linha.isdigit() and int(linha) != int(vistas[-1]) + 1:
            raise RuntimeError(f"grid de itens: esperava linha {int(vistas[-1]) + 1} e achou {linha}")
        vistas.append(linha)
        v = valor_linha.split(";")
        seq = v[i_seq] if i_seq < len(v) else ""
        prd = v[i_prd] if i_prd < len(v) else ""
        fat = _eh_true(v[i_fat]) if i_fat < len(v) else False
        acao(seq, prd, fat, rect, linha)
        teclado.atalho("down", pausa=0.05)
        time.sleep(0.1)
        if y + altura <= y_ultimo:
            y += altura  # ainda descendo na area visivel; depois disso o grid rola e a linha fica no fim
    return len(vistas)


# ================================================================== grid de itens pela PESQUISA (Ctrl+F)
# Para cada item: pesquisa o codigo do produto -> o item vira a 1a linha (posicao conhecida) -> confere a
# linha por hit-test (seq + produto) -> 1 clique no Faturar -> grava (clique no Nº Sequencial da mesma
# linha) -> confere. Nao percorre o grid e nunca chega na ultima linha.

def _caixa_pesquisa_grid(grid):
    """EDIT 'Search Box' do painel de pesquisa (filho do proprio grid: busca so ali dentro)."""
    return uia_min.mapa_nomes(grid, {"Search Box"}, classes=["EDIT"]).get("Search Box")


def _y_linha(cab, k, altura):
    """Centro vertical da k-esima linha visivel (k=1 e a primeira) logo abaixo do cabecalho."""
    topo = max(dict(cab["colunas"])[COL_SEQ][3], cab["painel"][1])
    return topo + (k - 1) * altura + altura // 2


def _altura_linha(cab):
    x = _x_col(cab, COL_FAT)
    topo = max(dict(cab["colunas"])[COL_SEQ][3], cab["painel"][1])
    c = _celula_no_ponto(x, topo + 9)
    if not c:
        return 20
    return max(c[3][3] - c[3][1], 12)


def _x_col(cab, coluna):
    l, t, r, b = dict(cab["colunas"])[coluna]
    return (l + r) // 2


def _linha_info(cab, k, altura, i_seq, i_prd, i_fat):
    """(seq, prd, fat, rect_faturar) da k-esima linha visivel, por hit-test na coluna Faturar."""
    c = _celula_no_ponto(_x_col(cab, COL_FAT), _y_linha(cab, k, altura))
    if not c or c[0] != COL_FAT:
        return None
    v = c[2].split(";")
    seq = v[i_seq] if i_seq < len(v) else ""
    prd = v[i_prd] if i_prd < len(v) else ""
    fat = _eh_true(v[i_fat]) if i_fat < len(v) else False
    return seq, prd, fat, c[3]


def _abrir_pesquisa(ctx, grid, cab):
    caixa = _caixa_pesquisa_grid(grid)
    if caixa and win32.visivel(caixa):
        return caixa
    teclado.clicar(_x_col(cab, COL_SEQ), _y_linha(cab, 1, 18))   # foco no grid (Nº Sequencial, nunca Faturar)
    time.sleep(0.25)
    teclado.atalho("ctrl+f")
    return win32.esperar(lambda: (lambda h: h if h and win32.visivel(h) else 0)(_caixa_pesquisa_grid(grid)),
                         4, "painel de pesquisa do grid (Ctrl+F)", intervalo=0.2)


def _digitar_na_caixa(caixa, texto):
    """Foco por CLIQUE na caixa de pesquisa (posicao via Win32) - sem acessibilidade."""
    l, t, r, b = win32.rect(caixa)
    teclado.clicar((l + r) // 2, (t + b) // 2)
    time.sleep(0.15)
    limpar_campo()
    if texto:
        teclado.digitar(texto)
    teclado.atalho("enter")


def _pesquisar_codigo(caixa, codigo):
    _digitar_na_caixa(caixa, codigo)
    time.sleep(0.9)


def _fechar_pesquisa(caixa):
    if caixa and win32.existe(caixa) and win32.visivel(caixa):
        _digitar_na_caixa(caixa, "")
        time.sleep(0.6)
        teclado.atalho("esc")
        time.sleep(0.4)


def _achar_na_pesquisa(cab, altura, codigo, usadas, idx, seq_preferida=None, tentativas=6):
    """Procura nas primeiras linhas do resultado a 1a linha com o produto e seq ainda nao usada."""
    i_seq, i_prd, i_fat = idx
    for _ in range(tentativas):  # o filtro da pesquisa pode demorar a aplicar
        achou = None
        for k in range(1, 8):
            info = _linha_info(cab, k, altura, i_seq, i_prd, i_fat)
            if info is None:
                break
            seq, prd, fat, rect = info
            if prd == codigo and seq not in usadas and (not seq_preferida or seq == seq_preferida):
                return k, info
            if prd == codigo and achou is None and seq not in usadas:
                achou = (k, info)
        if achou and not seq_preferida:
            return achou
        time.sleep(0.4)
    return None, None


def marcar_faturar_pesquisa(ctx, grid, alvos):
    """Marca Faturar de cada item do lote usando a pesquisa do grid. Item nao encontrado: FALHA o lote."""
    cab = _cabecalho_grid(grid)
    cab_sem = cab
    nomes = [n for n, _ in cab["colunas"]]
    exigir_colunas(nomes, [COL_SEQ, COL_PRD, COL_FAT], "de itens")
    caixa = _abrir_pesquisa(ctx, grid, cab)
    time.sleep(0.3)
    cab = _cabecalho_grid(grid)          # com o painel aberto o cabecalho desce: rele as posicoes
    nomes = [n for n, _ in cab["colunas"]]
    idx = (nomes.index(COL_SEQ), nomes.index(COL_PRD), nomes.index(COL_FAT))
    usadas, faltam = set(), []
    altura = None
    try:
        for it in alvos:
            _pesquisar_codigo(caixa, it["cod_prd"])
            if altura is None:
                altura = _altura_linha(cab)
            k, info = _achar_na_pesquisa(cab, altura, it["cod_prd"], usadas, idx,
                                         seq_preferida=str(it["seq"]) if it.get("seq") else None)
            if info is None:
                faltam.append(it["cod_prd"])
                continue
            seq, prd, fat, rect = info
            it["_seq_rm"] = seq
            usadas.add(seq)
            for tentativa in range(2):
                if fat:
                    break
                l, t, r, b = rect
                teclado.clicar((l + r) // 2, (t + b) // 2)               # UM clique no Faturar
                time.sleep(0.2)
                teclado.clicar(_x_col(cab, COL_SEQ), _y_linha(cab, k, altura))  # grava (sai da celula)
                time.sleep(0.5)
                info2 = _linha_info(cab, k, altura, *idx)
                if not info2 or info2[0] != seq:
                    raise RuntimeError(f"pesquisa: linha do item {prd} mudou de posicao apos o clique")
                fat = info2[2]
            if not fat:
                raise RuntimeError(f"nao consegui marcar Faturar do item {prd} (seq {seq})")
            log(f"   Faturar OK: {prd} seq {seq}")
        if not faltam:
            # CONFERENCIA (trava): pesquisa de novo cada item e exige a linha dele (seq) com Faturar marcado.
            # Feita aqui, com o painel aberto e antes de editar os itens: RM leve e posicoes conhecidas.
            # A edicao dos itens nao altera o Faturar.
            desmarcadas, nao_achadas = [], []
            for it in alvos:
                _pesquisar_codigo(caixa, it["cod_prd"])
                k, info = _achar_na_pesquisa(cab, altura, it["cod_prd"], set(), idx, seq_preferida=it["_seq_rm"])
                if info is None:
                    nao_achadas.append((it["_seq_rm"], it["cod_prd"]))
                elif not info[2]:
                    desmarcadas.append((it["_seq_rm"], it["cod_prd"]))
            ctx.med.marca("conferencia Faturar (pesquisa)", itens=len(alvos), nao_achadas=nao_achadas,
                          desmarcadas=desmarcadas)
            if nao_achadas or desmarcadas:
                raise ConferenciaFaturarError(
                    "Conferencia do Faturar falhou; movimento NAO confirmado: "
                    f"nao encontradas={nao_achadas} sem Faturar={desmarcadas}")
            log(f"   conferencia OK: {len(alvos)} item(ns) do lote com Faturar marcado")
    finally:
        _fechar_pesquisa(caixa)
    if faltam:
        for c in faltam:
            ctx.log_warning("ITEM", "Produto nao encontrado no grid apos varredura completa", item=c)
        raise ItemNaoEncontradoError(f"Itens do lote nao encontrados no movimento 1.1.15: {faltam}")
    ctx.med.marca("Faturar marcado (pesquisa)", itens=[(i["cod_prd"], i.get("_seq_rm")) for i in alvos])
    return cab_sem, cab


def conferir_faturar_pesquisa(ctx, grid, alvos, cab_sem, cab_com):
    """TRAVA antes de confirmar: pesquisa cada item e exige a linha do lote (seq) com Faturar marcado.
    Qualquer falha: ConferenciaFaturarError -> movimento cancelado, lote ERRO (nunca confirmado)."""
    sem_linha = [i["cod_prd"] for i in alvos if not i.get("_seq_rm")]
    time.sleep(1.0)                      # deixa o RM assentar depois de fechar a janela do item
    caixa = _abrir_pesquisa(ctx, grid, cab_sem)
    time.sleep(0.5)
    cab = cab_com                        # posicoes ja conhecidas com o painel aberto (sem reler o grid)
    nomes = [n for n, _ in cab["colunas"]]
    idx = (nomes.index(COL_SEQ), nomes.index(COL_PRD), nomes.index(COL_FAT))
    desmarcadas, nao_achadas = [], []
    altura = None
    try:
        for it in alvos:
            if not it.get("_seq_rm"):
                continue
            _pesquisar_codigo(caixa, it["cod_prd"])
            if altura is None:
                altura = _altura_linha(cab)
            k, info = _achar_na_pesquisa(cab, altura, it["cod_prd"], set(), idx, seq_preferida=it["_seq_rm"])
            if info is None:
                nao_achadas.append((it["_seq_rm"], it["cod_prd"]))
            elif not info[2]:
                desmarcadas.append((it["_seq_rm"], it["cod_prd"]))
    finally:
        _fechar_pesquisa(caixa)
    ctx.med.marca("conferencia Faturar (pesquisa)", itens=len(alvos), sem_linha=sem_linha,
                  nao_achadas=nao_achadas, desmarcadas=desmarcadas)
    problemas = []
    if sem_linha:
        problemas.append(f"itens sem linha no 1.1.15: {sem_linha}")
    if nao_achadas:
        problemas.append(f"linhas nao encontradas na conferencia: {nao_achadas}")
    if desmarcadas:
        problemas.append(f"itens SEM Faturar: {desmarcadas}")
    if problemas:
        raise ConferenciaFaturarError("Conferencia do Faturar falhou; movimento NAO confirmado: "
                                      + "; ".join(problemas))
    log(f"   conferencia OK: {len(alvos)} item(ns) do lote com Faturar marcado")


def marcar_faturar_teclado(ctx, grid, alvos):
    """Uma passada no grid: cada item do lote e associado a uma linha DISTINTA com o mesmo produto e, se
    o Faturar estiver desmarcado, recebe UM clique (a celula focada ja esta visivel). O valor e gravado
    quando o foco desce para a proxima linha. Itens que nao aparecem: FALHA o lote."""
    cab = _cabecalho_grid(grid)
    exigir_colunas([n for n, _ in cab["colunas"]], [COL_SEQ, COL_PRD, COL_FAT], "de itens")
    pend = list(alvos)
    usadas = set()

    def acao(seq, prd, fat, rect, linha):
        it = next((x for x in pend if x["cod_prd"] == prd and (not x.get("seq") or str(x["seq"]) == seq)), None)
        if it is None or seq in usadas:
            return
        it["_seq_rm"] = seq
        usadas.add(seq)
        pend.remove(it)
        if not fat:
            l, t, r, b = rect
            teclado.clicar((l + r) // 2, (t + b) // 2)
            time.sleep(0.15)

    n = _percorrer(cab, acao)
    ctx.med.marca("Faturar marcado (teclado)", linhas_percorridas=n,
                  itens=[(i["cod_prd"], i.get("_seq_rm")) for i in alvos])
    if pend:
        faltam = [i["cod_prd"] for i in pend]
        for c in faltam:
            ctx.log_warning("ITEM", "Produto nao encontrado no grid apos varredura completa", item=c)
        raise ItemNaoEncontradoError(f"Itens do lote nao encontrados no movimento 1.1.15: {faltam}")
    return cab


def conferir_faturar_teclado(ctx, grid, alvos, cab, corrigir=True):
    """TRAVA antes de confirmar o movimento: percorre TODAS as linhas (so lendo) e exige
      1. todo item do lote associado a uma linha;  2. todas essas linhas com Faturar marcado;
      3. nenhuma OUTRA linha com Faturar marcado;   4. total marcado == total de itens do lote.
    Se houver linha do lote desmarcada, faz UMA passada de correcao (clique so nela) e confere de novo.
    Qualquer falha restante: ConferenciaFaturarError -> lote ERRO, movimento cancelado (nunca confirmado)."""
    esperadas = {i["_seq_rm"]: i["cod_prd"] for i in alvos if i.get("_seq_rm")}
    sem_linha = [i["cod_prd"] for i in alvos if not i.get("_seq_rm")]
    for passada in (1, 2):
        estado = {}
        _percorrer(cab, lambda seq, prd, fat, rect, linha: estado.__setitem__(seq, (prd, fat)))
        marcadas = {s_: p for s_, (p, f) in estado.items() if f}
        nao_lidas = [(s_, c) for s_, c in esperadas.items() if s_ not in estado]
        desmarcadas = [(s_, c) for s_, c in esperadas.items() if s_ in estado and not estado[s_][1]]
        extras = [(s_, p) for s_, p in marcadas.items() if s_ not in esperadas]
        ctx.med.marca(f"conferencia Faturar (passada {passada})", linhas=len(estado), marcadas=len(marcadas),
                      desmarcadas=desmarcadas, extras=extras, nao_lidas=nao_lidas)
        if passada == 1 and corrigir and desmarcadas and not extras and not nao_lidas:
            log(f"   conferencia: corrigindo Faturar desmarcado em {desmarcadas}")
            alvo_seqs = {s_ for s_, _ in desmarcadas}

            def corrige(seq, prd, fat, rect, linha):
                if seq in alvo_seqs and not fat:
                    l, t, r, b = rect
                    teclado.clicar((l + r) // 2, (t + b) // 2)
                    time.sleep(0.15)
            _percorrer(cab, corrige)
            continue
        break
    problemas = []
    if sem_linha:
        problemas.append(f"itens sem linha no 1.1.15: {sem_linha}")
    if nao_lidas:
        problemas.append(f"linhas nao encontradas na conferencia: {nao_lidas}")
    if desmarcadas:
        problemas.append(f"itens SEM Faturar: {desmarcadas}")
    if extras:
        problemas.append(f"linhas FORA do lote com Faturar marcado: {extras}")
    if len(marcadas) != len(alvos):
        problemas.append(f"{len(marcadas)} linha(s) com Faturar para {len(alvos)} item(ns) do lote")
    if problemas:
        raise ConferenciaFaturarError("Conferencia do Faturar falhou; movimento NAO confirmado: "
                                      + "; ".join(problemas))
    log(f"   conferencia OK: {len(marcadas)} linha(s) com Faturar = {len(alvos)} item(ns) do lote "
        f"({len(estado)} linhas no grid)")


def verificar_faturar_final(ctx, grid, alvos):
    """TRAVA antes de confirmar o movimento. Le TODAS as linhas do grid (leitura leve) e exige:
      1. todo item do lote associado a uma linha do 1.1.15;
      2. todas essas linhas lidas e com Faturar marcado;
      3. nenhuma OUTRA linha com Faturar marcado (nao faturar item fora do lote);
      4. total de linhas marcadas == total de itens do lote.
    Qualquer falha: ConferenciaFaturarError -> lote ERRO e movimento cancelado (nunca confirmado)."""
    sem_linha = [i["cod_prd"] for i in alvos if not i.get("_seq_rm")]
    esperadas = {i["_seq_rm"]: i["cod_prd"] for i in alvos if i.get("_seq_rm")}
    por_seq = _ler_todas_linhas(grid)
    linhas = list(por_seq.values())
    marcadas = {ln.get(COL_SEQ): ln.get(COL_PRD) for ln in linhas if _eh_true(ln.get(COL_FAT))}
    nao_lidas = [(s_, c) for s_, c in esperadas.items() if s_ not in por_seq]
    desmarcadas = [(s_, c) for s_, c in esperadas.items() if s_ in por_seq and s_ not in marcadas]
    extras = [(s_, c) for s_, c in marcadas.items() if s_ not in esperadas]
    ctx.med.marca("conferencia final Faturar", itens_lote=len(alvos), linhas_lidas=len(linhas),
                  marcadas=len(marcadas), sem_linha=sem_linha, nao_lidas=nao_lidas,
                  desmarcadas=desmarcadas, extras=extras)
    problemas = []
    if sem_linha:
        problemas.append(f"itens sem linha no 1.1.15: {sem_linha}")
    if nao_lidas:
        problemas.append(f"linhas nao lidas na conferencia: {nao_lidas}")
    if desmarcadas:
        problemas.append(f"itens SEM Faturar: {desmarcadas}")
    if extras:
        problemas.append(f"linhas FORA do lote com Faturar marcado: {extras}")
    if len(marcadas) != len(alvos):
        problemas.append(f"{len(marcadas)} linha(s) com Faturar para {len(alvos)} item(ns) do lote")
    if problemas:
        raise ConferenciaFaturarError("Conferencia do Faturar falhou; movimento NAO confirmado: "
                                      + "; ".join(problemas))
    log(f"   conferencia final OK: {len(marcadas)} linha(s) com Faturar = {len(alvos)} item(ns) do lote")


# ------------------------------------------------------------------ janela do item
def _janela_item(ctx):
    for h in win32.janelas_topo(ctx.pid):
        if win32.titulo(h).startswith("Item de Movimento:"):
            return h
    return 0


def _tratar_confirma_alteracao(ctx, timeout=0.6):
    """'Confirma a alteracao ?' (#32770) -> Yes. Qualquer outra caixa -> erro."""
    fim = time.perf_counter() + timeout
    while time.perf_counter() < fim:
        d = win32.dialogo_rm(ctx.pid)
        if d:
            h, msg, botoes = d
            if "Confirma a altera" in msg and "Yes" in botoes:
                log("   'Confirma a alteracao ?' -> Yes")
                win32.clicar_botao_dialogo(h, botoes["Yes"])
                win32.esperar(lambda: not win32.existe(h), 5, "fechar confirmacao")
                return True
            checar_dialogo(ctx, "item")
        time.sleep(0.05)
    return False


class JanelaItem:
    """Cache nome->hwnd da janela do item (os controles sobrevivem ao Ctrl+PgDn)."""

    def __init__(self, h):
        self.h = h
        self.m = {}

    def campo(self, nome, timeout=8):
        hw = self.m.get(nome)
        if hw and win32.existe(hw) and win32.visivel(hw):
            return hw
        hw = win32.esperar(lambda: uia_min.mapa_nomes(self.h, {nome}).get(nome), timeout, f"campo {nome}", intervalo=0.2)
        self.m[nome] = hw
        return hw

    def navbar(self):
        return self.campo("NavBar")


def _garantir_cabecalho(ji):
    preco = ji.m.get("tbxPRECOUNITARIO")
    if preco and win32.existe(preco) and win32.visivel(preco):
        return preco
    vis = uia_min.mapa_nomes(ji.h, {"tbxPRECOUNITARIO"}).get("tbxPRECOUNITARIO")
    if vis:
        ji.m["tbxPRECOUNITARIO"] = vis
        return vis
    return abrir_secao(ji.navbar(), "Identificação", "Cabeçalho",
                       lambda: uia_min.mapa_nomes(ji.h, {"tbxPRECOUNITARIO"}).get("tbxPRECOUNITARIO"),
                       "campo preco unitario")


def _preencher_tributo(ctx, ji, codigo, aliquota):
    """Tributos e Valores > Tributos: seleciona a linha do tributo em dgvTributos e preenche cAliquota."""
    dgv = ji.campo("dgvTributos")
    arv = uia_min.ler_arvore(dgv)
    alvo = None
    for linha in arv.filhos():
        if linha.tipo not in (uia_min.T_DATAITEM, uia_min.T_CUSTOM, uia_min.T_LISTITEM):
            continue
        cel = linha.busca(lambda n: n.nome.startswith("Código do Tributo"))
        if cel and cel.valor.strip() == codigo:
            alvo = cel
            break
    if alvo is None:
        raise RuntimeError(f"tributo {codigo} nao encontrado em dgvTributos")
    teclado.clicar(*alvo.centro)
    time.sleep(0.2)
    teclado.atalho("esc")

    def campo_aliquota():
        # cAliquota visivel cujo painel (pai) tambem tem cValor: e o painel do tributo selecionado
        cands = [h for h in win32.filhos(ji.h, True)]
        nomes = {}
        for h in cands:
            if "Window.8" in win32.classe(h):
                continue
            n, a = uia_min.nome_aid(h)
            if n in ("cAliquota", "cValor") or a in ("cAliquota", "cValor"):
                nomes[h] = n or a
        for h, n in nomes.items():
            if n == "cAliquota":
                irmaos = [x for x, nn in nomes.items() if nn == "cValor" and win32.pai(x) == win32.pai(h)]
                if irmaos:
                    return h
        return 0

    aliq_h = win32.esperar(campo_aliquota, 10, "campo cAliquota", intervalo=0.3)
    valor = num_br(aliquota)
    digitar_campo(aliq_h, valor, tab=True)
    lido = esperar_texto(aliq_h, lambda t: so_digitos(t).rstrip("0") == so_digitos(valor).rstrip("0"),
                         8, f"aliquota {codigo} = {valor}")
    ctx.med.marca(f"tributo {codigo}", aliquota=valor, lido=lido)


def _preencher_item(ctx, ji, it):
    ipi, icms = _num(it.get("ipi")), _num(it.get("icms"))
    if it.get("preco") is None and ipi <= 0 and icms <= 0:
        log(f"   {it['cod_prd']}: sem preco e sem tributos, nada a preencher")
        return
    preco_h = _garantir_cabecalho(ji)
    total_h = ji.campo("tbxVALORTOTALITEM")
    if it.get("preco") is not None:
        preco = num_br(it["preco"], 2)
        digitar_campo(preco_h, preco, tab=True)
        # O RM so recalcula o Valor Total ao salvar; aqui confere o preco que ficou no campo.
        checar_dialogo(ctx, "preco")
        preco_lido = esperar_texto(preco_h, lambda t: so_digitos(t).rstrip("0") == so_digitos(preco).rstrip("0"),
                                   8, f"preco de {it['cod_prd']} = {preco}")
        ctx.med.marca(f"preco {it['cod_prd']}", preco=preco, preco_lido=preco_lido)
    else:
        log(f"   {it['cod_prd']}: preco nao informado, mantendo valor atual")

    if ipi > 0 or icms > 0:
        abrir_secao(ji.navbar(), "Tributos e Valores", "Tributos",
                    lambda: uia_min.mapa_nomes(ji.h, {"dgvTributos"}).get("dgvTributos"), "tabela de tributos")
        ji.m.pop("dgvTributos", None)
        if ipi > 0:
            _preencher_tributo(ctx, ji, "IPI", ipi)
        if icms > 0:
            _preencher_tributo(ctx, ji, "ICMS", icms)

    frente(ji.h)
    teclado.atalho("alt+s")
    _tratar_confirma_alteracao(ctx, timeout=0.8)
    win32.esperar(lambda: win32.habilitada(ji.h) and not win32.dialogo_rm(ctx.pid), 10, "item salvo")
    ctx.med.marca(f"item salvo {it['cod_prd']}", valor_total=win32.texto(total_h))


def itens(ctx):
    alvos = [dict(i) for i in ctx.lote["itens"]]
    mov = _mov(ctx)
    hj = _janela_item(ctx)
    retomando = bool(hj)
    if hj:
        # Retomada (teste): janela do item ja aberta -> continua dela, sem reler o grid.
        log("   janela do item ja aberta: retomando a partir do item atual")
    else:
        frente(mov)
        m = uia_min.mapa_nomes(mov, {"NavBar"})
        grid = abrir_secao(m["NavBar"], "Itens", "Itens",
                           lambda: uia_min.mapa_nomes(mov, {"MainView"}).get("MainView"), "grid de itens")
        cab_sem, cab_com = marcar_faturar_pesquisa(ctx, grid, alvos)
        # Abre o primeiro item: foco no grid (Nº Sequencial da 1a linha) -> topo (Ctrl+Home) -> Ctrl+Enter.
        teclado.clicar(_x_col(cab_sem, COL_SEQ), _y_linha(cab_sem, 1, 18))
        time.sleep(0.25)
        teclado.atalho("ctrl+home")
        time.sleep(0.35)
        teclado.atalho("ctrl+enter")
        hj = win32.esperar(lambda: _janela_item(ctx), 20, "janela do item")
    ji = JanelaItem(hj)
    # Chave de navegacao: Nº Sequencial da linha atribuida (o titulo da janela traz a seq).
    pendentes = {i["_seq_rm"]: i for i in alvos if i.get("_seq_rm")}
    if retomando:  # sem grid lido: casa por seq/codigo, descartando os que ficaram para tras
        mt0 = RE_TITULO_ITEM.match(win32.esperar(lambda: win32.titulo(hj), 5, "titulo do item"))
        seq_atual = int(mt0.group(1)) if mt0 else 0
        pendentes = {}
        for it in alvos:
            if it.get("seq") and int(it["seq"]) < seq_atual:
                log(f"   retomada: item {it['seq']} {it['cod_prd']} ja ficou para tras, considerado feito")
            else:
                pendentes[str(it.get("seq") or it["cod_prd"])] = it
    vistos = []
    while True:
        titulo = win32.esperar(lambda: win32.titulo(hj), 5, "titulo do item")
        mt = RE_TITULO_ITEM.match(titulo)
        if not mt:
            raise RuntimeError(f"titulo inesperado da janela do item: {titulo!r}")
        seq, cod = mt.group(1), mt.group(2)
        if (seq, cod) in vistos:
            break
        vistos.append((seq, cod))
        chave = seq if seq in pendentes else (cod if retomando and cod in pendentes else None)
        if chave is not None:
            it = pendentes.pop(chave)
            if it["cod_prd"] != cod:
                raise RuntimeError(f"item {seq}: produto {cod} diferente do esperado {it['cod_prd']}")
            log(f"   item {seq} {cod}: preenchendo")
            ctx.log_info("ITEM", "Processando item", item=cod)
            _preencher_item(ctx, ji, it)
            # apos Alt+S o RM recarrega o item: espera o titulo voltar (nao vazio) antes de navegar
            win32.esperar(lambda: win32.titulo(hj), 10, "item recarregado apos salvar")
            ctx.log_info("ITEM", "Item processado com sucesso", item=cod)
        else:
            log(f"   item {seq} {cod}: nao faturar, pula")
        if not pendentes:
            break
        frente(hj)
        teclado.atalho("ctrl+pgdn")
        _tratar_confirma_alteracao(ctx, timeout=0.3)
        try:
            # titulo fica vazio enquanto o RM recarrega: so vale titulo NAO vazio e diferente
            win32.esperar(lambda: (lambda t: t and t != titulo)(win32.titulo(hj)), 4, "proximo item")
        except win32.TempoEsgotado:
            break  # ultimo item
    frente(hj)
    teclado.atalho("alt+o")
    _tratar_confirma_alteracao(ctx, timeout=0.8)
    win32.esperar(lambda: not win32.existe(hj) or not win32.visivel(hj), 15, "fechar janela do item")
    if pendentes:
        raise RuntimeError("itens marcados no grid mas nao alcancados na navegacao: "
                           f"{[(k, v['cod_prd']) for k, v in pendentes.items()]}")
    ctx.med.marca("itens percorridos", vistos=vistos)
    if not retomando:
        pass  # conferencia do Faturar ja feita na marcacao (antes de editar os itens)

    # Sem conferencia relendo o grid: depois que o grid foi lido, nenhuma consulta ampla no 1.1.15
    # (levantamento + teste: isso sobrecarrega o RM). Preco/valor ja foram conferidos na janela do item.
