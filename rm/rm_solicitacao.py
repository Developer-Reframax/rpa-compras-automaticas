# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle
from rpa_rm_faturamento.utils.timing import t
from rpa_rm_faturamento.utils.exceptions import MovimentoEmFaturamentoError


FILTRO_SOLICITACAO_WINDOW_TITLE = "Filtros - Solicitação de Compras (Gestão Compras)"


def tratar_solicitacao(filial: str, tipo_movimento_origem: str, solicitacao_window_title: str) -> None:
    print("📄 Solicitação de Compras...")

    janela = aguardar_controle(
        lambda: auto.WindowControl(Name=solicitacao_window_title),
        descricao="janela solicitacao",
    )

    # -------------------------------------------------
    # 1️⃣ FILIAL
    # -------------------------------------------------
    campo_filial = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela, Name="lkpCODFILIALCode"),
        descricao="filial",
    )

    campo_filial.SetFocus()
    t(0.2)

    campo_filial.SendKeys("{Ctrl}a{Del}")
    campo_filial.SendKeys(filial)
    t(0.5)

    # -------------------------------------------------
    # 2️⃣ TIPO MOVIMENTO (FIX DIGITAÇÃO INVERTIDA 🔥)
    # -------------------------------------------------
    campo_tipo_mov = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela, Name="cTipoMovCode"),
        descricao="campo tipo movimento",
    )

    # 🔥 1. garante foco REAL
    campo_tipo_mov.Click()
    t(0.3)

    # 🔥 2. garante seleção TOTAL (duas vezes por segurança)
    campo_tipo_mov.SendKeys("{Ctrl}a")
    t(0.2)
    campo_tipo_mov.SendKeys("{Ctrl}a")
    t(0.2)

    # 🔥 3. apaga
    campo_tipo_mov.SendKeys("{Del}")
    t(0.3)

    # 🔥 4. FORÇA cursor no início
    campo_tipo_mov.SendKeys("{Home}")
    t(0.2)

    # 🔥 5. digitação CONTROLADA (char a char evita bug da AVD)
    for c in tipo_movimento_origem:  # "1.1.04"
        campo_tipo_mov.SendKeys(c)
        time.sleep(0.05)  # delay fixo de digitação — não escalonado

    t(0.3)

    # 🔥 6. TAB para validar
    campo_tipo_mov.SendKeys("{Tab}")
    t(1.5)

    print(f"✅ Tipo de movimento preenchido corretamente: {tipo_movimento_origem}")

    # aguarda botão estar habilitado
    for _ in range(10):
        botao_ok = auto.ButtonControl(searchFromControl=janela, Name="btnOk")
        if botao_ok.Exists(0.5):
            try:
                if botao_ok.IsEnabled:
                    break
            except Exception:
                pass
    t(0.3)

    botao_ok.Click()
    t(2.0)


def aplicar_filtro_pendentes() -> None:
    janela = aguardar_controle(
        lambda: auto.WindowControl(Name=FILTRO_SOLICITACAO_WINDOW_TITLE),
        descricao="janela filtros",
    )

    grupo = aguardar_controle(
        lambda: auto.GroupControl(searchFromControl=janela, Name="Filtros globais"),
        descricao="grupo filtros",
    )

    auto.TextControl(searchFromControl=grupo, Name="09 - Pendentes/Parc.Recebido").DoubleClick()
    t(2.0)


def _ler_valor_scrollbar(scroll_bar) -> str | None:
    """Lê o LegacyValue da ScrollBar vertical. Retorna None em caso de falha."""
    try:
        return scroll_bar.GetValuePattern().Value
    except Exception:
        return None


def _rolar_linhas_baixo(tabela, n: int = 4) -> None:
    """Rola n linhas para baixo via scrollbar vertical (move viewport, linha sobe na tela)."""
    try:
        sb = auto.ScrollBarControl(searchFromControl=tabela, Name="Vertical")
        if sb.Exists(0, 0):
            btn = auto.ButtonControl(searchFromControl=sb, Name="Uma linha para baixo")
            if btn.Exists(0, 0):
                for _ in range(n):
                    btn.Click()
                    t(0.06)
                t(0.3)
                return
    except Exception:
        pass
    tabela.SetFocus()
    t(0.1)
    for _ in range(n):
        tabela.SendKeys("{Down}")
    t(0.3)


