# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle
from rpa_rm_faturamento.utils.timing import t

def tratar_wizard(max_wait_time: int) -> None:
    print("🧭 Tratando wizard Receber...")

    wizard = aguardar_controle(
        lambda: auto.PaneControl(Name="pnlWizard"),
        timeout=max_wait_time,
        descricao="wizard (pnlWizard)",
    )

    janela = wizard.GetTopLevelControl()

    # FIX AVD (Problema 10): "Agrupar Todos" pode não ter renderizado quando a
    # verificação instantânea (Exists 0,0) ocorre. Usar aguardar_controle com
    # timeout curto para dar margem à renderização antes de concluir que o
    # radio não existe nesta etapa.
    radio_agrupar = None
    try:
        radio_agrupar = aguardar_controle(
            lambda: auto.RadioButtonControl(searchFromControl=wizard, Name="Agrupar Todos"),
            timeout=5,
            descricao="radio Agrupar Todos",
        )
    except TimeoutError:
        radio_agrupar = None

    if radio_agrupar is not None and radio_agrupar.Exists(0, 0):
        print("🔘 Marcando 'Agrupar Todos'")
        radio_agrupar.Click()
        t(0.5)

        botao_next = aguardar_controle(
            lambda: auto.ButtonControl(searchFromControl=janela, Name="btnNext"),
            timeout=max_wait_time,
            descricao="botao Avancar",
        )

        botao_next.Click()

        # Buffer para AVD: aguarda renderização da próxima etapa do wizard
        print("⏳ Aguardando próxima etapa do wizard...")
        t(2.0)

        aguardar_controle(
            lambda: auto.WindowControl(Name="Faturar / Receber"),
            timeout=max_wait_time,
            descricao="janela wizard pós avanço",
        )

        t(1.0)
        return

    print("ℹ️ Etapa de agrupamento não exibida")


# =========================
# HELPERS
# =========================


def esperar_grid_populado(janela, timeout=30):
    """
    Aguarda o grid de tipos de movimento carregar dados reais.

    FIX AVD (Problema 4): a condição original (len(filhos) > 1) detectava
    header + spinner como "carregado". Agora verifica se ao menos um filho
    contém o valor "1.1.15" ou tem padrão de linha de dados, o que confirma
    que os dados reais chegaram.
    """
    print("⏳ Aguardando grid carregar conteúdo com 1.1.15...")

    inicio = time.time()

    while time.time() - inicio < timeout:
        try:
            grid = auto.TableControl(
                searchFromControl=janela,
                AutomationId="grdTipoMovimento"
            )

            if not grid.Exists(0, 0):
                time.sleep(0.5)
                continue

            filhos = grid.GetChildren()
            if not filhos or len(filhos) <= 1:
                time.sleep(0.5)
                continue

            # Verifica se algum filho/descendente contém "1.1.15"
            for ctrl, _ in auto.WalkControl(grid, maxDepth=5):
                try:
                    val = ""
                    try:
                        val = ctrl.GetLegacyIAccessiblePattern().Value
                    except Exception:
                        pass
                    if not val:
                        try:
                            val = ctrl.GetValuePattern().Value
                        except Exception:
                            pass
                    if val == "1.1.15":
                        print(f"✅ Grid carregado com 1.1.15 confirmado ({len(filhos)} filhos)")
                        return grid
                except Exception:
                    continue

            # Se tem filhos mas ainda não achou 1.1.15, aguarda mais um pouco
            print(f"⏳ Grid tem {len(filhos)} filhos mas 1.1.15 ainda não visível...")

        except Exception:
            pass

        time.sleep(0.5)

    raise TimeoutError("❌ Grid não carregou o conteúdo com 1.1.15")

def selecionar_row0_e_avancar(max_wait_time: int):
    print("🎯 Selecionando Row 0 (modo robusto AVD)")

    janela = auto.WindowControl(Name="Faturar / Receber")

    janela.SetActive()
    t(1.0)

    grid = esperar_grid_populado(janela, max_wait_time)

    print("🔍 Procurando célula com valor 1.1.15...")

    alvo = None

    for ctrl, _ in auto.WalkControl(grid, maxDepth=5):
        try:
            val = ""

            try:
                val = ctrl.GetLegacyIAccessiblePattern().Value
            except:
                pass

            if not val:
                try:
                    val = ctrl.GetValuePattern().Value
                except:
                    pass

            if val == "1.1.15":
                alvo = ctrl
                print("✅ Encontrado controle alvo:", ctrl.Name)
                break

        except:
            continue

    if not alvo:
        raise RuntimeError("❌ Não encontrou 1.1.15 após grid carregar")

    # clique seguro
    try:
        alvo.SetFocus()
        t(0.3)
        alvo.Click()
        t(0.5)
    except:
        rect = alvo.BoundingRectangle
        x = rect.left + (rect.right - rect.left) // 2
        y = rect.top + (rect.bottom - rect.top) // 2
        auto.Click(x, y)
        t(0.5)

    print("🔘 Clicando no botão Avançar")

    btn = auto.ButtonControl(searchFromControl=janela, AutomationId="btnNext")

    if btn.Exists(2, 0):
        btn.Click()
    else:
        rect = btn.BoundingRectangle
        auto.Click(
            rect.left + (rect.right - rect.left) // 2,
            rect.top + (rect.bottom - rect.top) // 2
        )

    # FIX AVD: buffer maior após Avançar no wizard — o RM precisa criar o
    # documento e iniciar o carregamento do formulário antes de aguardar_movimento_final
    # começar a buscar "Código Linha". Com TIMING_FACTOR=2.5 isso vira ~7.5s.
    t(3.0)


# =========================
# FUNÇÃO PRINCIPAL
# =========================

def selecionar_movimento_destino(tipo_movimento_destino: str, max_wait_time: int) -> None:
    print(f"🎯 Selecionando movimento destino: {tipo_movimento_destino}")

    # Fallback principal (AVD-safe): busca o valor "1.1.15" diretamente no grid
    print("🚀 Usando fallback por teclado (AVD-safe)")
    selecionar_row0_e_avancar(max_wait_time)
