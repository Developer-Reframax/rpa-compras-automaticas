# -*- coding: utf-8 -*-
"""Pecas comuns das etapas: contexto, dialogos do RM, foco+digitacao, NavBar e leitura de grid."""
import re
import time

import w32 as win32  # noqa
import uia_min
import teclado
from medidor import log


class ErroRM(RuntimeError):
    """O RM mostrou uma caixa de erro/aviso inesperada."""


class Ctx:
    def __init__(self, pid, cred, lote, med):
        self.pid = pid
        self.cred = cred
        self.lote = lote
        self.med = med
        self.main = 0          # janela principal do RM
        self.form_sol = 0      # MDI child da Solicitacao de Compras
        self.mov = 0           # janela do 1.1.15 em edicao
        self.numero_gerado = None
        self.mensagem_rm = ""  # texto de 'Mensagens de Aviso do Movimento'
        self.logger = None     # RpaLogger (padrao v1) em producao; None no run_teste
        self.log_ctx = {}      # campos padrao do log (lote_id, filial, fornecedor, movimento_origem)

    def log_info(self, step, message, **kw):
        if self.logger:
            self.logger.info(step, message, **{**self.log_ctx, **kw})

    def log_warning(self, step, message, **kw):
        if self.logger:
            self.logger.warning(step, message, **{**self.log_ctx, **kw})


# ------------------------------------------------------------------ janelas/dialogos
def checar_dialogo(ctx, contexto: str, fechar=True):
    """Se houver caixa '#32770' do RM aberta, le o texto, fecha com OK (se pedido) e levanta ErroRM."""
    d = win32.dialogo_rm(ctx.pid)
    if not d:
        return
    h, msg, botoes = d
    log(f"   ! dialogo RM em '{contexto}': {msg!r} botoes={list(botoes)}")
    if fechar and "OK" in botoes:
        win32.clicar_botao_dialogo(h, botoes["OK"])
    e = ErroRM(f"[{contexto}] RM: {msg}")
    e.mensagem = msg  # texto puro do RM (o v1 grava este texto nas mensagens de erro)
    raise e


def esperar_janela(ctx, timeout, descricao, checar_erro=True, **filtro):
    def cond():
        if checar_erro:
            checar_dialogo(ctx, descricao)
        return win32.achar_janela(ctx.pid, **filtro)
    return win32.esperar(cond, timeout, descricao)


def esperar_sumir(h, timeout, descricao):
    win32.esperar(lambda: not win32.existe(h) or not win32.visivel(h), timeout, descricao)


def frente(h):
    if not win32.trazer_para_frente(h):
        try:
            uia_min.elemento(h).SetFocus()
        except Exception:
            pass
    return win32.esperar(lambda: win32.em_primeiro_plano(h), 3, "janela em primeiro plano")


# ------------------------------------------------------------------ foco e digitacao
def focar(h, timeout=2.0):
    """Leva o foco ao controle (UIA SetFocus pelo handle) e confirma pelo Windows."""
    def tem_foco():
        f = win32.foco_atual(h)
        return f and (f == h or win32.pai(f) == h)  # aceita filho direto (ex.: EDIT do DateTimePicker)
    if tem_foco():
        return
    uia_min.focar_hwnd(h)
    win32.esperar(tem_foco, timeout, f"foco no hwnd {h}")


def limpar_campo():
    """Seleciona e apaga o conteudo. NAO usar Ctrl+A: no RM ele abre um menu."""
    teclado.atalho("home")
    teclado.atalho("shift+end")
    teclado.atalho("del")


def digitar_campo(h, valor: str, tab=True, intervalo=0.0, limpar=True):
    focar(h)
    if limpar:
        limpar_campo()
    teclado.digitar(valor, intervalo)
    if tab:
        teclado.atalho("tab")


def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def preencher_lookup(ctx, janela, code_h, inner_h, valor, descricao, timeout=15):
    """Lookup do RM: digita o codigo, Tab e espera a descricao (innerEdit) ser preenchida.
    Retorna a descricao lida."""
    atual = win32.texto(code_h)
    if so_digitos(atual) and so_digitos(atual) == so_digitos(valor) and win32.texto(inner_h).strip():
        log(f"   {descricao}: ja preenchido ({atual})")
        return win32.texto(inner_h)
    antes = win32.texto(inner_h)
    t0 = time.perf_counter()
    digitar_campo(code_h, valor, tab=True)

    def pronto():
        checar_dialogo(ctx, descricao)
        if not win32.existe(janela):
            raise RuntimeError(f"janela fechou durante {descricao}")
        d = win32.texto(inner_h).strip()
        return d if d and d != antes.strip() else None

    desc = win32.esperar(pronto, timeout, f"descricao do lookup {descricao}")
    lido = win32.texto(code_h)
    ctx.med.marca(f"lookup {descricao}", ms=round((time.perf_counter() - t0) * 1000), codigo=lido, descricao=desc)
    if so_digitos(lido) != so_digitos(valor):
        raise RuntimeError(f"{descricao}: codigo ficou {lido!r}, esperado {valor!r}")
    return desc