def _checkbox_esta_marcado(chk) -> bool:
    """Retorna True se o checkbox está em estado selecionado."""
    try:
        val = (chk.GetValuePattern().Value or "").strip().lower()
        return val not in ("não selecionado", "nao selecionado", "")
    except Exception:
        return False


def _esta_na_borda_inferior(chk, tabela, margem_px: int = 80) -> bool:
    """Retorna True se o checkbox está nos últimos margem_px pixels do viewport da tabela."""
    try:
        rect_chk = chk.BoundingRectangle
        rect_tab = tabela.BoundingRectangle
        return rect_chk.bottom > rect_tab.bottom - margem_px
    except Exception:
        return False


def _relocalizar_chk(painel, mov: str):
    """Re-escaneia o painel e retorna (linha, chk) para o movimento. (None, None) se não visível."""
    try:
        for linha in painel.GetChildren():
            for cel in linha.GetChildren():
                if cel.Name.startswith("Nº do Movimento"):
                    num = (cel.GetValuePattern().Value or "").lstrip("0")
                    if num == mov:
                        for chk in linha.GetChildren():
                            if chk.Name.startswith("[x]"):
                                return linha, chk
                    break
    except Exception:
        pass
    return None, None


def _clicar_checkbox_com_verificacao(
    painel, tabela, mov: str, linha, chk, max_tentativas: int = 3
) -> bool:
    """
    Marca o checkbox verificando o estado após cada tentativa.

    Se o item estiver na borda inferior do viewport (onde cliques em grids
    Windows Forms são propensos a falhar silenciosamente), rola o grid para
    centralizá-lo e re-localiza o controle antes de tentar novamente.
    """
    for tentativa in range(max_tentativas):
        if _checkbox_esta_marcado(chk):
            return True

        # Na borda inferior ou após falha: rola para tirar da borda e re-localiza
        if tentativa >= 1 or _esta_na_borda_inferior(chk, tabela):
            _rolar_linhas_baixo(tabela, n=4)
            nova_linha, novo_chk = _relocalizar_chk(painel, mov)
            if nova_linha and novo_chk:
                linha, chk = nova_linha, novo_chk
            elif tentativa >= 1:
                # Movimento saiu da view após scroll — não tenta mais
                break

        try:
            linha.Click()  # Ativa a linha na grid antes de clicar no checkbox
            t(0.2)
        except Exception:
            pass

        try:
            chk.Click()
        except Exception:
            pass

        t(0.5 + tentativa * 0.2)

    return _checkbox_esta_marcado(chk)


def _rolar_pagina_abaixo(tabela) -> bool:
    """
    Rola o grid MainView uma página para baixo via ScrollBar vertical real.
    Usa o botão 'Página abaixo' do ScrollBarControl filho do TableControl.
    Retorna True se a posição mudou (ainda há linhas abaixo),
    False se o scrollbar não se moveu (chegou ao fim).
    Faz fallback para {Page_Down} se o ScrollBar não estiver acessível.
    """
    try:
        scroll_bar = auto.ScrollBarControl(searchFromControl=tabela, Name="Vertical")
        if scroll_bar.Exists(0, 0):
            valor_antes = _ler_valor_scrollbar(scroll_bar)

            btn_pagina = auto.ButtonControl(searchFromControl=scroll_bar, Name="Página abaixo")
            if btn_pagina.Exists(0, 0):
                btn_pagina.Click()
                t(0.6)
            else:
                # Fallback: clica várias vezes em "Uma linha para baixo"
                btn_linha = auto.ButtonControl(searchFromControl=scroll_bar, Name="Uma linha para baixo")
                if btn_linha.Exists(0, 0):
                    for _ in range(15):
                        btn_linha.Click()
                        t(0.05)
                    t(0.4)

            valor_depois = _ler_valor_scrollbar(scroll_bar)

            # Se conseguiu ler ambos os valores, compara para detectar fim
            if valor_antes is not None and valor_depois is not None:
                return valor_antes != valor_depois

            return True  # Não conseguiu comparar — assume que scrollou
    except Exception:
        pass

    # Fallback final: envia Page_Down via teclado
    tabela.SetFocus()
    t(0.2)
    tabela.SendKeys("{Page_Down}")
    t(0.6)
    return True


