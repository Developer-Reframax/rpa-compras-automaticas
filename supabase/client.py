# -*- coding: utf-8 -*-
from supabase import create_client, Client, ClientOptions

from rpa_rm_faturamento.config import Settings

# Timeout (s) das chamadas a edge functions. Generoso porque a reconstrução da
# fila invoca `validar-itens` (até 3 consultas ao RM, ~60s no pior caso) e
# `cria_produtos_a_faturar` (consulta TOTVS + inserts em lote). O padrão do
# client (60s) é apertado demais e cortaria um rebuild lento porém válido.
FUNCTION_CLIENT_TIMEOUT_S = 180


def get_supabase_client(settings: Settings) -> Client:
    options = ClientOptions(function_client_timeout=FUNCTION_CLIENT_TIMEOUT_S)
    return create_client(settings.supabase_url, settings.supabase_key, options=options)
