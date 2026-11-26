# -*- coding: utf-8 -*-
import time
from comtypes import COMError


def aguardar_controle(factory, timeout=30, intervalo=0.5, descricao="controle"):
    start = time.time()

    while True:
        try:
            ctrl = factory()
            if ctrl and ctrl.Exists(0, 0):
                return ctrl
        except (COMError, LookupError):
            # COM invalido ou controle recriado
            pass
        except Exception:
            pass

        if time.time() - start > timeout:
            raise TimeoutError(f"❌ Timeout aguardando {descricao}")

        time.sleep(intervalo)


def aguardar_controle_sumir(factory, timeout=60, intervalo=0.5, descricao="controle"):
    print(f"⏳ Aguardando {descricao} fechar...")

    start = time.time()

    while True:
        try:
            ctrl = factory()
            if not ctrl or not ctrl.Exists(0, 0):
                print(f"✅ {descricao} fechado.")
                return
        except (COMError, LookupError):
            # controle ja nao existe mais
            print(f"✅ {descricao} fechado.")
            return
        except Exception:
            pass

        if time.time() - start > timeout:
            raise TimeoutError(f"❌ Timeout aguardando {descricao} fechar")

        time.sleep(intervalo)