# ------------------------------------------------------------------ NavBar
def secao_aberta(janela, nome):
    """Painel de conteudo visivel com o texto da secao (ex.: 'Tabelas'). So Win32."""
    for c in win32.filhos(janela, True):
        if "Window.8" in win32.classe(c) and win32.texto(c, 200) == nome:
            return c
    return 0


def abrir_secao(navbar_h, lista: str, item: str, pronto, descricao, timeout=8):
    """Abre um item do NavBar: le so o NavBar (cache), expande a lista se preciso,
    seleciona/invoca o item e espera pronto(). Se nao funcionar, 1 clique no centro do item."""
    arv = uia_min.ler_arvore(navbar_h)
    lst = arv.busca(lambda n: n.tipo == uia_min.T_LIST and n.nome == lista)
    if lst is None:
        raise RuntimeError(f"NavBar sem a lista '{lista}'")
    it = lst.filho(nome=item, tipo=uia_min.T_LISTITEM)
    if it is None:
        exp = lst.filho(nome="Expand")
        try:
            (exp or lst).invocar()
        except Exception:
            teclado.clicar(*(exp or lst).centro)
        def achou():
            a = uia_min.ler_arvore(navbar_h)
            l2 = a.busca(lambda n: n.tipo == uia_min.T_LIST and n.nome == lista)
            return l2.filho(nome=item, tipo=uia_min.T_LISTITEM) if l2 else None
        it = win32.esperar(achou, 3, f"item '{item}' apos expandir '{lista}'", intervalo=0.15)
    for tentativa in ("selecionar", "invocar", "clicar"):
        try:
            if tentativa == "selecionar":
                it.selecionar()
            elif tentativa == "invocar":
                it.invocar()
            else:
                teclado.clicar(*it.centro)
        except Exception as e:
            log(f"   NavBar {item}: {tentativa} falhou ({e!r})")
            continue
        try:
            r = win32.esperar(pronto, 2.5 if tentativa != "clicar" else timeout, descricao)
            log(f"   NavBar {lista} > {item}: ok via {tentativa}")
            return r
        except win32.TempoEsgotado:
            continue
    raise win32.TempoEsgotado(f"secao '{lista} > {item}' nao abriu ({descricao})")


# ------------------------------------------------------------------ grid DevExpress
class LinhaGrid:
    def __init__(self, no, headers):
        self.no = no
        self.valores = (no.valor or "").split(";")
        self.headers = headers
        self.celulas = {}
        for c in no.filhos():
            n = c.nome
            if " linha " in n:
                self.celulas[n.rsplit(" linha ", 1)[0]] = c

    def get(self, coluna):
        i = self.headers.index(coluna)
        return self.valores[i] if i < len(self.valores) else ""

    def valores_atuais(self):
        return (self.no.valor_atual() or "").split(";")

    def get_atual(self, coluna):
        v = self.valores_atuais()
        i = self.headers.index(coluna)
        return v[i] if i < len(v) else ""


def ler_grid(grid_h):
    """Uma leitura em cache do grid (cabecalho + linhas visiveis). Nao rola, nao clica."""
    arv = uia_min.ler_arvore(grid_h, limite_s=10.0)
    cab = arv.filho(nome="Cabeçalho")
    headers = [f.nome for f in cab.filhos()] if cab else []
    painel = arv.filho(nome="Painel de dados")
    linhas = []
    if painel:
        linhas = [LinhaGrid(r, headers) for r in painel.filhos() if r.tipo == uia_min.T_LISTITEM]
    return headers, linhas, (painel.rect if painel else arv.rect)


def exigir_colunas(headers, colunas, grid_desc):
    faltam = [c for c in colunas if c not in headers]
    if faltam:
        raise RuntimeError(f"Grid {grid_desc} sem as colunas {faltam}. Cabecalho atual: {headers}")


def texto_limpo(s):
    return (s or "").replace("&", "").strip()
