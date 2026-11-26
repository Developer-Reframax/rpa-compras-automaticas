# -*- coding: utf-8 -*-
"""RPA v2 - teste do ciclo de faturamento com o minimo de acessibilidade.

Uso (a partir da raiz do repositorio; -I evita a pasta logging/ do projeto):
    python -I rpa_v2\\run_teste.py                       # ciclo completo
    python -I rpa_v2\\run_teste.py --parar-em navegacao  # executa ate a etapa (inclusive)
    python -I rpa_v2\\run_teste.py --retomar-de itens    # comeca nesta etapa (RM ja no ponto certo)
    python -I rpa_v2\\run_teste.py --somente marcar      # so uma etapa

Etapas: login, navegacao, solicitacao, marcar, receber, wizard, movimento, itens, confirmacao
"""
import argparse
import ctypes
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:  # coordenadas fisicas (cliques pelo retangulo UIA)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from config_v2 import carregar_credenciais, LOTE_TESTE  # noqa: E402
from medidor import Medidor, log  # noqa: E402
from comum import Ctx  # noqa: E402
from etapas import inicio, faturar, movimento, itens, confirmacao  # noqa: E402
import w32 as win32  # noqa

ETAPAS = [
    ("login", inicio.login),
    ("navegacao", inicio.navegacao),
    ("solicitacao", inicio.solicitacao),
    ("marcar", faturar.marcar),
    ("receber", faturar.receber),
    ("wizard", faturar.wizard),
    ("movimento", movimento.movimento),
    ("itens", itens.itens),
    ("confirmacao", confirmacao.confirmacao),
]
NOMES = [n for n, _ in ETAPAS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parar-em", choices=NOMES)
    ap.add_argument("--retomar-de", choices=NOMES)
    ap.add_argument("--somente", choices=NOMES)
    a = ap.parse_args()

    ini = NOMES.index(a.somente or a.retomar_de or "login")
    fim = NOMES.index(a.somente or a.parar_em or "confirmacao")

    cred = carregar_credenciais()
    med = Medidor()
    pid = inicio.achar_pid(cred["processo"], cred["exe"])
    ctx = Ctx(pid, cred, LOTE_TESTE, med)
    log(f"RPA v2 | RM pid={pid or '-'} | etapas {NOMES[ini]} -> {NOMES[fim]} | saida: {med.arquivo}")
    if ini > 0:  # retomando: precisa da janela principal e (se ja passou da solicitacao) da visao
        ctx.main = inicio.janela_principal(ctx)
        ctx.form_sol = inicio._form_solicitacao(ctx) if ctx.main else 0

    ok = False
    try:
        for nome, fn in ETAPAS[ini:fim + 1]:
            with med.etapa(nome):
                fn(ctx)
        ok = True
    except Exception as e:
        log(f"FALHOU: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        med.salvar(ok=ok, numero_gerado=ctx.numero_gerado)
        log(f"{'OK' if ok else 'ERRO'} | total {sum(x['ms'] for x in med.etapas)} ms | tempos em {med.arquivo}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
