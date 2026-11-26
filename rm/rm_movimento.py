# -*- coding: utf-8 -*-
import time
from datetime import datetime, timedelta
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle
from rpa_rm_faturamento.utils.timing import t
from rpa_rm_faturamento.utils.ui_helpers import (
    acessar_item_lista,
    resetar_cache_navbar,
    sincronizar_listas_navbar,
)
from rpa_rm_faturamento.rm.rm_itens import tratar_itens_movimento
from rpa_rm_faturamento.rm.rm_confirmacao import confirmar_movimento


def aguardar_movimento_final(timeout: int = 60):
    """
    Aguarda a janela do movimento 1.1.15 abrir como popup standalone e retorna a janela.

    O formulário abre com AutomationId="MovMovimentoForm" (sem sufixo "View") —
    diferente da janela de Solicitação de Compras que fica embutida no MDI com
    AutomationId="MovMovimentoFormView". Por isso NÃO usamos "Código Linha" como
    âncora (esse controle não existe neste formulário).

    Âncora confiável: PaneControl name="NavBar" dentro de panelLeft.
    Só aparece quando o formulário está completamente renderizado.
    """
    # Passo 1: aguarda o popup do movimento aparecer na desktop
    janela = aguardar_controle(
        lambda: auto.WindowControl(AutomationId="MovMovimentoForm"),
        timeout=timeout,
        descricao="popup Movimento 1.1.15 (MovMovimentoForm)",
    )

    # Passo 2: aguarda NavBar — confirma que o form está carregado e pronto
    aguardar_controle(
        lambda: auto.PaneControl(searchFromControl=janela, Name="NavBar"),
        timeout=30,
        descricao="NavBar do Movimento 1.1.15",
    )

    print(f"🏁 Movimento final aberto: {janela.Name}")
    return janela


def preencher_fornecedor(janela, cnpj: str) -> None:
    print("🏭 Preenchendo fornecedor (CNPJ)...")

    campo = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela, Name="lkpCODCFOCode"),
        timeout=60,
        descricao="campo fornecedor",
    )

    # Usa ValuePattern (modelo antigo que funcionava)
    vp = campo.GetValuePattern()
    vp.SetValue("")
    t(0.1)

    vp.SetValue(cnpj)
    t(0.2)

    # Sai do campo: Tab dispara a primeira validação do campo
    campo.SendKeys("\t")
    t(0.5)

    # Gatilho do lookup: espaço + backspace + tab.
    # Força o RM a disparar o lookup do CNPJ mesmo que o valor já estivesse preenchido.
    # Os sleeps foram reduzidos — o input via SendKeys é síncrono; o tempo relevante
    # está na espera final do lookup (t(1.2)), não nos comandos intermediários.
    campo.SetFocus()
    t(0.1)

    campo.SendKeys(" ")
    t(0.1)
    campo.SendKeys("\b")
    t(0.1)

    campo.SendKeys("\t")
    t(1.2)

    print("✅ Fornecedor preenchido e lookup disparado.")


def preencher_comprador(janela, codigo_comprador: str) -> str:
    """Preenche o código do comprador e retorna o nome resolvido pelo lookup."""
    codigo_comprador = str(codigo_comprador).zfill(5)
    print(f"👤 Preenchendo Comprador: {codigo_comprador}")

    campo = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela, Name="lkpCODVEN1Code"),
        timeout=60,
        descricao="campo comprador",
    )

    campo.SetFocus()
    t(0.2)

    try:
        campo.SendKeys("{Ctrl}a{Del}")
    except Exception:
        pass

    try:
        campo.GetValuePattern().SetValue(codigo_comprador)
    except Exception:
        campo.SendKeys(codigo_comprador)

    campo.SendKeys("{Tab}")
    t(1.5)

    # Lê o nome do comprador resolvido pelo lookup (campo descrição ao lado do código)
    nome_comprador = ""
    try:
        campo_nome = auto.EditControl(
            searchFromControl=janela, Name="lkpCODVEN1lookupEditinnerEdit"
        )
        if campo_nome.Exists(0, 0):
            nome_comprador = (campo_nome.GetValuePattern().Value or "").strip()
    except Exception:
        pass

    if nome_comprador:
        print(f"✅ Comprador preenchido: {nome_comprador}")
    else:
        print("✅ Comprador preenchido (nome nao disponivel).")

    return nome_comprador


def preencher_condicao_pagamento(janela, codigo_cpg: str) -> None:
    print("💰 Preenchendo Condicao de Pagamento...")

    campo = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela, Name="lkpCODCPGCode"),
        timeout=60,
        descricao="condicao de pagamento",
    )

    campo.SetFocus()
    t(0.2)

    try:
        campo.SendKeys("{Ctrl}a{Del}")
    except Exception:
        pass

    try:
        campo.GetValuePattern().SetValue(codigo_cpg)
    except Exception:
        campo.SendKeys(codigo_cpg)

    campo.SendKeys("{Tab}")
    t(1.5)

    print("✅ Condicao de pagamento preenchida.")


