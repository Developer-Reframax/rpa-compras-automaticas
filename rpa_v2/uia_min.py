# -*- coding: utf-8 -*-
"""Acessibilidade (UIA) so de forma pontual.

Regras:
- nunca WalkControl, nunca FindFirst/FindAll em descendentes a partir de uma janela grande;
- elemento sempre aberto direto pelo handle (ElementFromHandle);
- leitura de subarvore so de controles pequenos (grid, NavBar, toolbar, lista), numa unica
  chamada com cache (BuildUpdatedCache);
- nomes dos campos resolvidos um a um pelo handle (mapa nome -> hwnd).
"""
import time

import uiautomation as auto
import uiautomation.uiautomation as _u

import w32 as win32  # noqa

IUIA = _u._AutomationClient.instance().IUIAutomation

P_NAME = 30005
P_CTRLTYPE = 30003
P_AID = 30011
P_RECT = 30001
P_OFFSCREEN = 30022
P_ENABLED = 30010
P_VALUE = 30045
P_LEGACY_VALUE = 30093

T_BUTTON = 50000
T_CHECKBOX = 50002
T_EDIT = 50004
T_LISTITEM = 50007
T_LIST = 50008
T_TABITEM = 50019
T_CUSTOM = 50025
T_DATAITEM = 50029
T_HEADER = 50034
T_HEADERITEM = 50035
T_TABLE = 50036

ESCOPO_ELEMENTO = 1
ESCOPO_FILHOS = 2
ESCOPO_SUBARVORE = 7


def _cache_request(escopo, valores=True):
    cr = IUIA.CreateCacheRequest()
    props = [P_NAME, P_CTRLTYPE, P_AID, P_RECT, P_OFFSCREEN, P_ENABLED]
    if valores:
        props += [P_VALUE, P_LEGACY_VALUE]
    for p in props:
        cr.AddProperty(p)
    cr.TreeScope = escopo
    cr.TreeFilter = IUIA.RawViewCondition
    return cr


_CR_NOME = None


def _cr_nome():
    global _CR_NOME
    if _CR_NOME is None:
        _CR_NOME = _cache_request(ESCOPO_ELEMENTO, valores=False)
    return _CR_NOME


class No:
    """No de uma arvore lida em cache (sem novas chamadas ao RM para ler propriedades)."""

    __slots__ = ("el",)

    def __init__(self, el):
        self.el = el

    def _p(self, pid):
        try:
            v = self.el.GetCachedPropertyValue(pid)
            return v
        except Exception:
            return None

    @property
    def nome(self):
        return self._p(P_NAME) or ""

    @property
    def tipo(self):
        return self._p(P_CTRLTYPE) or 0

    @property
    def aid(self):
        return self._p(P_AID) or ""

    @property
    def valor(self):
        v = self._p(P_VALUE)
        if v in (None, ""):
            v = self._p(P_LEGACY_VALUE)
        return v if isinstance(v, str) else ("" if v is None else str(v))

    @property
    def fora_da_tela(self):
        return bool(self._p(P_OFFSCREEN))

    @property
    def rect(self):
        r = self.el.CachedBoundingRectangle
        return (r.left, r.top, r.right, r.bottom)

    @property
    def centro(self):
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)

    def filhos(self):
        try:
            arr = self.el.GetCachedChildren()
        except Exception:
            return []
        if not arr:
            return []
        return [No(arr.GetElement(i)) for i in range(arr.Length)]

    def busca(self, pred, profundidade=50):
        """DFS no cache (nao toca no RM)."""
        pilha = [(self, 0)]
        while pilha:
            n, d = pilha.pop()
            if pred(n):
                return n
            if d < profundidade:
                pilha.extend((f, d + 1) for f in reversed(n.filhos()))
        return None

    def busca_todos(self, pred, profundidade=50):
        res, pilha = [], [(self, 0)]
        while pilha:
            n, d = pilha.pop()
            if pred(n):
                res.append(n)
            if d < profundidade:
                pilha.extend((f, d + 1) for f in reversed(n.filhos()))
        return res

    def filho(self, nome=None, tipo=None, prefixo=None):
        for f in self.filhos():
            if nome is not None and f.nome != nome:
                continue
            if prefixo is not None and not f.nome.startswith(prefixo):
                continue
            if tipo is not None and f.tipo != tipo:
                continue
            return f
        return None

    # ---- acoes (cada uma e uma chamada pontual ao RM)
    def controle(self):
        return auto.Control.CreateControlFromElement(self.el)

    def invocar(self):
        self.controle().GetInvokePattern().Invoke()

    def selecionar(self):
        self.controle().GetSelectionItemPattern().Select()

    def focar(self):
        self.el.SetFocus()

    def valor_atual(self) -> str:
        """Le o Value atual do elemento (1 chamada)."""
        try:
            return self.controle().GetValuePattern().Value or ""
        except Exception:
            try:
                return self.controle().GetLegacyIAccessiblePattern().Value or ""
            except Exception:
                return ""


