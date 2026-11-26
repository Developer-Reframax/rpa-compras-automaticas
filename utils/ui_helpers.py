# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from .wait import aguardar_controle
from .timing import t


LISTAS_NAVBAR_ABERTAS = set()


def resetar_cache_navbar():
    print("🧹 Resetando cache de estado do NavBar (nova janela)")
    LISTAS_NAVBAR_ABERTAS.clear()


def click_por_varredura_horizontal(ctrl, validar_click=None, passos=10):
    """
    Tenta clicar dentro do BoundingRectangle do controle,
    varrendo horizontalmente até encontrar a área clicável.

    validar_click: função opcional que retorna True quando o clique funcionou
    """
    rect = ctrl.BoundingRectangle

    y = rect.top + (rect.bottom - rect.top) // 2

    largura = rect.right - rect.left
    inicio = rect.left + int(largura * 0.15)
    fim = rect.left + int(largura * 0.85)

    passo = max(5, (fim - inicio) // passos)

    print(f"🧪 Varredura de clique: x de {inicio} até {fim} (passo {passo})")

    for x in range(inicio, fim, passo):
        auto.Click(x, y)
        t(0.4)

        if validar_click:
            try:
                if validar_click():
                    print(f"✅ Clique validado em x={x}")
                    return True
            except Exception:
                pass

    raise RuntimeError("❌ Não foi possível encontrar área clicável no item")


def sincronizar_listas_navbar(navbar, pares_lista_item):
    """
    Varre previamente as listas do NavBar e registra no cache (LISTAS_NAVBAR_ABERTAS)
    aquelas que já estão expandidas NO MOMENTO em que a tela abriu.

    Estratégia de detecção em dois passos para balancear velocidade e robustez AVD:
      1. Exists(0, 0) — verifica imediatamente sem espera. Listas já expandidas e
         renderizadas são detectadas na hora; listas colapsadas retornam False
         instantaneamente (seus filhos nunca aparecem na UIA independente do tempo).
      2. Exists(1, 0) — fallback de 1s para tolerância com renderização lenta em AVD.
         Reduz de 2s → 1s, que ainda cobre a janela de inicialização observada.

    O buffer inicial foi reduzido de 1.0s → 0.3s: o NavBar já foi confirmado presente
    por aguardar_controle() antes desta chamada, portanto a maior parte da espera
    anterior era desnecessária.
    """
    # Buffer mínimo: NavBar já confirmado presente, garante filhos carregados
    print("🧭 Sincronizando estado inicial das listas do NavBar...")
    t(0.3)

    for nome_lista, nome_item in pares_lista_item:
        try:
            lista = auto.ListControl(searchFromControl=navbar, Name=nome_lista)
            if not lista.Exists(0, 0):
                continue

            item = auto.ListItemControl(searchFromControl=lista, Name=nome_item)

            # Caminho rápido: item já visível na UIA (lista expandida e renderizada)
            if item.Exists(0, 0):
                LISTAS_NAVBAR_ABERTAS.add(nome_lista)
                print(f"✅ Lista '{nome_lista}' expandida (detecção imediata).")
                continue

            # Fallback AVD: tolera renderização lenta de até 1s
            # Listas colapsadas retornam False imediatamente aqui também,
            # poupando os 2s que eram desperdiçados antes.
            if item.Exists(1, 0):
                LISTAS_NAVBAR_ABERTAS.add(nome_lista)
                print(f"✅ Lista '{nome_lista}' expandida (detecção com tolerância AVD).")
        except Exception:
            continue

    print(f"🧾 Listas expandidas: {sorted(list(LISTAS_NAVBAR_ABERTAS))}")


def garantir_navbar_expandido(janela):
    print("🧭 Verificando navbar do movimento...")

    try:
        navbar = aguardar_controle(
            lambda: auto.PaneControl(searchFromControl=janela, Name="NavBar"),
            timeout=10,
            descricao="navbar",
        )
    except TimeoutError:
        print("ℹ️ Navbar não encontrada (seguindo fluxo).")
        return

    botoes = [c for c, _ in auto.WalkControl(navbar, maxDepth=3) if c.ControlTypeName == "ButtonControl"]

    for btn in botoes:
        try:
            nome_btn = (btn.Name or "").lower()

            # Tenta por nome semântico primeiro (mais confiável que tamanho em pixels)
            if nome_btn in ("recolher", "expandir", "collapse", "expand", "<<", ">>"):
                btn.Click()
                t(0.5)
                print(f"🧩 Navbar expandido via nome: {btn.Name}")
                return

            # FIX AVD (Problema 13): threshold de largura aumentado de 40 para 60px
            # para tolerar DPI scaling de 125-150% da AVD.
            # Critério adicional: ausência de texto no botão (distingue do toolbar).
            rect = btn.BoundingRectangle
            largura = rect.right - rect.left
            altura = rect.bottom - rect.top
            if largura < 60 and altura < 60 and not btn.Name:
                btn.Click()
                t(0.5)
                print("🧩 Navbar expandido via heurística de tamanho (DPI-tolerante).")
                return
        except Exception:
            continue

    print("ℹ️ Navbar já estava expandido.")


def garantir_lista_expandida(navbar, nome_lista, nome_item_verificacao):
    """
    Garante que a lista esteja expandida seguindo regra determinística:
    - Se a lista já está no cache -> NÃO toca no toggle
    - Se o item-alvo Exists(2,0) -> NÃO toca no toggle e adiciona no cache
    - Só expande se o item-alvo NÃO existir
    """
    print(f"🧭 Verificando lista '{nome_lista}'...")

    # 1) Já validada anteriormente
    if nome_lista in LISTAS_NAVBAR_ABERTAS:
        print(f"🔒 Lista '{nome_lista}' já marcada como expandida. Não tocando no toggle.")
        return aguardar_controle(
            lambda: auto.ListControl(searchFromControl=navbar, Name=nome_lista),
            descricao=f"lista {nome_lista}",
        )

    # 2) Localiza a lista
    lista = aguardar_controle(
        lambda: auto.ListControl(searchFromControl=navbar, Name=nome_lista),
        timeout=20,
        descricao=f"lista {nome_lista}",
    )

    # 3) FIX: usa Exists(2, 0) — tolera renderização lenta do AVD
    item = auto.ListItemControl(searchFromControl=lista, Name=nome_item_verificacao)
    if item.Exists(2, 0):
        print(f"ℹ️ Lista '{nome_lista}' já está expandida (item '{nome_item_verificacao}' encontrado).")
        LISTAS_NAVBAR_ABERTAS.add(nome_lista)
        return lista

    # 4) Se não existe -> expandir UMA vez
    print(f"🧩 Expandindo lista '{nome_lista}'...")

    botao_expandir = None
    for c, _ in auto.WalkControl(lista, maxDepth=2):
        if c.ControlTypeName == "ButtonControl" and c.Name == "Expand":
            botao_expandir = c
            break

    if not botao_expandir:
        raise RuntimeError(f"❌ Botão Expand não encontrado na lista '{nome_lista}'")

    botao_expandir.Click()
    t(0.8)

    # Confirma que o item apareceu após expandir
    aguardar_controle(
        lambda: auto.ListItemControl(searchFromControl=lista, Name=nome_item_verificacao),
        timeout=10,
        descricao=f"item {nome_item_verificacao}",
    )

    LISTAS_NAVBAR_ABERTAS.add(nome_lista)
    print(f"✅ Lista '{nome_lista}' expandida e validada.")

    return lista


def acessar_item_lista(navbar, nome_lista, nome_item):
    lista = garantir_lista_expandida(
        navbar=navbar,
        nome_lista=nome_lista,
        nome_item_verificacao=nome_item,
    )

    print(f"📂 Acessando '{nome_lista} > {nome_item}'")

    # Primeiro tenta TextControl
    texto = auto.TextControl(searchFromControl=lista, Name=nome_item)
    if texto.Exists(0, 0):
        ctrl_click = texto
    else:
        ctrl_click = auto.ListItemControl(searchFromControl=lista, Name=nome_item)

    if not ctrl_click.Exists(0, 0):
        raise RuntimeError(f"❌ Item '{nome_item}' não encontrado")

    # Validação: painel de itens apareceu
    def validacao_itens():
        return auto.TableControl(Name="MainView").Exists(0, 0)

    # Clique por varredura (resolve o Itens)
    click_por_varredura_horizontal(ctrl_click, validar_click=validacao_itens)


def acessar_submenu_movimento(janela, nome_menu):
    print(f"📂 Acessando submenu '{nome_menu}'...")

    item = aguardar_controle(
        lambda: auto.TextControl(searchFromControl=janela, Name=nome_menu),
        timeout=20,
        descricao=f"submenu {nome_menu}",
    )

    item.Click()
    t(1.0)


def localizar_celula_grid_por_nome(linha, nome_coluna):
    """
    Acha a célula da coluna no grid do RM.
    Ex.: nome_coluna="Faturar" encontra "Faturar linha 1"
    """
    alvo = nome_coluna.lower().strip()

    for c, _ in auto.WalkControl(linha, maxDepth=3):
        if c.ControlTypeName not in ("DataItemControl", "CustomControl"):
            continue

        nome = (c.Name or "").lower()
        if nome.startswith(alvo):  # "faturar linha 1"
            return c

    return None


def garantir_coluna_visivel(tabela, linha, nome_coluna, max_paginas=20):
    """
    Tenta encontrar a célula da coluna; se não achar, pagina horizontalmente à direita.
    """
    cel = localizar_celula_grid_por_nome(linha, nome_coluna)
    if cel:
        return cel

    scrollbar_h = None
    for c, _ in auto.WalkControl(tabela, maxDepth=4):
        if c.ControlTypeName == "ScrollBarControl" and (c.Name or "").lower() == "horizontal":
            scrollbar_h = c
            break

    if not scrollbar_h:
        return None

    btn_pagina_direita = None
    for c, _ in auto.WalkControl(scrollbar_h, maxDepth=2):
        if c.ControlTypeName == "ButtonControl" and "pagina a direita" in (c.Name or "").lower():
            btn_pagina_direita = c
            break

    if not btn_pagina_direita:
        return None

    for _ in range(max_paginas):
        btn_pagina_direita.Click()
        t(0.3)  # escalonado: garante re-renderização no AVD

        cel = localizar_celula_grid_por_nome(linha, nome_coluna)
        if cel:
            return cel

    return None


def localizar_scrollbar_horizontal(tabela):
    """
    Localiza a ScrollBar horizontal e seu ThumbControl.
    Retorna (scrollbar, thumb)
    """
    for c, _ in auto.WalkControl(tabela, maxDepth=5):
        if c.ControlTypeName == "ScrollBarControl" and (c.Name or "").lower() == "horizontal":
            for t_ctrl, _ in auto.WalkControl(c, maxDepth=2):
                if t_ctrl.ControlTypeName == "ThumbControl":
                    return c, t_ctrl
    return None, None


def _scroll_via_scroll_pattern(tabela, direcao="direita"):
    """
    Tenta rolar a tabela horizontalmente usando IScrollPattern.
    Mais confiável em sessões RDP/AVD do que DragDrop.
    Retorna True se conseguiu aplicar o scroll.
    """
    try:
        sp = tabela.GetScrollPattern()
        if direcao == "direita":
            sp.SetScrollPercent(100, -1)
        else:
            sp.SetScrollPercent(0, -1)
        t(0.5)
        return True
    except Exception:
        return False


def _scroll_via_pagina_botao(tabela, linha, nome_coluna, direcao="direita", max_paginas=30):
    """
    Rola usando o botão 'Página à Direita' ou 'Página à Esquerda' da scrollbar.
    Fallback quando ScrollPattern não está disponível.
    """
    scrollbar_h = None
    for c, _ in auto.WalkControl(tabela, maxDepth=5):
        if c.ControlTypeName == "ScrollBarControl" and (c.Name or "").lower() == "horizontal":
            scrollbar_h = c
            break

    if not scrollbar_h:
        return None

    if direcao == "direita":
        nome_btn = "pagina a direita"
    else:
        nome_btn = "pagina a esquerda"

    btn = None
    for c, _ in auto.WalkControl(scrollbar_h, maxDepth=2):
        if c.ControlTypeName == "ButtonControl" and nome_btn in (c.Name or "").lower():
            btn = c
            break

    if not btn:
        return None

    for _ in range(max_paginas):
        btn.Click()
        t(0.3)
        cel = localizar_celula_grid_por_nome(linha, nome_coluna)
        if cel:
            return cel

    return None


def arrastar_scroll_ate_coluna(tabela, linha, nome_coluna, direcao="direita", max_passos=15):
    """
    Localiza a coluna rolando horizontalmente a tabela.

    FIX AVD (Problema 6): DragDrop é instável em sessões RDP por causa da
    latência de rede. Estratégia em camadas:
      1. Tenta ScrollPattern (mais confiável, sem coordenadas)
      2. Fallback: botão Página à Direita/Esquerda da scrollbar
      3. Último recurso: DragDrop (comportamento original)
    """
    # Já está visível?
    cel = localizar_celula_grid_por_nome(linha, nome_coluna)
    if cel:
        return cel

    print(f"📜 Rolando para '{nome_coluna}' via ScrollPattern...")

    # 1) ScrollPattern — sem coordenadas, sem DragDrop
    if _scroll_via_scroll_pattern(tabela, direcao):
        cel = localizar_celula_grid_por_nome(linha, nome_coluna)
        if cel:
            print(f"✅ '{nome_coluna}' encontrada via ScrollPattern.")
            return cel

    # 2) Botão de página (fallback intermediário)
    print(f"📜 ScrollPattern insuficiente, tentando botão Página...")
    cel = _scroll_via_pagina_botao(tabela, linha, nome_coluna, direcao, max_paginas=max_passos)
    if cel:
        print(f"✅ '{nome_coluna}' encontrada via botão Página.")
        return cel

    # 3) DragDrop como último recurso (pode falhar em AVD)
    print(f"📜 Tentando DragDrop como último recurso...")
    scrollbar, thumb = localizar_scrollbar_horizontal(tabela)
    if not scrollbar or not thumb:
        print("❌ ScrollBar horizontal ou Thumb não encontrado — não é possível rolar.")
        return None

    sb_rect = scrollbar.BoundingRectangle
    th_rect = thumb.BoundingRectangle

    y = th_rect.top + (th_rect.bottom - th_rect.top) // 2
    x_origem = th_rect.left + (th_rect.right - th_rect.left) // 2

    if direcao == "direita":
        x_destino = sb_rect.right - 5
    else:
        x_destino = sb_rect.left + 5

    # Drag único
    auto.DragDrop(x_origem, y, x_destino, y)
    t(0.6)  # tempo extra para re-renderização no AVD após drag

    cel = localizar_celula_grid_por_nome(linha, nome_coluna)
    if cel:
        return cel

    # Loop de fallback controlado
    for _ in range(max_passos):
        auto.DragDrop(x_origem, y, x_destino, y)
        t(0.5)

        cel = localizar_celula_grid_por_nome(linha, nome_coluna)
        if cel:
            return cel

    return None


def resetar_scroll_horizontal(tabela) -> None:
    """Reseta o scroll horizontal para a posição 0 (esquerda)."""
    try:
        sp = tabela.GetScrollPattern()
        sp.SetScrollPercent(0, -1)
        t(0.4)
    except Exception:
        pass


def localizar_checkbox_linha(linha):
    """
    Localiza o checkbox '[x] linha X' dentro da linha do grid.
    """
    for c, _ in auto.WalkControl(linha, maxDepth=2):
        if c.ControlTypeName == "DataItemControl":
            nome = (c.Name or "").lower()
            if nome.startswith("[x]"):
                return c
    return None


def selecionar_linha_por_checkbox(linha):
    print("☑️ Selecionando linha pelo checkbox")

    chk = localizar_checkbox_linha(linha)
    if not chk:
        raise RuntimeError("❌ Checkbox '[x] linha' não encontrado")

    rect = chk.BoundingRectangle
    x = rect.left + (rect.right - rect.left) // 2
    y = rect.top + (rect.bottom - rect.top) // 2

    auto.Click(x, y)
    t(0.4)

    print("✅ Linha ativada")
