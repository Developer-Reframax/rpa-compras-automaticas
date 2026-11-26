# -*- coding: utf-8 -*-
"""Leitura de pixels da tela pela GDI do Windows, em memoria (nenhuma imagem e salva em disco).
Usado para conferir o checkbox Faturar no grid de itens SEM acessibilidade (o grid do RM fica pesado
quando consultado pela acessibilidade)."""
import ctypes
import ctypes.wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
                ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


# Tipos declarados: handles sao de 64 bits (sem isso o ctypes estoura com "int too long")
user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = w.HDC
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = w.HBITMAP
gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ
gdi32.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC,
                         ctypes.c_int, ctypes.c_int, w.DWORD]
gdi32.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.c_void_p, w.UINT]
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteDC.argtypes = [w.HDC]


def capturar(x0, y0, x1, y1):
    """Retorna (largura, altura, lista de luminancias 0-255 linha a linha) da regiao da tela."""
    larg, alt = max(1, x1 - x0), max(1, y1 - y0)
    tela = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(tela)
    bmp = gdi32.CreateCompatibleBitmap(tela, larg, alt)
    antigo = gdi32.SelectObject(mem, bmp)
    try:
        gdi32.BitBlt(mem, 0, 0, larg, alt, tela, x0, y0, SRCCOPY)
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = larg, -alt, 1, 32
        buf = (ctypes.c_ubyte * (larg * alt * 4))()
        gdi32.GetDIBits(mem, bmp, 0, alt, buf, ctypes.byref(bi), DIB_RGB_COLORS)
        lum = [int(0.114 * buf[i] + 0.587 * buf[i + 1] + 0.299 * buf[i + 2]) for i in range(0, len(buf), 4)]
        return larg, alt, lum
    finally:
        gdi32.SelectObject(mem, antigo)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(0, tela)


def checkbox(cx, cy, raio=4, margem=11):
    """Mede o miolo do checkbox (quadrado de lado 2*raio+1 no centro) contra o fundo da celula (faixas a
    'margem' px para os lados). Retorna (pixels_escuros_no_miolo, luminancia_fundo).
    Escuro = bem mais escuro que o fundo (vale para linha normal ou selecionada)."""
    x0, y0 = cx - margem - 2, cy - raio
    larg, alt, lum = capturar(x0, y0, cx + margem + 3, cy + raio + 1)
    fundo_px = []
    miolo = []
    for yy in range(alt):
        for xx in range(larg):
            v = lum[yy * larg + xx]
            dx = (x0 + xx) - cx
            if abs(dx) <= raio:
                miolo.append(v)
            elif abs(dx) >= margem:
                fundo_px.append(v)
    fundo = sorted(fundo_px)[len(fundo_px) // 2] if fundo_px else 255
    escuros = sum(1 for v in miolo if v < fundo - 70)
    return escuros, fundo


def tem_conteudo(x0, x1, cy, meia_altura=4, min_px=6):
    """A linha tem texto na faixa [x0,x1] (pixels bem mais escuros que o fundo da propria faixa)?"""
    larg, alt, lum = capturar(x0, cy - meia_altura, x1, cy + meia_altura + 1)
    fundo = sorted(lum)[int(len(lum) * 0.8)] if lum else 255
    escuros = sum(1 for v in lum if v < fundo - 80)
    return escuros >= min_px, escuros


def assinatura(x0, x1, cy, meia_altura=6):
    """'Impressao digital' do texto desenhado numa faixa (ex.: codigo do produto na 1a linha): mapa binario
    de pixels escuros. Muda quando o conteudo da linha muda (outro produto)."""
    larg, alt, lum = capturar(x0, cy - meia_altura, x1, cy + meia_altura + 1)
    fundo = sorted(lum)[int(len(lum) * 0.8)] if lum else 255
    return tuple(1 if v < fundo - 80 else 0 for v in lum)