def elemento(hwnd):
    return IUIA.ElementFromHandle(hwnd)


def ler_arvore(hwnd, escopo=ESCOPO_SUBARVORE, tentativas=1, limite_s=6.0) -> No:
    """Le a subarvore de UM controle (pelo handle) numa unica chamada com cache."""
    ultimo = None
    for i in range(tentativas):
        try:
            cr = _cache_request(escopo)
            t0 = time.perf_counter()
            no = No(IUIA.ElementFromHandleBuildCache(hwnd, cr))
            dt = time.perf_counter() - t0
            if dt >= 0.5:
                print(f"      (leitura UIA {dt:.1f}s no hwnd {hwnd})", flush=True)
            if dt > limite_s:
                raise RmLento(f"leitura UIA levou {dt:.1f}s no hwnd {hwnd}: RM sobrecarregado, parando")
            return no
        except RmLento:
            raise
        except Exception as e:  # COMError de timeout do RM
            ultimo = e
            time.sleep(0.5 * (i + 1))
    raise RuntimeError(f"Falha lendo arvore UIA do hwnd {hwnd}: {ultimo!r}")


def reler(no: No, escopo=ESCOPO_SUBARVORE) -> No:
    return No(no.el.BuildUpdatedCache(_cache_request(escopo)))


class RmLento(RuntimeError):
    """Consulta de acessibilidade lenta demais: parar para nao sobrecarregar o RM."""


LIMITE_NOME_S = 1.5
_NOMES = {}  # hwnd -> (Name, AutomationId). Nome de controle WinForms nao muda durante a vida do hwnd.


def nome_aid(hwnd):
    """(Name, AutomationId) de um handle. 1 chamada ao RM na primeira vez; depois vem do cache local."""
    r = _NOMES.get(hwnd)
    if r is not None:
        return r
    t0 = time.perf_counter()
    try:
        el = IUIA.ElementFromHandleBuildCache(hwnd, _cr_nome())
        r = (el.CachedName or ""), (el.CachedAutomationId or "")
    except Exception:
        r = ("", "")
    dt = time.perf_counter() - t0
    if dt > LIMITE_NOME_S:
        raise RmLento(f"consulta de nome levou {dt:.1f}s no hwnd {hwnd}: RM sobrecarregado, parando")
    _NOMES[hwnd] = r
    return r


def nome_aid_atual(hwnd):
    """Sem cache (para o controle focado, cujo hwnd pode ser reutilizado)."""
    _NOMES.pop(hwnd, None)
    return nome_aid(hwnd)


def mapa_nomes(janela, alvos, so_visiveis=True, classes=None):
    """Resolve nomes de controles WinForms -> hwnd, consultando um handle por vez
    e parando assim que todos os alvos forem achados. Casa por Name ou AutomationId.

    classes: lista de trechos de classe Win32 a considerar (ex.: ["EDIT", "Window.8"]).
    """
    alvos = set(alvos)
    achados = {}
    for h in win32.filhos(janela, so_visiveis):
        if classes and not any(c in win32.classe(h) for c in classes):
            continue
        n, a = nome_aid(h)
        for chave in (n, a):
            if chave in alvos and chave not in achados:
                achados[chave] = h
        if len(achados) == len(alvos):
            break
    return achados


def radio_marcado(hwnd) -> bool:
    """RadioButton WinForms: BM_GETCHECK nao reflete o estado; usa SelectionItem.IsSelected (1 chamada)."""
    try:
        ctl = auto.Control.CreateControlFromElement(IUIA.ElementFromHandle(hwnd))
        return bool(ctl.GetSelectionItemPattern().IsSelected)
    except Exception:
        return False


def ponto(x, y):
    """POINT para IUIAutomation.ElementFromPoint (coordenadas fisicas de tela)."""
    import ctypes.wintypes
    return ctypes.wintypes.POINT(int(x), int(y))


def focar_hwnd(hwnd):
    """Foco num controle pelo handle (1 chamada). Tambem ativa a janela dona."""
    IUIA.ElementFromHandle(hwnd).SetFocus()
