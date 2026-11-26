# -*- coding: utf-8 -*-
"""Teclado e mouse via SendInput (sem acessibilidade).

- digitar(): caracteres unicode (KEYEVENTF_UNICODE) -> chega como WM_CHAR, funciona em campos
  com mascara e nao depende do layout de teclado;
- atalho("ctrl+enter"), atalho("alt+s"), teclas("tab"), keytips("C", "O", "S").
"""
import ctypes
import ctypes.wintypes as w
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _U)]


user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "esc": 0x1B, "space": 0x20, "pgup": 0x21, "pgdn": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "ins": 0x2D, "del": 0x2E,
    "f2": 0x71, "f4": 0x73, "f5": 0x74,
}
_EXTENDIDAS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}


def _vk(nome: str) -> int:
    nome = nome.lower()
    if nome in VK:
        return VK[nome]
    if len(nome) == 1:
        return user32.VkKeyScanW(ord(nome)) & 0xFF
    raise ValueError(f"tecla desconhecida: {nome}")


def _tecla(vk: int, solta: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if solta else 0
    if vk in _EXTENDIDAS:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, 0)
    i = INPUT(type=INPUT_KEYBOARD)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def _enviar(lista):
    arr = (INPUT * len(lista))(*lista)
    user32.SendInput(len(lista), arr, ctypes.sizeof(INPUT))


def atalho(combo: str, pausa: float = 0.03):
    """Ex.: 'ctrl+enter', 'alt+s', 'ctrl+pgdn', 'tab', 'ctrl+a'."""
    partes = [_vk(p) for p in combo.split("+")]
    seq = [_tecla(v, False) for v in partes] + [_tecla(v, True) for v in reversed(partes)]
    _enviar(seq)
    time.sleep(pausa)


def teclas(*nomes, pausa: float = 0.03):
    for n in nomes:
        atalho(n, pausa)


def digitar(texto: str, intervalo: float = 0.0):
    """Digita texto unicode. intervalo>0 digita caractere a caractere (campos com mascara)."""
    if intervalo <= 0:
        seq = []
        for ch in texto:
            for solta in (False, True):
                i = INPUT(type=INPUT_KEYBOARD)
                i.ki = KEYBDINPUT(0, ord(ch), KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if solta else 0), 0, 0)
                seq.append(i)
        if seq:
            _enviar(seq)
        time.sleep(0.03)
        return
    for ch in texto:
        digitar(ch)
        time.sleep(intervalo)


def keytips(*letras, pausa: float = 0.25):
    """Ribbon: toca Alt sozinho e depois as letras das KeyTips (ex.: 'c','o','s')."""
    atalho("alt", pausa)
    for l in letras:
        atalho(l, pausa)


def clicar(x: int, y: int, duplo: bool = False):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    n = 2 if duplo else 1
    seq = []
    for _ in range(n):
        for f in (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
            i = INPUT(type=INPUT_MOUSE)
            i.mi = MOUSEINPUT(0, 0, 0, f, 0, 0)
            seq.append(i)
    _enviar(seq)
    time.sleep(0.05)
