# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle
from rpa_rm_faturamento.utils.timing import t
from rpa_rm_faturamento.utils.ui_helpers import (
    acessar_item_lista,
    arrastar_scroll_ate_coluna,
    resetar_cache_navbar,
    resetar_scroll_horizontal,
)
from rpa_rm_faturamento.rm.rm_tributos import preencher_aliquota
from rpa_rm_faturamento.supabase.models import ItemAFaturar


def _scroll_vertical_n_linhas(tabela, n: int = 3) -> None:
    """
    Rola o grid n linhas para baixo via botão da scrollbar vertical.
    Usado para tirar o item da borda inferior do viewport antes de retentar o clique.
    """
    try:
        sb = None
        for c, _ in auto.WalkControl(tabela, maxDepth=3):
            if c.ControlTypeName == "ScrollBarControl" and (c.Name or "").lower() == "vertical":
                sb = c
                break
        if not sb:
            return
        btn = None
        for c, _ in auto.WalkControl(sb, maxDepth=2):
            if c.ControlTypeName == "ButtonControl" and "linha para baixo" in (c.Name or "").lower():
                btn = c
                break
        if btn:
            for _ in range(n):
                btn.Click()
                time.sleep(0.05)
            time.sleep(0.25)
    except Exception:
        pass


def _localizar_linha_no_grid(tabela, codigo_produto: str):
    """
    Busca a linha pelo código de produto no Value serializado do ListItemControl.
    Funciona independente da posição do scroll horizontal porque o Value sempre
    contém todos os campos, inclusive os off-screen.
    Formato: 'status;seq;produto;desc;...' -> produto está no índice 2.
    """
    try:
        painel = next(c for c in tabela.GetChildren() if c.Name == "Painel de dados")
        for linha in painel.GetChildren():
            try:
                valor = linha.GetValuePattern().Value or ""
                campos = valor.split(";")
                if len(campos) > 2 and campos[2].strip() == codigo_produto:
                    return linha
            except Exception:
                continue
    except Exception:
        pass
    return None


def marcar_faturar_grid(janela_movimento, linha, codigo_produto: str) -> None:
    print("☑️ Marcando Faturar no grid")

    MAX_TENTATIVAS = 3

    tabela = aguardar_controle(
        lambda: auto.TableControl(searchFromControl=janela_movimento, Name="MainView"),
        timeout=20,
        descricao="grid MainView",
    )

    idx_faturar = _obter_indice_faturar(tabela)

    for tentativa in range(MAX_TENTATIVAS):
        if tentativa > 0:
            print(f"🔄 [{tentativa + 1}/{MAX_TENTATIVAS}] Re-buscando linha após tentativa falha...")
            # Scroll vertical para tirar o item da borda inferior do viewport
            _scroll_vertical_n_linhas(tabela, n=3)
            resetar_scroll_horizontal(tabela)
            tabela = aguardar_controle(
                lambda: auto.TableControl(searchFromControl=janela_movimento, Name="MainView"),
                timeout=20,
                descricao="grid MainView",
            )
            linha = _localizar_linha_no_grid(tabela, codigo_produto)
            if not linha:
                print(f"  ⚠️ Linha não visível, fazendo varredura completa...")
                linha = localizar_linha_produto(janela_movimento, codigo_produto)
            if not linha:
                raise RuntimeError(f"❌ Produto '{codigo_produto}' não encontrado na tentativa {tentativa + 1}")

        cel_faturar = arrastar_scroll_ate_coluna(
            tabela=tabela,
            linha=linha,
            nome_coluna="Faturar",
            direcao="direita",
        )

        if not cel_faturar:
            print(f"  ⚠️ [{tentativa + 1}/{MAX_TENTATIVAS}] Coluna 'Faturar' não localizada após scroll")
            continue

        rect = cel_faturar.BoundingRectangle
        auto.Click(rect.left + (rect.right - rect.left) // 2, rect.top + (rect.bottom - rect.top) // 2)
        time.sleep(0.6)

        # Verifica se Faturar foi efetivamente marcado relendo o Value da linha
        linha_check = _localizar_linha_no_grid(tabela, codigo_produto) or linha
        if _faturar_esta_marcado(linha_check, idx_faturar):
            print("✅ Checkbox Faturar marcado e verificado")
            return

        print(f"  ⚠️ [{tentativa + 1}/{MAX_TENTATIVAS}] Faturar não confirmado após clique, retentando...")

    raise RuntimeError(f"❌ Não foi possível marcar Faturar para '{codigo_produto}' após {MAX_TENTATIVAS} tentativas")


def garantir_num_sequencial_visivel(janela_movimento, linha):
    print("↩️ Resetando scroll horizontal para esquerda (drag real)")

    tabela = aguardar_controle(
        lambda: auto.TableControl(searchFromControl=janela_movimento, Name="MainView"),
        timeout=20,
        descricao="grid MainView",
    )

    cel = arrastar_scroll_ate_coluna(
        tabela=tabela,
        linha=linha,
        nome_coluna="Nº Sequencial",
        direcao="esquerda",
        max_passos=3,
    )

    if not cel:
        raise RuntimeError("❌ Não consegui retornar o scroll para 'Nº Sequencial'.")

    print("✅ Scroll resetado corretamente.")
    return cel


def preencher_preco_unitario_item(janela_item, preco: float) -> None:
    print(f"💰 Preenchendo Preço Unitário no item: {preco}")

    campo = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela_item, Name="tbxPRECOUNITARIO"),
        timeout=20,
        descricao="campo Preço Unitário (tbxPRECOUNITARIO)",
    )

    campo.SetFocus()
    t(0.2)

    valor = f"{preco:.2f}".replace(".", ",")

    # Tenta via ValuePattern (mais estável no RM)
    try:
        vp = campo.GetValuePattern()
        vp.SetValue("")
        t(0.1)
        vp.SetValue(valor)
    except Exception:
        # Fallback por teclado
        campo.SendKeys("{Ctrl}a{Del}")
        t(0.1)
        campo.SendKeys(valor)

    # Confirma edição
    campo.SendKeys("{Tab}")
    t(0.8)

    print("✅ Preço Unitário preenchido no Item de Movimento")


