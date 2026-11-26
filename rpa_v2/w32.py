# -*- coding: utf-8 -*-
"""Acesso ao RM so pela API do Windows (sem acessibilidade).

Tudo aqui custa microssegundos/milissegundos e nao gera carga na thread de UI do RM:
lista de janelas, titulo, classe, dono, texto de campos (WM_GETTEXT com timeout),
clique em botoes nativos (BM_CLICK), foco atual (GetGUIThreadInfo).
"""
import ctypes
import ctypes.wintypes as w
import re
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
SMTO_ABORTIFHUNG = 0x0002
GWL_STYLE = -16
ES_PASSWORD = 0x0020
GW_OWNER = 4

_ENUM = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

user32.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = w.LPARAM
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
user32.GetWindow.argtypes = [w.HWND, w.UINT]
user32.GetWindow.restype = w.HWND
user32.GetParent.argtypes = [w.HWND]
user32.GetParent.restype = w.HWND
user32.GetForegroundWindow.restype = w.HWND


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD), ("flags", w.DWORD), ("hwndActive", w.HWND), ("hwndFocus", w.HWND),
        ("hwndCapture", w.HWND), ("hwndMenuOwner", w.HWND), ("hwndMoveSize", w.HWND),
        ("hwndCaret", w.HWND), ("rcCaret", w.RECT),
    ]


def _h(h):
    return int(h or 0)


# ---------------------------------------------------------------- basicos
def classe(h) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def texto(h, timeout_ms: int = 500) -> str:
    """Texto da janela/campo via WM_GETTEXT, com timeout (nao trava se o RM estiver ocupado)."""
    tam = ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(h, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(tam)):
        return ""
    n = int(tam.value) + 1
    buf = ctypes.create_unicode_buffer(max(n, 2))
    r = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(h, WM_GETTEXT, n, ctypes.cast(buf, ctypes.c_void_p).value,
                                    SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(r))
    return buf.value if ok else ""


def titulo(h) -> str:
    return texto(h, 300)


def existe(h) -> bool:
    return bool(h) and bool(user32.IsWindow(h))


def visivel(h) -> bool:
    return bool(user32.IsWindowVisible(h))


def habilitada(h) -> bool:
    return bool(user32.IsWindowEnabled(h))


def dono(h) -> int:
    return _h(user32.GetWindow(h, GW_OWNER))


def pai(h) -> int:
    return _h(user32.GetParent(h))


def estilo(h) -> int:
    return user32.GetWindowLongW(h, GWL_STYLE) & 0xFFFFFFFF


def rect(h):
    r = w.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def pid_da_janela(h) -> int:
    p = w.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def thread_da_janela(h) -> int:
    return user32.GetWindowThreadProcessId(h, None)


def sessao_do_processo(pid: int) -> int:
    """Sessao do Windows (Terminal Services) de um processo; -1 se nao der para ler."""
    sid = w.DWORD()
    if kernel32.ProcessIdToSessionId(int(pid), ctypes.byref(sid)):
        return sid.value
    return -1


def sessao_atual() -> int:
    return sessao_do_processo(kernel32.GetCurrentProcessId())


# ---------------------------------------------------------------- enumeracao
def janelas_topo(pid: int, so_visiveis: bool = True):
    res = []

    def cb(h, _):
        if pid_da_janela(h) == pid and (not so_visiveis or user32.IsWindowVisible(h)):
            res.append(_h(h))
        return True

    user32.EnumWindows(_ENUM(cb), 0)
    return res


def filhos(h, so_visiveis: bool = False):
    """Todos os descendentes (ordem DFS do Windows = ordem de criacao/z-order)."""
    res = []

    def cb(c, _):
        if not so_visiveis or user32.IsWindowVisible(c):
            res.append(_h(c))
        return True

    user32.EnumChildWindows(h, _ENUM(cb), 0)
    return res


def filhos_diretos(h, so_visiveis: bool = False):
    return [c for c in filhos(h, so_visiveis) if pai(c) == _h(h)]


def achar_janela(pid, exato=None, prefixo=None, contem=None, regex=None, classe_contem=None, habilitada_req=None):
    for h in janelas_topo(pid):
        t = titulo(h)
        if exato is not None and t != exato:
            continue
        if prefixo is not None and not t.startswith(prefixo):
            continue
        if contem is not None and contem not in t:
            continue
        if regex is not None and not re.search(regex, t):
            continue
        if classe_contem is not None and classe_contem not in classe(h):
            continue
        if habilitada_req is not None and habilitada(h) != habilitada_req:
            continue
        return h
    return 0


