# -*- coding: utf-8 -*-
import time
import subprocess
from enum import Enum
import uiautomation as auto
import psutil


class EstadoRM(Enum):
    UPDATE = "update"
    LOGIN = "login"
    PRINCIPAL = "principal"
    SOLICITACAO = "solicitacao"
    FILTRO = "filtro"
    PENDENTES = "pendentes"
    WIZARD = "wizard"
    SELECAO_DESTINO = "selecao_destino"
    MOVIMENTO_FINAL = "movimento_final"
    NAVBAR = "navbar"
    IDENTIFICACAO = "identificacao"
    FIM = "fim"


def rm_esta_aberto(process_name: str) -> bool:
    return any(
        p.info.get("name", "").lower() == process_name.lower()
        for p in psutil.process_iter(attrs=["name"])
    )


def abrir_rm(executable_path: str) -> None:
    print("🚀 Abrindo RM...")
    subprocess.Popen(executable_path)


def fechar_rm(process_name: str, timeout: float = 10.0) -> int:
    """
    Encerra COMPLETAMENTE o RM — todas as instâncias do processo.

    Usado na recuperação de erro crítico: quando o RPA perde o controle da UI
    do RM, fechar e reabrir o processo é o reset mais confiável para um estado
    conhecido. Tenta terminate() (encerramento gracioso) e, no que sobrar após
    o timeout, aplica kill() (forçado).

    Retorna a quantidade de processos sinalizados.
    """
    print("🛑 Fechando RM completamente...")
    alvo = (process_name or "").lower()

    procs = []
    for proc in psutil.process_iter(attrs=["name"]):
        try:
            if (proc.info.get("name") or "").lower() == alvo:
                procs.append(proc)
        except Exception:
            continue

    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass

    try:
        _, alive = psutil.wait_procs(procs, timeout=timeout)
    except Exception:
        alive = procs

    for p in alive:
        try:
            p.kill()
        except Exception:
            pass

    print(f"🛑 RM encerrado ({len(procs)} processo(s)).")
    return len(procs)


def rm_em_atualizacao() -> bool:
    try:
        for win in auto.GetRootControl().GetChildren():
            try:
                for c, _ in auto.WalkControl(win, maxDepth=5):
                    if c.ControlTypeName == "TextControl" and c.Name:
                        t = c.Name.lower()
                        if any(p in t for p in ["atualiz", "verificando", "carregando", "versão"]):
                            return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def aguardar_fim_atualizacao(timeout=300) -> None:
    print("🔄 RM em atualização...")
    start = time.time()
    while True:
        if not rm_em_atualizacao():
            print("✅ Atualização finalizada.")
            time.sleep(2)
            return
        if time.time() - start > timeout:
            raise TimeoutError("❌ Atualização do RM excedeu o tempo limite")
        time.sleep(2)


def detectar_estado_rm(login_window_title: str, solicitacao_window_title: str):
    try:
        if rm_em_atualizacao():
            return EstadoRM.UPDATE
    except Exception:
        pass

    # 🔥 NOVO BLOCO - DETECÇÃO DE MOVIMENTO
    try:
        for win in auto.GetRootControl().GetChildren():
            try:
                nome = win.Name or ""
                if "Movimento:" in nome:
                    return EstadoRM.MOVIMENTO_FINAL
            except:
                continue
    except:
        pass

    try:
        if auto.WindowControl(Name=login_window_title).Exists(0, 0):
            return EstadoRM.LOGIN
    except Exception:
        pass

    try:
        if auto.WindowControl(Name=solicitacao_window_title).Exists(0, 0):
            return EstadoRM.SOLICITACAO
    except Exception:
        pass

    try:
        for win in auto.GetRootControl().GetChildren():
            try:
                if auto.PaneControl(searchFromControl=win, Name="mdiRibbonControl").Exists(0, 0):
                    return EstadoRM.PRINCIPAL
            except Exception:
                continue
    except Exception:
        pass

    return None

def aguardar_estado(target_estado: EstadoRM, timeout=20):
    print(f"⏳ Aguardando estado: {target_estado.value}")

    start = time.time()

    while True:
        estado = detectar_estado_rm("", "")

        if estado == target_estado:
            print(f"✅ Estado atingido: {estado.value}")
            return estado

        if time.time() - start > timeout:
            raise TimeoutError(f"❌ Timeout aguardando estado {target_estado.value}")

        time.sleep(0.5)