def _obter_indice_faturar(tabela) -> int:
    """
    Determina o índice da coluna Faturar na string serializada do ListItemControl.
    O RM representa cada linha como campos separados por ';' no Value, na mesma
    ordem dos HeaderControls do Cabeçalho (incluindo os off-screen).
    Retorna -1 se não encontrado.
    """
    try:
        cabecalho = next(
            c for c in tabela.GetChildren()
            if c.ControlTypeName == "CustomControl" and c.Name == "Cabeçalho"
        )
        colunas = [c.Name for c in cabecalho.GetChildren() if c.ControlTypeName == "HeaderControl"]
        return colunas.index("Faturar")
    except (ValueError, StopIteration, Exception):
        return -1


def _faturar_esta_marcado(linha, idx_faturar: int) -> bool:
    """
    Lê o Value do ListItemControl (string ';'-separada com TODOS os campos,
    inclusive os off-screen) e verifica se o campo Faturar é 'True'.

    A abordagem via DataItemControl off-screen não funciona porque o RM não
    renderiza células fora da viewport na árvore UIA — por isso usamos o
    Value serializado do próprio ListItemControl, que sempre contém tudo.
    """
    if idx_faturar < 0:
        return False
    try:
        valor_linha = linha.GetValuePattern().Value or ""
        campos = valor_linha.split(";")
        if idx_faturar < len(campos):
            return campos[idx_faturar].strip().lower() == "true"
    except Exception:
        pass
    return False


def _rolar_grid_para_topo(tabela) -> None:
    """Rola o grid verticalmente para a primeira linha via Ctrl+Home."""
    try:
        tabela.Click()
        time.sleep(0.2)
        auto.SendKeys("{Ctrl}{Home}")
        time.sleep(0.3)
        return
    except Exception:
        pass
    # Fallback: RangeValuePattern no ScrollBar vertical
    try:
        sb = auto.ScrollBarControl(searchFromControl=tabela, Name="Vertical")
        if sb.Exists(0, 0):
            rvp = sb.GetRangeValuePattern()
            rvp.SetValue(rvp.MinimumValue)
            time.sleep(0.3)
    except Exception:
        pass