def marcar_movimentos(main, movimentos) -> int:
    tabela = aguardar_controle(
        lambda: auto.TableControl(searchFromControl=main, Name="MainView"),
        descricao="MainView",
    )

    painel = next(
        c for c in tabela.GetChildren() if c.ControlTypeName == "CustomControl" and c.Name == "Painel de dados"
    )

    lista = set(str(m).lstrip("0") for m in movimentos)
    ja_marcados: set = set()

    # Garante foco no grid e volta ao início antes de iterar.
    # O grid do RM usa virtualização — apenas linhas visíveis no viewport existem
    # na árvore UIA. A rolagem via ScrollBar real é mais confiável que {Page_Down}
    # porque aciona o mecanismo nativo de scroll do Windows Forms.
    tabela.SetFocus()
    t(0.3)
    tabela.SendKeys("{Ctrl}{Home}")
    t(0.5)

    ultima_linha_vista = None

    while True:
        filhos = painel.GetChildren()

        for linha in filhos:
            for cel in linha.GetChildren():
                if cel.Name.startswith("Nº do Movimento"):
                    mov = (cel.GetValuePattern().Value or "").lstrip("0")
                    if mov in lista and mov not in ja_marcados:
                        for chk in linha.GetChildren():
                            if chk.Name.startswith("[x]"):
                                marcado = _clicar_checkbox_com_verificacao(
                                    painel, tabela, mov, linha, chk
                                )
                                if marcado:
                                    ja_marcados.add(mov)
                                    print(f"  ✅ Movimento {mov} marcado.")
                                else:
                                    print(f"  ⚠️ Falha ao marcar checkbox do movimento {mov} após tentativas.")
                    break  # cada linha tem apenas uma célula de Nº do Movimento

        # Todos encontrados — para de rolar
        if ja_marcados >= lista:
            break

        # Identifica o último movimento visível para detectar fim do grid (fallback)
        ultima_atual = None
        for linha in reversed(filhos):
            for cel in linha.GetChildren():
                if cel.Name.startswith("Nº do Movimento"):
                    ultima_atual = (cel.GetValuePattern().Value or "").lstrip("0")
                    break
            if ultima_atual:
                break

        if ultima_atual is not None and ultima_atual == ultima_linha_vista:
            # Última linha visível não mudou → chegou ao fim do grid
            print("📋 Fim do grid atingido (última linha repetida).")
            break
        ultima_linha_vista = ultima_atual

        # Rola via ScrollBar real; se retornar False, chegou ao fim
        if not _rolar_pagina_abaixo(tabela):
            print("📋 Fim do grid atingido (ScrollBar no máximo).")
            break

    nao_encontrados = lista - ja_marcados
    if nao_encontrados:
        print(f"⚠️  Movimentos NÃO encontrados na tabela: {nao_encontrados}")

    return len(ja_marcados)


def clicar_receber(main) -> None:
    auto.ButtonControl(searchFromControl=main, Name="Receber").Click()
    t(2.0)


def _capturar_mensagem_modal_rm(janela) -> str:
    """Lê o texto (AutomationId='65535') do modal de erro padrão do RM."""
    try:
        texto = auto.TextControl(searchFromControl=janela, AutomationId="65535")
        if texto.Exists(0, 0):
            return (texto.Name or "").strip()
    except Exception:
        pass
    return ""


def _fechar_dialogo_erro_e_wizard(janela, btn_ok) -> None:
    """
    Fecha o dialog de erro padrão do RM (clica OK) e, em seguida, cancela a
    janela 'Faturar / Receber' (AutomationId='MovFaturamentoProcForm') caso
    tenha ficado aberta — se permanecer, bloqueia a próxima execução.
    """
    # 1) Fecha o dialog de erro (OK)
    try:
        btn_ok.Click()
        t(0.5)
    except Exception:
        pass

    # 2) Cancela a janela "Faturar / Receber" para liberar o RM
    try:
        janela_wizard = auto.WindowControl(AutomationId="MovFaturamentoProcForm")
        if janela_wizard.Exists(2, 0):
            btn_cancel = auto.ButtonControl(
                searchFromControl=janela_wizard, AutomationId="btnCancel"
            )
            if btn_cancel.Exists(0, 0):
                btn_cancel.Click()
                t(1.0)
                print("✅ Janela 'Faturar / Receber' cancelada")
    except Exception:
        pass


