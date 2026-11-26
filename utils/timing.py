# -*- coding: utf-8 -*-
"""
Módulo de timing escalonável para AVD.

O fator padrão é 1.0 (LOCAL). Em AVD, defina TIMING_FACTOR=2.5 (ou outro valor)
no arquivo de configuração ou variável de ambiente.

Uso:
    from rpa_rm_faturamento.utils.timing import t

    t(1.0)   # dorme 1.0s em LOCAL, 2.5s com fator 2.5 (AVD)

O fator é configurado uma única vez no startup do RPA via configurar_factor().
"""

import time

_factor: float = 1.0


def configurar_factor(factor: float) -> None:
    """Define o multiplicador global de timing. Chamar uma vez no main()."""
    global _factor
    _factor = max(0.1, float(factor))
    print(f"⏱️  Timing factor configurado: {_factor}x")


def t(segundos: float) -> None:
    """Sleep escalonado pelo timing_factor (LOCAL=1.0, AVD=2.5)."""
    time.sleep(segundos * _factor)


def get_factor() -> float:
    """Retorna o fator atual (útil para calcular timeouts derivados)."""
    return _factor