def _nomes_linhas_visiveis(tabela) -> frozenset:
    """Retorna frozenset dos nomes das linhas visíveis no Painel de dados."""
    try:
        painel = next(c for c in tabela.GetChildren() if c.Name == "Painel de dados")
        return frozenset(l.Name for l in painel.GetChildren())
    except Exception:
        return frozenset()


def _rolar_grid_proxima_pagina(tabela) -> None:
    """Rola o grid uma página para baixo via PgDn."""
    try:
        auto.SendKeys("{PgDn}")
        time.sleep(0.3)
        return
    except Exception:
        pass
    # Fallback: botão "Página abaixo" ou "Uma linha para baixo" repetido
    try:
        sb = auto.ScrollBarControl(searchFromControl=tabela, Name="Vertical")
        if sb.Exists(0, 0):
            btn_pgdn = auto.ButtonControl(searchFromControl=sb, Name="Página abaixo")
            if btn_pgdn.Exists(0, 0):
                btn_pgdn.Click()
                time.sleep(0.3)
                return
            btn_down = auto.ButtonControl(searchFromControl=sb, Name="Uma linha para baixo")
            if btn_down.Exists(0, 0):
                for _ in range(5):
                    btn_down.Click()
                    time.sleep(0.05)
                time.sleep(0.2)
    except Exception:
        pass


def localizar_linha_produto(janela, codigo_produto: str):
    """
    Localiza a primeira linha do grid cujo código de produto bate com
    `codigo_produto` E cuja coluna Faturar ainda NÃO está marcada.

    Percorre TODO o grid (rola do topo ao fim) antes de concluir que o
    produto não existe, evitando falso negativo quando o item está fora
    da área visível da tela.
    """
    tabela = aguardar_controle(
        lambda: auto.TableControl(searchFromControl=janela, Name="MainView"),
        descricao="tabela de itens",
    )

    idx_faturar = _obter_indice_faturar(tabela)

    # Garante varredura a partir do topo do grid
    _rolar_grid_para_topo(tabela)

    nomes_pagina_anterior = None
    limite_paginas = 200  # segurança contra loop infinito

    for _ in range(limite_paginas):
        nomes_pagina_atual = _nomes_linhas_visiveis(tabela)

        # Chegamos ao fim: mesmas linhas visíveis que na iteração anterior
        if nomes_pagina_atual == nomes_pagina_anterior:
            break

        # Escaneia linhas visíveis nesta "página"
        try:
            painel_dados = next(c for c in tabela.GetChildren() if c.Name == "Painel de dados")
            for linha in painel_dados.GetChildren():
                for cel in linha.GetChildren():
                    if cel.Name.startswith("Produto"):
                        valor = cel.GetValuePattern().Value or ""
                        if valor.strip() == codigo_produto:
                            if _faturar_esta_marcado(linha, idx_faturar):
                                print(f"  ↩️ '{codigo_produto}' Faturar=True, buscando próxima ocorrência.")
                                break  # próxima linha
                            return linha
        except Exception:
            pass

        nomes_pagina_anterior = nomes_pagina_atual
        _rolar_grid_proxima_pagina(tabela)

    return None


def abrir_item_movimento(linha) -> None:
    print("📂 Abrindo Item de Movimento (Ctrl + Enter)")

    cel_seq = None

    for cel in linha.GetChildren():
        if cel.Name.startswith("Nº Sequencial"):
            cel_seq = cel
            break

    if not cel_seq:
        raise RuntimeError("❌ Coluna 'Nº Sequencial' não encontrada na linha")

    # 1) Click simples para selecionar a célula
    rect = cel_seq.BoundingRectangle
    x = rect.left + (rect.right - rect.left) // 2
    y = rect.top + (rect.bottom - rect.top) // 2

    auto.Click(x, y)

    # FIX AVD (Problema 14): aguarda o grid processar o foco na célula antes
    # de enviar Ctrl+Enter. Em AVD, 0.25s era insuficiente para o input registrar.
    t(0.5)

    # 2) Atalho Ctrl + Enter (abre propriedades)
    auto.SendKeys("{Ctrl}{Enter}")
    t(0.3)

    print("⏳ Aguardando janela 'Item de Movimento'...")

    # 3) REGRA DE OURO: aguarda nova janela abrir
    aguardar_controle(
        lambda: auto.WindowControl(NameRegex="Item de Movimento"),
        timeout=20,
        descricao="janela Item de Movimento",
    )

    print("✅ Janela de Item de Movimento aberta com sucesso")