def verificar_janela_erro_rm(timeout: float = 5.0) -> str | None:
    """
    Monitora por até `timeout` segundos se o RM exibiu uma janela de erro.

    Usada após operações que podem fazer o RM exibir um dialog de erro padrão
    (ClassName='#32770', Name='RM'), como após selecionar o tipo de movimento
    destino e clicar em Avançar no wizard.

    A janela contém: botão OK (AutomationId='2') e um TextControl
    (AutomationId='65535') com a mensagem de erro.

    Retorna o texto da mensagem se a janela aparecer; None caso contrário
    (fluxo normal prossegue).
    """
    inicio = time.time()

    while time.time() - inicio < timeout:
        try:
            janela = auto.WindowControl(Name="RM", ClassName="#32770")
            if not janela.Exists(0, 0):
                time.sleep(0.4)
                continue

            # Confirma que é o dialog de erro esperado (botão OK com AutomationId=2)
            btn_ok = auto.ButtonControl(searchFromControl=janela, AutomationId="2")
            if not btn_ok.Exists(0, 0):
                time.sleep(0.4)
                continue

            mensagem = _capturar_mensagem_modal_rm(janela) or "Erro RM após Receber (mensagem não capturada)"
            print(f"⚠️ Janela de erro RM detectada: {mensagem[:120]}")

            _fechar_dialogo_erro_e_wizard(janela, btn_ok)
            return mensagem

        except Exception:
            pass

        time.sleep(0.4)

    return None  # Sem erro — wizard deve ter aberto normalmente


def detectar_erro_apos_receber(timeout: float = 12.0) -> None:
    """
    Logo após clicar em Receber, o RM segue por um de dois caminhos:
      - abre o wizard de recebimento (PaneControl Name='pnlWizard'); ou
      - exibe o modal de erro padrão (Name='RM', ClassName='#32770'), por
        exemplo: "Movimento não pode ser alterado, movimento está em
        faturamento!" — quando um dos movimentos está bloqueado por outra
        sessão (humano faturando o mesmo movimento).

    Faz polling simultâneo pelos dois e:
      - se o wizard abrir  → retorna (fluxo normal segue para tratar_wizard);
      - se o modal aparecer → captura a mensagem, fecha o dialog (OK) e cancela
        a janela 'Faturar / Receber', e levanta MovimentoEmFaturamentoError;
      - se nenhum aparecer dentro de `timeout` → retorna, deixando o
        tratar_wizard subsequente lidar com a ausência (e eventual timeout).

    Como retorna imediatamente ao detectar o wizard, o caminho feliz não sofre
    atraso — o `timeout` só é atingido no caso raro em que nada aparece.
    """
    inicio = time.time()

    while time.time() - inicio < timeout:
        # 1) Wizard abriu? Caminho normal — sai na hora.
        try:
            if auto.PaneControl(Name="pnlWizard").Exists(0, 0):
                return
        except Exception:
            pass

        # 2) Modal de erro padrão do RM?
        try:
            janela = auto.WindowControl(Name="RM", ClassName="#32770")
            if janela.Exists(0, 0):
                btn_ok = auto.ButtonControl(searchFromControl=janela, AutomationId="2")
                if btn_ok.Exists(0, 0):
                    mensagem = _capturar_mensagem_modal_rm(janela) or (
                        "Erro RM após Receber (mensagem não capturada)"
                    )
                    print(f"⚠️ Erro RM após Receber detectado: {mensagem[:120]}")
                    _fechar_dialogo_erro_e_wizard(janela, btn_ok)
                    raise MovimentoEmFaturamentoError(mensagem)
        except MovimentoEmFaturamentoError:
            raise
        except Exception:
            pass

        time.sleep(0.3)

    return  # Nem wizard nem erro detectados — segue o fluxo (tratar_wizard decide)
