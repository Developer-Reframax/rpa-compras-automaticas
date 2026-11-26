# -*- coding: utf-8 -*-
"""Cronometro por etapa + log simples (console e JSON em rpa_v2/saida/)."""
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime

PASTA_SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saida")


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S.%f}"[:-3] + f"] {msg}", flush=True)


class Medidor:
    def __init__(self):
        self.inicio = time.perf_counter()
        self.etapas = []
        self.marcas = []
        os.makedirs(PASTA_SAIDA, exist_ok=True)
        self.arquivo = os.path.join(PASTA_SAIDA, f"tempos_{datetime.now():%Y%m%d_%H%M%S}.json")

    @contextmanager
    def etapa(self, nome: str):
        log(f"=== {nome} ...")
        t0 = time.perf_counter()
        erro = None
        try:
            yield
        except BaseException as e:
            erro = f"{type(e).__name__}: {e}"
            raise
        finally:
            ms = round((time.perf_counter() - t0) * 1000)
            self.etapas.append({"etapa": nome, "ms": ms, "erro": erro})
            log(f"=== {nome}: {ms} ms" + (f"  ERRO: {erro}" if erro else ""))
            self.salvar()

    def marca(self, nome: str, **dados):
        """Sub-tempos dentro de uma etapa (ms desde o inicio da execucao)."""
        ms = round((time.perf_counter() - self.inicio) * 1000)
        self.marcas.append({"t_ms": ms, "marca": nome, **dados})
        log(f"   - {nome} {dados if dados else ''}")

    def salvar(self, **extra):
        dados = {
            "total_ms": round((time.perf_counter() - self.inicio) * 1000),
            "etapas": self.etapas,
            "marcas": self.marcas,
            **extra,
        }
        with open(self.arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