def achar_filho(h, classe_contem=None, texto_exato=None, texto_limpo=None, so_visiveis=True):
    """Primeiro descendente por classe e/ou texto. texto_limpo ignora '&' (mnemonicos)."""
    for c in filhos(h, so_visiveis):
        if classe_contem and classe_contem not in classe(c):
            continue
        if texto_exato is not None and texto(c) != texto_exato:
            continue
        if texto_limpo is not None and texto(c).replace("&", "").strip() != texto_limpo:
            continue
        return c
    return 0


def filhos_por_classe(h, classe_contem, so_visiveis=True):
    return [c for c in filhos(h, so_visiveis) if classe_contem in classe(c)]


# ---------------------------------------------------------------- acoes
def bm_click(h) -> None:
    """Clique em botao/radio nativo. PostMessage: nao bloqueia se o botao abrir um modal."""
    user32.PostMessageW(h, BM_CLICK, 0, 0)


WM_COMMAND = 0x0111


def clicar_botao_dialogo(dlg, botao) -> None:
    """Botao de caixa #32770: WM_COMMAND(id, BN_CLICKED) para o dialogo. Funciona mesmo sem a caixa ativa
    (BM_CLICK falha nesse caso)."""
    cid = user32.GetDlgCtrlID(botao) & 0xFFFF
    user32.PostMessageW(dlg, WM_COMMAND, cid, botao)


def marcado(h) -> bool:
    r = ctypes.c_size_t()
    user32.SendMessageTimeoutW(h, BM_GETCHECK, 0, 0, SMTO_ABORTIFHUNG, 300, ctypes.byref(r))
    return int(r.value) == 1


def foco_atual(h_ref) -> int:
    """Controle com foco na thread de UI dona de h_ref (sem acessibilidade)."""
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    if user32.GetGUIThreadInfo(thread_da_janela(h_ref), ctypes.byref(gti)):
        return _h(gti.hwndFocus)
    return 0


def em_primeiro_plano(h) -> bool:
    return _h(user32.GetForegroundWindow()) == _h(h)


def trazer_para_frente(h) -> bool:
    if em_primeiro_plano(h):
        return True
    fg = user32.GetForegroundWindow()
    t_fg = user32.GetWindowThreadProcessId(fg, None)
    t_eu = kernel32.GetCurrentThreadId()
    anexou = False
    if t_fg and t_fg != t_eu:
        anexou = bool(user32.AttachThreadInput(t_eu, t_fg, True))
    try:
        user32.ShowWindow(h, 5)  # SW_SHOW (nao restaura/maximiza)
        user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
    finally:
        if anexou:
            user32.AttachThreadInput(t_eu, t_fg, False)
    return em_primeiro_plano(h)


# ---------------------------------------------------------------- dialogos do RM
def dialogo_rm(pid):
    """Caixa padrao do RM (#32770, titulo 'RM'). Retorna (hwnd, texto, botoes{texto:hwnd}) ou None."""
    for h in janelas_topo(pid):
        if classe(h) != "#32770":
            continue
        msg = ""
        botoes = {}
        for c in filhos(h):
            cls = classe(c)
            if cls == "Static" and user32.GetDlgCtrlID(c) == 65535:
                msg = texto(c)
            elif cls == "Button":
                botoes[texto(c).replace("&", "")] = c
        return h, msg, botoes
    return None


# ---------------------------------------------------------------- esperas
class TempoEsgotado(RuntimeError):
    pass


def esperar(cond, timeout: float, descricao: str, intervalo: float = 0.05):
    """Espera cond() retornar algo verdadeiro. Retorna o valor. Levanta TempoEsgotado."""
    t0 = time.perf_counter()
    fim = t0 + timeout
    while True:
        v = cond()
        if v:
            dt = time.perf_counter() - t0
            if dt >= 1.0:
                print(f"      (espera {dt:.1f}s: {descricao})", flush=True)
            return v
        if time.perf_counter() >= fim:
            raise TempoEsgotado(f"Tempo esgotado ({timeout:.0f}s) esperando: {descricao}")
        time.sleep(intervalo)
