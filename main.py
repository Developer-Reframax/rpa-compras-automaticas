# -*- coding: utf-8 -*-
from __future__ import annotations

import uuid

from rpa_rm_faturamento.config import load_settings
from rpa_rm_faturamento.logging import build_logger
from rpa_rm_faturamento.orchestrator import RpaOrchestrator
from rpa_rm_faturamento.services import FaturamentoService, FilaService
from rpa_rm_faturamento.supabase import DadosLofRepository, LotesRpaRepository, get_supabase_client
from rpa_rm_faturamento.utils.timing import configurar_factor


def main() -> None:
    settings = load_settings()
    # Aplica o fator de timing globalmente (LOCAL=1.0, AVD=2.5)
    configurar_factor(settings.timing_factor)
    execution_id = uuid.uuid4().hex

    supabase_client = get_supabase_client(settings)
    logger = build_logger(settings, supabase_client, execution_id)

    repository = DadosLofRepository(supabase_client, settings.supabase_table_dados)
    lotes_repository = LotesRpaRepository(supabase_client)
    service = FaturamentoService(settings, logger)
    fila_service = FilaService(supabase_client, repository, lotes_repository, logger)
    orchestrator = RpaOrchestrator(
        settings, repository, lotes_repository, service, fila_service, logger
    )

    try:
        orchestrator.run()
    except Exception:
        logger.exception("ORQUESTRADOR", "Erro fatal na execucao")
        raise


if __name__ == "__main__":
    main()
