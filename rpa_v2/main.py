# -*- coding: utf-8 -*-
"""RPA v2 - PRODUCAO. Mesmo ciclo de lotes do v1 (lotes_faturamento_rpa / dados_lof_rpa / rpa_logs),
com as etapas de tela do v2.

Uso (a partir da raiz do repositorio; -I evita a pasta logging/ do projeto):
    python -I rpa_v2\\main.py

Configuracao: mesmo dev_settings.json do v1 (env DEV_CONFIG_PATH ou config/dev_settings.json).
Codigo de saida: 0 = execucao finalizada; 1 = erro fatal (igual ao v1).
"""
import ctypes
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:  # coordenadas fisicas (cliques pelo retangulo UIA)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from comum import Ctx  # noqa: E402
from config_v2 import carregar_settings  # noqa: E402
from etapas import inicio  # noqa: E402
from medidor import Medidor, log  # noqa: E402
from orquestrador import OrquestradorV2  # noqa: E402
from rpa_log import build_logger  # noqa: E402
from supa import DadosLofRepository, FilaService, LotesRpaRepository, get_supabase_client  # noqa: E402


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="RPA v2 - faturamento dos lotes PENDENTE (producao)")
    ap.add_argument("--lote", type=int, help="processa somente este lote (se estiver PENDENTE)")
    ap.add_argument("--max-lotes", type=int, help="para apos N lotes processados")
    args = ap.parse_args()
    settings = carregar_settings()
    execution_id = uuid.uuid4().hex
    client = get_supabase_client(settings)
    logger = build_logger(settings, client, execution_id)

    dados = DadosLofRepository(client, settings["supabase_table_dados"])
    lotes = LotesRpaRepository(client)
    fila = FilaService(client, dados, lotes, logger)

    cred = {
        "usuario": settings["rm_usuario"],
        "senha": settings["rm_senha"],
        "exe": settings["rm_executable_path"],
        "processo": settings["rm_process_name"],
    }
    med = Medidor()
    ctx = Ctx(inicio.achar_pid(cred["processo"], cred["exe"]), cred, None, med)
    ctx.logger = logger
    log(f"RPA v2 producao | execution_id={execution_id} | tempos em {med.arquivo}")

    try:
        OrquestradorV2(ctx, settings, dados, lotes, fila, logger,
                       lote_fixo=args.lote, max_lotes=args.max_lotes).run()
    except Exception:
        logger.exception("ORQUESTRADOR", "Erro fatal na execucao")
        med.salvar(ok=False)
        return 1
    med.salvar(ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
