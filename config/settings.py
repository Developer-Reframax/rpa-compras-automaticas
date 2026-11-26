# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Optional

from .constants import (
    RM_PROCESS_NAME,
    RM_LOGIN_WINDOW_TITLE,
    RM_SOLICITACAO_WINDOW_TITLE,
    TIPO_MOVIMENTO_ORIGEM,
    TIPO_MOVIMENTO_DESTINO,
    MAX_WAIT_TIME,
    AUTO_GLOBAL_SEARCH_TIMEOUT,
    TIMING_FACTOR,
)


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _get_env_int(name: str, default: int) -> int:
    value = _get_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Variavel de ambiente invalida para {name}: {value}") from exc


def _get_env_float(name: str, default: float) -> float:
    value = _get_env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Variavel de ambiente invalida para {name}: {value}") from exc


def _require_env(name: str) -> str:
    value = _get_env(name)
    if value is None:
        raise ValueError(f"Variavel de ambiente obrigatoria nao informada: {name}")
    return value


def _load_dev_config(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"Arquivo de configuracao DEV nao encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Settings:
    # RM
    rm_process_name: str
    rm_executable_path: str
    rm_login_window_title: str
    rm_solicitacao_window_title: str
    rm_usuario: str
    rm_senha: str

    # Movimentos
    tipo_movimento_origem: str
    tipo_movimento_destino: str

    # Tempos
    max_wait_time: int
    auto_global_search_timeout: int
    # Fator de timing: 1.0=LOCAL, 2.5=AVD (multiplica todos os sleeps críticos)
    timing_factor: float

    # Supabase
    supabase_url: str
    supabase_key: str
    supabase_table_dados: str
    supabase_table_logs: str

    # Parametros de negocio
    historico_movimento: str

    # Logging
    log_level: str
    log_file_path: str
    log_max_bytes: int
    log_backup_count: int


def load_settings() -> Settings:
    env = (_get_env("RPA_ENV", "DEV") or "DEV").upper()
    if env == "PROD":
        return Settings(
            rm_process_name=_get_env("RM_PROCESS_NAME", RM_PROCESS_NAME),
            rm_executable_path=_require_env("RM_EXECUTABLE_PATH"),
            rm_login_window_title=_get_env("RM_LOGIN_WINDOW_TITLE", RM_LOGIN_WINDOW_TITLE),
            rm_solicitacao_window_title=_get_env(
                "RM_SOLICITACAO_WINDOW_TITLE", RM_SOLICITACAO_WINDOW_TITLE
            ),
            rm_usuario=_require_env("RM_USUARIO"),
            rm_senha=_require_env("RM_SENHA"),
            tipo_movimento_origem=_get_env("TIPO_MOVIMENTO_ORIGEM", TIPO_MOVIMENTO_ORIGEM),
            tipo_movimento_destino=_get_env("TIPO_MOVIMENTO_DESTINO", TIPO_MOVIMENTO_DESTINO),
            max_wait_time=_get_env_int("MAX_WAIT_TIME", MAX_WAIT_TIME),
            auto_global_search_timeout=_get_env_int(
                "AUTO_GLOBAL_SEARCH_TIMEOUT", AUTO_GLOBAL_SEARCH_TIMEOUT
            ),
            timing_factor=_get_env_float("TIMING_FACTOR", TIMING_FACTOR),
            supabase_url=_require_env("SUPABASE_URL"),
            supabase_key=_require_env("SUPABASE_KEY"),
            supabase_table_dados=_get_env("SUPABASE_TABLE_DADOS", "dados_lof_rpa"),
            supabase_table_logs=_get_env("SUPABASE_TABLE_LOGS", "rpa_logs"),
            historico_movimento=_get_env(
                "HISTORICO_MOVIMENTO",
                "Movimento criado automaticamente pelo RPA de pedidos automaticos.",
            ),
            log_level=_get_env("LOG_LEVEL", "INFO"),
            log_file_path=_get_env("LOG_FILE_PATH", "logs/rpa_rm_faturamento.log"),
            log_max_bytes=_get_env_int("LOG_MAX_BYTES", 5 * 1024 * 1024),
            log_backup_count=_get_env_int("LOG_BACKUP_COUNT", 5),
        )

    # DEV usa arquivo local de configuracao
    cfg_path = Path(_get_env("DEV_CONFIG_PATH", "rpa_rm_faturamento/config/dev_settings.json"))
    cfg = _load_dev_config(cfg_path)

    return Settings(
        rm_process_name=cfg.get("RM_PROCESS_NAME", RM_PROCESS_NAME),
        rm_executable_path=cfg["RM_EXECUTABLE_PATH"],
        rm_login_window_title=cfg.get("RM_LOGIN_WINDOW_TITLE", RM_LOGIN_WINDOW_TITLE),
        rm_solicitacao_window_title=cfg.get(
            "RM_SOLICITACAO_WINDOW_TITLE", RM_SOLICITACAO_WINDOW_TITLE
        ),
        rm_usuario=cfg["RM_USUARIO"],
        rm_senha=cfg["RM_SENHA"],
        tipo_movimento_origem=cfg.get("TIPO_MOVIMENTO_ORIGEM", TIPO_MOVIMENTO_ORIGEM),
        tipo_movimento_destino=cfg.get("TIPO_MOVIMENTO_DESTINO", TIPO_MOVIMENTO_DESTINO),
        max_wait_time=int(cfg.get("MAX_WAIT_TIME", MAX_WAIT_TIME)),
        auto_global_search_timeout=int(
            cfg.get("AUTO_GLOBAL_SEARCH_TIMEOUT", AUTO_GLOBAL_SEARCH_TIMEOUT)
        ),
        timing_factor=float(cfg.get("TIMING_FACTOR", TIMING_FACTOR)),
        supabase_url=cfg["SUPABASE_URL"],
        supabase_key=cfg["SUPABASE_KEY"],
        supabase_table_dados=cfg.get("SUPABASE_TABLE_DADOS", "dados_lof_rpa"),
        supabase_table_logs=cfg.get("SUPABASE_TABLE_LOGS", "rpa_logs"),
        historico_movimento=cfg.get(
            "HISTORICO_MOVIMENTO",
            "Movimento criado automaticamente pelo RPA de pedidos automaticos.",
        ),
        log_level=cfg.get("LOG_LEVEL", "INFO"),
        log_file_path=cfg.get("LOG_FILE_PATH", "logs/rpa_rm_faturamento.log"),
        log_max_bytes=int(cfg.get("LOG_MAX_BYTES", 5 * 1024 * 1024)),
        log_backup_count=int(cfg.get("LOG_BACKUP_COUNT", 5)),
    )
