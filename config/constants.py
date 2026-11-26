# -*- coding: utf-8 -*-

# Constantes do RM
RM_PROCESS_NAME = "RM.exe"
RM_LOGIN_WINDOW_TITLE = "TOTVS"
RM_SOLICITACAO_WINDOW_TITLE = "Solicitação de Compras (Gestão Compras)"

# Tipos de movimento
TIPO_MOVIMENTO_ORIGEM = "1.1.04"
TIPO_MOVIMENTO_DESTINO = "1.1.15"

# Tempos
MAX_WAIT_TIME = 60

# Timeout global do uiautomation para Exists().
# 8s suporta a latência de renderização de UI da AVD via RDP.
# Em ambiente local (renderização imediata) o overhead extra é desprezível.
AUTO_GLOBAL_SEARCH_TIMEOUT = 8

# Fator de timing padrão (LOCAL=1.0, AVD=2.5).
# Lido pelo settings.py e aplicado em utils/timing.py no startup.
TIMING_FACTOR = 1.0