def acessar_tributos_item(janela_item) -> None:
    navbar = aguardar_controle(
        lambda: auto.PaneControl(searchFromControl=janela_item, Name="NavBar"),
        descricao="navbar item",
    )

    acessar_item_lista(navbar, nome_lista="Tributos e Valores", nome_item="Tributos")


def salvar_item(janela_item) -> None:
    botao = aguardar_controle(
        lambda: auto.ButtonControl(searchFromControl=janela_item, Name="btnSave"),
        descricao="botao salvar item",
    )
    botao.Click()
    t(1.5)


def fechar_item_movimento(janela_item) -> None:
    print("✅ Confirmando e fechando Item de Movimento")

    btn_ok = aguardar_controle(
        lambda: auto.ButtonControl(searchFromControl=janela_item, Name="btnOK"),
        timeout=15,
        descricao="botao OK do Item de Movimento",
    )

    btn_ok.Click()
    t(1.0)


def tratar_itens_movimento(janela_movimento, itens: list[ItemAFaturar], logger=None) -> None:
    print("📦 Tratando itens do movimento...")

    for item in itens:
        codigo = item.cod_prd
        preco = item.preco_unitario
        ipi_str = item.ipi or "0"
        icms_str = item.icms or "0"

        try:
            ipi_val = float(ipi_str.replace(",", "."))
        except Exception:
            ipi_val = 0.0
        try:
            icms_val = float(icms_str.replace(",", "."))
        except Exception:
            icms_val = 0.0

        print(f"🔎 Processando produto {codigo}")
        if logger:
            logger.info("ITEM", "Processando item", item=codigo)

        # 1) Localiza linha do produto no grid (varre do topo ao fim)
        linha = localizar_linha_produto(janela_movimento, codigo)
        if not linha:
            print(f"⚠️ Produto {codigo} não encontrado no grid após varredura completa")
            if logger:
                logger.warning(
                    "ITEM",
                    "Produto nao encontrado no grid apos varredura completa",
                    item=codigo,
                )
            continue

        # 2) Marca checkbox FATURAR no grid (com scroll horizontal -> e <-)
        marcar_faturar_grid(janela_movimento, linha, codigo)

        # Volta o scroll para garantir Nº Sequencial visível
        garantir_num_sequencial_visivel(janela_movimento, linha)

        # 3) Abre Item de Movimento (Nº Sequencial)
        abrir_item_movimento(linha)

        janela_item = aguardar_controle(
            lambda: auto.WindowControl(NameRegex="Item de Movimento"),
            timeout=20,
            descricao="janela Item de Movimento",
        )

        # NOVA JANELA -> novo estado visual
        resetar_cache_navbar()

        navbar_item = aguardar_controle(
            lambda: auto.PaneControl(searchFromControl=janela_item, Name="NavBar"),
            timeout=60,
            intervalo=2,
            descricao="NavBar do Item",
        )

        # 4) Preço Unitário (Identificação -> Cabeçalho)
        acessar_item_lista(navbar_item, "Identificação", "Cabeçalho")

        if preco is not None:
            preencher_preco_unitario_item(janela_item, preco)
        else:
            print("ℹ️ Preço não informado, mantendo valor atual")

        # 5) Tributos (somente se houver)
        if ipi_val > 0 or icms_val > 0:
            acessar_tributos_item(janela_item)

            if ipi_val > 0:
                preencher_aliquota(janela_item, "IPI", ipi_str)

            if icms_val > 0:
                preencher_aliquota(janela_item, "ICMS", icms_str)
        else:
            print("ℹ️ Item sem tributos, pulando etapa de tributos")

        # 6) Fecha Item de Movimento (btnOK)
        fechar_item_movimento(janela_item)

        print(f"✅ Produto {codigo} processado com sucesso")
        if logger:
            logger.info("ITEM", "Item processado com sucesso", item=codigo)