def selecionar_tipo_frete(janela, tipo_frete: str = "CIF") -> None:
    print(f"🚚 Selecionando tipo de frete: {tipo_frete}")

    grupo = aguardar_controle(
        lambda: auto.GroupControl(searchFromControl=janela, Name="rdgFRETECIFOUFOB"),
        timeout=60,
        descricao="grupo tipo frete",
    )

    opcao = aguardar_controle(
        lambda: auto.RadioButtonControl(searchFromControl=grupo, Name=tipo_frete),
        timeout=10,
        descricao=f"opcao frete {tipo_frete}",
    )

    opcao.Click()
    t(0.5)

    print("✅ Tipo de frete selecionado.")


def _localizar_campo_justificativa(janela):
    """
    Localiza o EditControl da Justificativa de Compra dentro do grupo Campos Complementares.
    O campo nao tem Name nem AutomationId estatico; e identificado como o primeiro
    EditControl imediatamente apos o TextControl 'Justificativa de Compra:'.
    """
    grupo = aguardar_controle(
        lambda: auto.GroupControl(searchFromControl=janela, Name="Campos Complementares"),
        timeout=20,
        descricao="grupo Campos Complementares",
    )

    achou_label = False
    for ctrl, _ in auto.WalkControl(grupo, maxDepth=5):
        if ctrl.ControlTypeName == "TextControl" and "Justificativa de Compra" in (ctrl.Name or ""):
            achou_label = True
            continue
        if achou_label and ctrl.ControlTypeName == "EditControl":
            return ctrl

    return None


def preencher_justificativa_compra(janela, mensagem: str) -> None:
    print("📋 Preenchendo Justificativa de Compra...")

    campo = _localizar_campo_justificativa(janela)
    if campo is None:
        raise RuntimeError("❌ Campo Justificativa de Compra nao encontrado")

    campo.SetFocus()
    t(0.2)

    try:
        campo.GetValuePattern().SetValue(mensagem)
    except Exception:
        campo.SendKeys("{Ctrl}a{Del}")
        t(0.1)
        campo.SendKeys(mensagem)

    campo.SendKeys("\t")
    t(0.5)

    print("✅ Justificativa de Compra preenchida.")


def adicionar_historico(janela, mensagem: str) -> None:
    print("📝 Adicionando historico no movimento...")

    campo = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela, Name="tbxHISTORICOLONGO"),
        timeout=60,
        descricao="campo historico",
    )

    campo.SetFocus()
    t(0.2)

    try:
        texto_atual = campo.GetValuePattern().Value or ""
    except Exception:
        texto_atual = ""

    novo_texto = texto_atual.rstrip() + "\n" + mensagem

    try:
        campo.GetValuePattern().SetValue(novo_texto)
    except Exception:
        campo.SendKeys("{End}{Enter}")
        campo.SendKeys(mensagem)

    t(0.5)
    print("✅ Historico atualizado.")


def preencher_entrega_fornecedor(janela, dias_entrega: int) -> None:
    print("📦 Preenchendo data de Entrega do Fornecedor...")

    # 1) Calcula data futura
    data_entrega = datetime.now() + timedelta(days=dias_entrega)
    data_str = data_entrega.strftime("%d/%m/%Y")
    print(f"🗓️ Data calculada: {data_str}")

    # 2) Localiza grupo Cabecalho
    cabecalho = aguardar_controle(
        lambda: auto.GroupControl(searchFromControl=janela, Name="Cabeçalho"),
        timeout=20,
        descricao="grupo Cabecalho",
    )

    # 3) Localiza grupo de datas
    grp_datas = aguardar_controle(
        lambda: auto.GroupControl(searchFromControl=cabecalho, Name="grpDatas"),
        timeout=20,
        descricao="grupo Datas",
    )

    # 4) Localiza o container do date picker (QUALQUER TIPO)
    dtp_container = aguardar_controle(
        lambda: next(
            c for c, _ in auto.WalkControl(grp_datas, maxDepth=5) if c.Name == "dtpDATAEXTRA2"
        ),
        timeout=20,
        descricao="container dtpDATAEXTRA2",
    )

    # 5) Localiza o Edit interno (Competencia)
    edit_data = aguardar_controle(
        lambda: next(c for c, _ in auto.WalkControl(dtp_container, maxDepth=5) if c.ControlTypeName == "EditControl"),
        timeout=10,
        descricao="edit data entrega",
    )

    # 6) Preenche a data
    edit_data.SetFocus()
    t(0.2)

    edit_data.SendKeys("{Ctrl}a{Del}")
    t(0.2)

    edit_data.SendKeys(data_str)
    t(0.2)

    edit_data.SendKeys("\t")
    t(1.0)

    print("✅ Data de Entrega do Fornecedor preenchida.")


