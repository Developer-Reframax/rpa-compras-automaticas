# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle


def obter_janela_principal():
    return (
        aguardar_controle(lambda: auto.PaneControl(Name="mdiRibbonControl"), descricao="ribbon")
        .GetTopLevelControl()
    )


def acessar_solicitacao() -> None:
    main = obter_janela_principal()
    main.SetActive()
    auto.TabItemControl(searchFromControl=main, Name="Compras").Click()
    time.sleep(1)
    auto.ButtonControl(searchFromControl=main, Name="Solicitação de Compra").Click()
    time.sleep(2)
