# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle


def localizar_campo_aliquota_gbtributacao(janela_item):
    """
    Localiza o Edit 'cAliquota' EXATAMENTE na hierarquia:
    Tributos -> gbTributacao -> Pane '' -> Pane '' -> Edit 'cAliquota'

    E valida o painel correto por "ancoras" que aparecem no seu print:
    - ComboBox 'Calculado'
    - Edit 'cValor'
    - Edit 'cBaseCalculo'
    - Text 'Manter Valor:' (opcional, mas ajuda muito)
    """

    grp_tributos = aguardar_controle(
        lambda: auto.GroupControl(searchFromControl=janela_item, Name="Tributos"),
        timeout=20,
        descricao="grupo Tributos",
    )

    grp_gb = aguardar_controle(
        lambda: auto.GroupControl(searchFromControl=grp_tributos, Name="gbTributacao"),
        timeout=20,
        descricao="grupo gbTributacao",
    )

    inicio = time.time()
    timeout_total = 20  # tempo seguro para o RM bindar o painel apos selecionar o tributo

    def painel_tem_ancoras(pane_2):
        """Valida que o pane_2 e o painel certo (o do print)."""
        try:
            # ancoras fortes do print
            ok_calculado = auto.ComboBoxControl(searchFromControl=pane_2, Name="Calculado").Exists(0, 0)
            ok_cvalor = auto.EditControl(searchFromControl=pane_2, Name="cValor").Exists(0, 0)
            ok_cbase = auto.EditControl(searchFromControl=pane_2, Name="cBaseCalculo").Exists(0, 0)

            # ancora extra (nem sempre existe igual, entao deixo como "ajuda", nao obrigatorio)
            ok_manter_valor = auto.TextControl(searchFromControl=pane_2, Name="Manter Valor:").Exists(0, 0)

            # regra: precisa ter as 3 ancoras principais
            if ok_calculado and ok_cvalor and ok_cbase:
                return True

            # fallback: algumas telas podem nao ter cBaseCalculo visivel,
            # mas se tiver Calculado + cValor + Manter Valor, tambem e bem confiavel
            if ok_calculado and ok_cvalor and ok_manter_valor:
                return True
        except Exception:
            return False

        return False

    while True:
        # 1) Pane nivel 1 (filho direto do gbTributacao) — normalmente Name vazio
        panes_nivel_1 = [c for c in grp_gb.GetChildren() if c.ControlTypeName == "PaneControl"]

        for pane_1 in panes_nivel_1:
            # 2) Pane nivel 2 (filho do pane_1) — normalmente Name vazio
            panes_nivel_2 = [c for c in pane_1.GetChildren() if c.ControlTypeName == "PaneControl"]

            for pane_2 in panes_nivel_2:
                # 3) Valida que e o painel correto do print
                if not painel_tem_ancoras(pane_2):
                    continue

                # 4) Agora sim: pega o cAliquota desse painel correto
                campo_aliquota = auto.EditControl(searchFromControl=pane_2, Name="cAliquota")
                if campo_aliquota.Exists(0, 0):
                    return campo_aliquota

        if time.time() - inicio > timeout_total:
            raise RuntimeError(
                "❌ Nao encontrei o 'cAliquota' no painel correto (gbTributacao -> Pane -> Pane) "
                "com as ancoras esperadas (Calculado/cValor/cBaseCalculo)."
            )

        time.sleep(0.3)


def preencher_aliquota(janela_item, codigo_tributo: str, aliquota: str) -> None:
    print(f"🧾 Preenchendo {codigo_tributo} com aliquota {aliquota}")

    tabela = aguardar_controle(
        lambda: auto.TableControl(searchFromControl=janela_item, Name="dgvTributos"),
        descricao="tabela tributos",
    )

    for linha in tabela.GetChildren():
        if linha.ControlTypeName not in ("DataItemControl", "CustomControl"):
            continue

        codigo_encontrado = None

        for cel in linha.GetChildren():
            if cel.ControlTypeName == "HeaderControl":
                continue

            try:
                vp = cel.GetValuePattern()
                valor = (vp.Value or "").strip()
            except Exception:
                continue

            if cel.Name.startswith("Código do Tributo"):
                codigo_encontrado = valor
                break

        if codigo_encontrado != codigo_tributo:
            continue

        print(f"✅ Tributo {codigo_tributo} encontrado")

        # Seleciona a linha SEM entrar em edicao no grid
        try:
            linha.Click()
        except Exception:
            pass

        time.sleep(0.3)

        # Garante foco fora da celula de aliquota do grid
        try:
            linha.SendKeys("{Esc}")
        except Exception:
            pass

        time.sleep(0.6)

        # Agora o painel esta corretamente bindado
        campo = localizar_campo_aliquota_gbtributacao(janela_item)

        vp_campo = campo.GetValuePattern()
        vp_campo.SetValue("")
        time.sleep(0.1)
        vp_campo.SetValue(str(aliquota))

        campo.SendKeys("\t")
        time.sleep(0.5)

        print(f"✅ Aliquota {codigo_tributo} preenchida corretamente")
        return

    print(f"⚠️ Tributo {codigo_tributo} nao encontrado")
