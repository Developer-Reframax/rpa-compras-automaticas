# -*- coding: utf-8 -*-
"""Configuracao do teste v2: credenciais do dev_settings.json do projeto + lote fixo (sem Supabase)."""
import json
import os
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV_SETTINGS = os.path.join(RAIZ, "config", "dev_settings.json")


def carregar_settings() -> dict:
    """Mesmas chaves/defaults do v1 (config/settings.py). Arquivo: env DEV_CONFIG_PATH ou
    config/dev_settings.json do repositorio."""
    caminho = os.environ.get("DEV_CONFIG_PATH") or DEV_SETTINGS
    with open(caminho, encoding="utf-8") as f:
        d = json.load(f)

    def g(k, default=None):
        v = d.get(k)
        return default if v in (None, "") else v

    return {
        "rm_executable_path": g("RM_EXECUTABLE_PATH"),
        "rm_usuario": g("RM_USUARIO"),
        "rm_senha": g("RM_SENHA"),
        "rm_process_name": g("RM_PROCESS_NAME", "RM.exe"),
        "tipo_movimento_origem": g("TIPO_MOVIMENTO_ORIGEM", "1.1.04"),
        "tipo_movimento_destino": g("TIPO_MOVIMENTO_DESTINO", "1.1.15"),
        "supabase_url": g("SUPABASE_URL"),
        "supabase_key": g("SUPABASE_KEY"),
        "supabase_table_dados": g("SUPABASE_TABLE_DADOS", "dados_lof_rpa"),
        "supabase_table_logs": g("SUPABASE_TABLE_LOGS", "rpa_logs"),
        "log_level": g("LOG_LEVEL", "INFO"),
        "log_file_path": g("LOG_FILE_PATH", "logs/rpa_rm_faturamento.log"),
        "log_max_bytes": int(g("LOG_MAX_BYTES", 5 * 1024 * 1024)),
        "log_backup_count": int(g("LOG_BACKUP_COUNT", 5)),
    }


RM_HOMOLOGACAO = r"C:\TOTVS\RM.NET.TESTE\RM.EXE"


def carregar_credenciais():
    """Credenciais para o run_teste: SEMPRE o RM de homologacao (env RM_EXE_TESTE para trocar)."""
    with open(DEV_SETTINGS, encoding="utf-8") as f:
        d = json.load(f)
    return {
        "usuario": d["RM_USUARIO"],
        "senha": d["RM_SENHA"],
        "exe": os.environ.get("RM_EXE_TESTE") or RM_HOMOLOGACAO,
        "processo": d.get("RM_PROCESS_NAME") or "RM.exe",
    }


# Lote de teste (homologacao). Item casado por codigo do produto; seq e conferencia.
LOTE_TESTE = {
    "filial": "17",
    "tipo_mov_origem": "1.1.04",
    "tipo_mov_destino": "1.1.15",
    "movimentos": ["048630", "048712", "048722"],
    "cnpj_fornecedor": "11.368.297/0001-69",
    "cod_comprador": "00171",
    "cod_pagamento": "040",
    "tipo_frete": "CIF",
    "data_entrega": (date.today() + timedelta(days=15)).strftime("%d/%m/%Y"),
    "justificativa": "Teste RPA v2",
    "itens": [
        {"seq": 2, "cod_prd": "71.02.019", "preco": 10.00, "ipi": 5, "icms": 18},
        {"seq": 3, "cod_prd": "68.02.005", "preco": 4.00, "ipi": 0, "icms": 0},
    ],
}


def num_br(v, casas=None) -> str:
    """10 -> '10,00' (casas=2) ; 5 -> '5' ; 5.2 -> '5,2'."""
    if casas is not None:
        return f"{float(v):.{casas}f}".replace(".", ",")
    f = float(v)
    s = str(int(f)) if f.is_integer() else repr(f)
    return s.replace(".", ",")
