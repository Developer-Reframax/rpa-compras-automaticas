# -*- coding: utf-8 -*-
"""Etapa movimento: cabecalho do 1.1.15 (fornecedor, entrega, comprador, pagamento, frete, justificativa)."""
import w32 as win32  # noqa
import uia_min
import teclado
from comum import (checar_dialogo, esperar_janela, frente, focar, digitar_campo, preencher_lookup,
                   abrir_secao, texto_limpo, secao_aberta)
from medidor import log


def _mov(ctx):
    if not ctx.mov or not win32.existe(ctx.mov):
        ctx.mov = esperar_janela(ctx, 30, "janela do movimento 1.1.15",
                                 prefixo="Movimento: -1 - " + ctx.lote["tipo_mov_destino"])
    return ctx.mov


def _foco_em_nome(mov, nome):
    """Condicao: o controle focado tem o nome UIA 'nome' (1 consulta pelo handle focado)."""
    def cond():
        f = win32.foco_atual(mov)
        if not f:
            return 0
        n, a = uia_min.nome_aid(f)
        return f if (n == nome or a == nome) else 0
    return cond


def _secao(mov, nome):
    """Sinal de secao aberta SO por Win32: o painel de conteudo passa a ter o texto da secao."""
    return lambda: secao_aberta(mov, nome)


def _campos(mov, nomes, descricao):
    """Resolve os campos uma vez (nomes ficam em cache por hwnd; nao repete consultas ao RM)."""
    return win32.esperar(lambda: (lambda d: d if len(d) == len(nomes) else None)(uia_min.mapa_nomes(mov, nomes)),
                         8, descricao, intervalo=0.3)


def movimento(ctx):
    lote = ctx.lote
    mov = _mov(ctx)
    frente(mov)
    navbar = win32.esperar(lambda: uia_min.mapa_nomes(mov, {"NavBar"}).get("NavBar"), 20, "NavBar do 1.1.15",
                           intervalo=0.3)
    nomes_cab = {"lkpCODCFOCode", "lkpCODCFOlookupEditinnerEdit", "dtpDATAEXTRA2"}
    abrir_secao(navbar, "Identificação", "Cabeçalho", _secao(mov, "Cabeçalho"), "secao Cabecalho")
    m = _campos(mov, nomes_cab, "campos do cabecalho")
    ctx.med.marca("mapa do cabecalho resolvido")

    # Fornecedor
    preencher_lookup(ctx, mov, m["lkpCODCFOCode"], m["lkpCODCFOlookupEditinnerEdit"],
                     lote["cnpj_fornecedor"], "fornecedor")

    # Data de entrega: foco no DateTimePicker -> o RM cria um EDIT filho para digitacao.
    dtp = m["dtpDATAEXTRA2"]
    focar(dtp)
    edit = win32.esperar(lambda: next((c for c in win32.filhos(dtp, True) if "EDIT" in win32.classe(c)), 0),
                         4, "campo de digitacao da data de entrega", intervalo=0.1)
    digitar_campo(edit, lote["data_entrega"], tab=True)
    lido = uia_min.ler_arvore(dtp, uia_min.ESCOPO_ELEMENTO).valor
    ctx.med.marca("data de entrega", lido=lido)
    if lido and lido != lote["data_entrega"]:
        raise RuntimeError(f"data de entrega ficou {lido!r}, esperado {lote['data_entrega']!r}")

    # Tabelas -> comprador
    abrir_secao(navbar, "Identificação", "Tabelas", _secao(mov, "Tabelas"), "secao Tabelas")
    t = _campos(mov, {"lkpCODVEN1Code", "lkpCODVEN1lookupEditinnerEdit"}, "campos do comprador")
    nome_comprador = preencher_lookup(ctx, mov, t["lkpCODVEN1Code"], t["lkpCODVEN1lookupEditinnerEdit"],
                                      lote["cod_comprador"], "comprador")

    # Financeira -> condicao de pagamento
    abrir_secao(navbar, "Integrações", "Financeira", _secao(mov, "Financeira"), "secao Financeira")
    f = _campos(mov, {"lkpCODCPGCode", "lkpCODCPGlookupEditinnerEdit"}, "campos da cond. pagamento")
    preencher_lookup(ctx, mov, f["lkpCODCPGCode"], f["lkpCODCPGlookupEditinnerEdit"],
                     lote["cod_pagamento"], "cond. pagamento")

    # Transporte -> frete (radios nativos dentro de rdgFRETECIFOUFOB).
    # BM_CLICK marca o radio so visualmente: o RM nao registra o valor ("Tipo de Frete obrigatorio").
    # Por isso clique de mouse no centro do radio (pelo retangulo Win32, sem acessibilidade).
    def radio_frete():
        for c in win32.filhos(mov, True):
            if "BUTTON" in win32.classe(c) and texto_limpo(win32.texto(c)) == lote["tipo_frete"]:
                return c
        return 0
    radio = abrir_secao(navbar, "Transporte", "Identificação", radio_frete, "radio de frete")
    l, t_, r, b = win32.rect(radio)
    frente(mov)
    teclado.clicar(l + 8, (t_ + b) // 2)  # area do circulo do radio
    win32.esperar(lambda: uia_min.radio_marcado(radio), 3, f"frete {lote['tipo_frete']} marcado")
    ctx.med.marca("frete", tipo=lote["tipo_frete"])

    # Campos Complementares -> justificativa = EDIT logo depois do rotulo "Justificativa de Compra:"
    def campo_justificativa():
        fs = win32.filhos(mov, True)
        for i, c in enumerate(fs):
            if "STATIC" in win32.classe(c) and win32.texto(c).startswith("Justificativa de Compra"):
                p = win32.pai(c)
                for d in fs[i + 1:]:
                    if win32.pai(d) == p and "EDIT" in win32.classe(d):
                        return d
        return 0
    just = abrir_secao(navbar, "Informações Adicionais", "Campos Complementares", campo_justificativa,
                       "campo justificativa")
    texto_just = lote["justificativa"]
    if nome_comprador:
        texto_just = f"{texto_just} - Comprador: {nome_comprador.strip()}"
    digitar_campo(just, texto_just, tab=True)
    if win32.texto(just).strip() != texto_just:
        raise RuntimeError(f"justificativa ficou {win32.texto(just)!r}")
    checar_dialogo(ctx, "cabecalho")
    ctx.med.marca("cabecalho completo")
