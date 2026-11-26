# -*- coding: utf-8 -*-
"""Etapa itens: marca Faturar no grid e percorre os itens com Ctrl+PgDn dentro da janela do item,
preenchendo preco (e tributos) so dos itens a faturar."""
import re
import time

import w32 as win32  # noqa
import uia_min
import teclado
from config_v2 import num_br
from comum import (checar_dialogo, frente, focar, digitar_campo, abrir_secao, ler_grid,
                   exigir_colunas, so_digitos)
from etapas.movimento import _mov
from medidor import log

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


def _marcar_celula_faturar(ln, cod):
    cel = ln.celulas.get(COL_FAT)
    if cel is None or cel.fora_da_tela:
        raise RuntimeError(f"celula Faturar fora da tela para {cod}: ajuste o layout do grid de itens "
                           "(Faturar entre as primeiras colunas)")
    for tentativa in range(3):
        teclado.clicar(*cel.centro)
        try:
            win32.esperar(lambda: _eh_true(ln.get_atual(COL_FAT)), 1.2, "Faturar marcado", intervalo=0.1)
            return
        except win32.TempoEsgotado:
            log(f"   Faturar de {cod} ainda falso (tentativa {tentativa + 1})")
    raise RuntimeError(f"nao consegui marcar Faturar do item {cod}")


def marcar_faturar(ctx, grid, alvos):
    """Marca Faturar de cada alvo numa linha DISTINTA do grid (mesmo produto pode repetir quando ha
    varias solicitacoes). Le so as linhas visiveis; se faltar alvo, pagina com PgDn e rele.
    Retorna (celula Nº Sequencial da 1a linha da 1a pagina, houve_paginacao)."""
    usadas = set()
    pend = list(alvos)
    primeira = None
    paginou = False
    assinatura_ant = None
    for pagina in range(60):
        headers, linhas, area = ler_grid(grid)
        exigir_colunas(headers, [COL_SEQ, COL_PRD, COL_FAT], "de itens")
        if pagina == 0:
            ctx.med.marca("grid de itens lido", linhas=len(linhas), colunas=headers)
            primeira = linhas[0].celulas.get(COL_SEQ) if linhas else None
        for it in list(pend):
            cands = [ln for ln in linhas if ln.get(COL_PRD) == it["cod_prd"] and ln.get(COL_SEQ) not in usadas]
            if not cands:
                continue
            ln = next((c for c in cands if it.get("seq") and c.get(COL_SEQ) == str(it["seq"])), cands[0])
            it["_seq_rm"] = ln.get(COL_SEQ)
            usadas.add(it["_seq_rm"])
            pend.remove(it)
            if not _eh_true(ln.get(COL_FAT)):
                _marcar_celula_faturar(ln, it["cod_prd"])
        if not pend:
            break
        assinatura = tuple(ln.get(COL_SEQ) for ln in linhas)
        if assinatura == assinatura_ant:
            break  # fim do grid
        assinatura_ant = assinatura
        uia_min.focar_hwnd(grid)
        teclado.atalho("pgdn")
        paginou = True
        time.sleep(0.3)
    for it in pend:  # comportamento do v1: avisa e segue
        log(f"   produto {it['cod_prd']} nao encontrado no grid")
        ctx.log_warning("ITEM", "Produto nao encontrado no grid apos varredura completa", item=it["cod_prd"])
    ctx.med.marca("Faturar marcado", itens=[(i["cod_prd"], i.get("_seq_rm")) for i in alvos])
    return primeira, paginou


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
    lido = win32.texto(aliq_h)
    ctx.med.marca(f"tributo {codigo}", aliquota=valor, lido=lido)
    if so_digitos(lido).rstrip("0") != so_digitos(valor).rstrip("0"):
        raise RuntimeError(f"aliquota {codigo} ficou {lido!r}, esperado {valor!r}")


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
        preco_lido = win32.texto(preco_h)
        if so_digitos(preco_lido).rstrip("0") != so_digitos(preco).rstrip("0"):
            raise RuntimeError(f"preco de {it['cod_prd']} ficou {preco_lido!r}, esperado {preco!r}")
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
        primeira, paginou = marcar_faturar(ctx, grid, alvos)
        if primeira is None:
            raise RuntimeError("grid de itens vazio")
        if not any(i.get("_seq_rm") for i in alvos):
            raise RuntimeError("nenhum item do lote foi encontrado no grid do 1.1.15")
        if paginou:  # volta ao topo antes de abrir o primeiro item
            uia_min.focar_hwnd(grid)
            teclado.atalho("ctrl+home")
            time.sleep(0.3)
        # Abre o primeiro item (Ctrl+Enter na primeira linha) e percorre com Ctrl+PgDn.
        teclado.clicar(*primeira.centro)
        time.sleep(0.15)
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

    # Sem conferencia relendo o grid: depois que o grid foi lido, nenhuma consulta ampla no 1.1.15
    # (levantamento + teste: isso sobrecarrega o RM). Preco/valor ja foram conferidos na janela do item.