def tratar_movimento_final(
    janela,
    cnpj_fornecedor: str,
    cod_comprador: str,
    cod_pagamento: str,
    tipo_frete: str,
    historico: str,
    dias_entrega: int,
    itens,
    logger=None,
):
    print("📑 Tratando movimento final...")

    # Garante que temos a janela real (não None) — evita busca global na UIA
    if janela is None:
        raise RuntimeError(
            "janela do movimento é None. Certifique-se de capturar o retorno de aguardar_movimento_final()."
        )

    # Reseta cache do NavBar: garante estado limpo para esta janela,
    # evitando que entradas de formulários anteriores causem skip indevido.
    resetar_cache_navbar()

    navbar = aguardar_controle(
        lambda: auto.PaneControl(searchFromControl=janela, Name="NavBar"),
        timeout=30,
        descricao="NavBar",
    )

    # Sincroniza listas ja expandidas ao abrir a tela
    sincronizar_listas_navbar(
        navbar,
        [
            ("Identificação", "Cabeçalho"),
            ("Identificação", "Tabelas"),
            ("Integrações", "Financeira"),
            ("Transporte", "Identificação"),
            ("Informações Adicionais", "Campos Complementares"),
            ("Itens", "Itens"),
        ],
    )

    # A partir daqui, o robo NAO deve mais fechar/abrir lista a toa
    acessar_item_lista(navbar, "Identificação", "Cabeçalho")
    preencher_fornecedor(janela, cnpj_fornecedor)
    preencher_entrega_fornecedor(janela, dias_entrega=dias_entrega)

    acessar_item_lista(navbar, "Identificação", "Tabelas")
    nome_comprador = preencher_comprador(janela, cod_comprador)
    if nome_comprador:
        historico = f"{historico} - Comprador: {nome_comprador}"

    acessar_item_lista(navbar, "Integrações", "Financeira")
    preencher_condicao_pagamento(janela, cod_pagamento)

    acessar_item_lista(navbar, "Transporte", "Identificação")
    selecionar_tipo_frete(janela, tipo_frete)

    acessar_item_lista(navbar, "Informações Adicionais", "Campos Complementares")
    preencher_justificativa_compra(janela, historico)

    acessar_item_lista(navbar, "Itens", "Itens")

    # Garante foco real no grid de itens
    tabela_itens = aguardar_controle(
        lambda: auto.TableControl(searchFromControl=janela, Name="MainView"),
        timeout=20,
        descricao="grid de Itens",
    )

    try:
        tabela_itens.Click()
    except Exception:
        pass

    t(0.6)

    tratar_itens_movimento(janela_movimento=janela, itens=itens, logger=logger)

    mensagem_rm = confirmar_movimento(janela)

    return mensagem_rm


def fechar_abas_tabcontrol():
    """Fecha todas as abas de movimento abertas no TabControl da tela inicial.

    Deve ser chamado antes de iniciar o faturamento de cada lote para garantir
    que nao ha abas residuais de ciclos anteriores.
    """
    print("🗂️ Verificando abas abertas no TabControl...")

    main_form = aguardar_controle(
        lambda: auto.WindowControl(Name="MainForm"),
        timeout=30,
        descricao="MainForm",
    )

    nomes_alvo = ("Ordem de Compra", "Solicitação de Compras")
    total_fechadas = 0
    limite_tentativas = 30

    for _ in range(limite_tentativas):
        abas = []
        vistos = set()

        for ctrl, _ in auto.WalkControl(main_form, maxDepth=6):
            try:
                if ctrl.ControlTypeName != "TabItemControl":
                    continue
                if not ctrl.Exists(0, 0):
                    continue

                nome_aba = (ctrl.Name or "").strip()
                if not nome_aba:
                    continue
                if not any(alvo in nome_aba for alvo in nomes_alvo):
                    continue

                botao_fechar = auto.ButtonControl(searchFromControl=ctrl, Name="Fechar")
                if not botao_fechar.Exists(0, 0):
                    continue

                try:
                    runtime_id = ctrl.GetRuntimeId()
                    assinatura = ("runtime_id", tuple(runtime_id)) if runtime_id else ("nome", nome_aba)
                except Exception:
                    assinatura = ("nome", nome_aba)

                if assinatura in vistos:
                    continue

                vistos.add(assinatura)
                abas.append((ctrl, nome_aba))
            except Exception:
                continue

        if not abas:
            break

        aba, nome_aba = abas[0]

        try:
            aba.Click()
            time.sleep(0.2)
        except Exception:
            pass

        botao_fechar = auto.ButtonControl(searchFromControl=aba, Name="Fechar")
        if not botao_fechar.Exists(0, 0):
            time.sleep(0.4)
            continue

        botao_fechar.Click()
        total_fechadas += 1
        print(f"✅ Aba fechada: {nome_aba}")
        time.sleep(0.8)

    if total_fechadas > 0:
        print(f"✅ {total_fechadas} aba(s) fechada(s) antes do faturamento.")
    else:
        print("ℹ️ Nenhuma aba de movimento aberta encontrada.")
