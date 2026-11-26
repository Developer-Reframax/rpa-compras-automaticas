# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle, aguardar_controle_sumir
from rpa_rm_faturamento.utils.timing import t
from rpa_rm_faturamento.utils.exceptions import ErroRMDuranteFaturamentoError


def _assinatura_controle(ctrl):
    try:
        runtime_id = ctrl.GetRuntimeId()
        if runtime_id:
            return ("runtime_id", tuple(runtime_id))
    except Exception:
        pass

    try:
        hwnd = int(getattr(ctrl, "NativeWindowHandle", 0) or 0)
        if hwnd:
            return ("hwnd", hwnd)
    except Exception:
        pass

    return None


def _iterar_commit_bars(max_depth=8):
    root = auto.GetRootControl()
    for ctrl, _ in auto.WalkControl(root, maxDepth=max_depth):
        try:
            if ctrl.ControlTypeName != "PaneControl":
                continue
            if ctrl.Name != "commitBar":
                continue
            if not ctrl.Exists(0, 0):
                continue
            yield ctrl
        except Exception:
            continue


def _obter_titulo_janela(janela):
    try:
        titulo = (janela.Name or "").strip()
        if titulo:
            return titulo
    except Exception:
        pass

    try:
        title_bar = auto.TitleBarControl(searchFromControl=janela)
        if not title_bar.Exists(0, 0):
            return ""

        partes = []
        for ctrl, _ in auto.WalkControl(title_bar, maxDepth=3):
            if ctrl.ControlTypeName == "TextControl" and ctrl.Name:
                texto = ctrl.Name.strip()
                if texto:
                    partes.append(texto)

        return " ".join(partes).strip()
    except Exception:
        return ""


def _aguardar_fim_progress_faturar_receber(janela_confirmacao, timeout=300, intervalo=0.3):
    print("⏳ Aguardando processamento do Faturar/Receber finalizar...")

    start = time.time()
    progress_foi_visto = False
    sem_progress_estavel = 0
    # 30s: margem segura para AVD onde o RM pode demorar a iniciar o progresso
    # (localmente o overhead é de ~18s extras no pior caso, aceitável)
    janela_sem_progress_min = 30

    while True:
        # Verifica se o RM exibiu janela de erro durante o processamento
        erro_rm = _capturar_e_fechar_erro_rm_modal()
        if erro_rm:
            raise ErroRMDuranteFaturamentoError(erro_rm)

        existe_progress = False
        try:
            progress = auto.ProgressBarControl(
                searchFromControl=janela_confirmacao,
                Name="progressBar",
            )
            existe_progress = progress.Exists(0, 0)
        except Exception:
            existe_progress = False

        # Fallback: busca ampla apenas enquanto o progress ainda nao foi detectado.
        # Apos progress_foi_visto=True, evita WalkControl caro em cada poll —
        # o RMSJobResultViewer passa a ser o sinal de conclusao.
        if not existe_progress and not progress_foi_visto:
            try:
                for ctrl, _ in auto.WalkControl(janela_confirmacao, maxDepth=6):
                    if ctrl.ControlTypeName == "ProgressBarControl" and ctrl.Exists(0, 0):
                        existe_progress = True
                        break
            except Exception:
                pass

        if existe_progress:
            progress_foi_visto = True
            sem_progress_estavel = 0
        else:
            sem_progress_estavel += 1
            decorrido = time.time() - start

            if progress_foi_visto:
                # Sinal positivo de conclusão: RMSJobResultViewer aparece no pnlWizard
                # quando o processamento termina, substituindo o painel de progresso.
                # Detecção imediata — não depende de contar polls sem ProgressBar.
                try:
                    rv = auto.PaneControl(
                        searchFromControl=janela_confirmacao,
                        Name="RMSJobResultViewer",
                    )
                    if rv.Exists(0, 0):
                        print("✅ Processamento finalizado (RMSJobResultViewer detectado).")
                        return
                except Exception:
                    pass

                # Fallback: progressBar sumiu por 2 polls estáveis
                # (era 3 × 0.5s = 1.5s; agora 2 × 0.3s = 0.6s)
                if sem_progress_estavel >= 2:
                    print("✅ Processamento finalizado (progressBar encerrado).")
                    return

            # Se nunca apareceu, segue apos janela maior de observacao
            # para reduzir falso negativo em telas lentas.
            if not progress_foi_visto and decorrido >= janela_sem_progress_min:
                print("ℹ️ progressBar nao foi exibido; seguindo fluxo.")
                return

        if time.time() - start > timeout:
            raise TimeoutError(
                "❌ Timeout aguardando processamento do Faturar/Receber finalizar"
            )

        time.sleep(intervalo)


def _clicar_botao_seguro(botao, descricao_botao):
    try:
        botao.SetFocus()
        time.sleep(0.1)
    except Exception:
        pass

    try:
        botao.GetInvokePattern().Invoke()
        print(f"🖱️ Clique via InvokePattern em: {descricao_botao}")
        return
    except Exception:
        pass

    botao.Click()
    print(f"🖱️ Clique via Click em: {descricao_botao}")


def _obter_botao_fechar_confirmacao(janela_confirmacao):
    # No RM desta tela, o botao de fechar geralmente expoe Name/AutomationId "btnCancel".
    criterios = (
        {"Name": "btnCancel"},
        {"AutomationId": "btnCancel"},
    )

    for criterio in criterios:
        try:
            btn = auto.ButtonControl(searchFromControl=janela_confirmacao, **criterio)
            if not btn.Exists(0, 0):
                continue

            try:
                if not btn.IsEnabled:
                    continue
            except Exception:
                pass

            nome_log = criterio.get("Name") or criterio.get("AutomationId") or "botao"
            return btn, nome_log
        except Exception:
            continue

    return None, None


def _janela_tem_estrutura_faturar_receber(janela):
    if not janela:
        return False

    for pane_name in ("pnlWizard", "RMSJobProgress", "pnlButtons"):
        try:
            pane = auto.PaneControl(searchFromControl=janela, Name=pane_name)
            if pane.Exists(0, 0):
                return True
        except Exception:
            continue

    return False


def _capturar_e_fechar_erro_rm_modal() -> str | None:
    """
    Verifica se há janela de erro modal do RM (Name='RM', ClassName='#32770',
    botão OK AutomationId='2'). Se existir: captura a mensagem, fecha o diálogo
    e retorna o texto. Retorna None se a janela não estiver presente.
    """
    try:
        janela = auto.WindowControl(Name="RM", ClassName="#32770")
        if not janela.Exists(0, 0):
            return None

        btn_ok = auto.ButtonControl(searchFromControl=janela, AutomationId="2")
        if not btn_ok.Exists(0, 0):
            return None

        mensagem = ""
        try:
            texto = auto.TextControl(searchFromControl=janela, AutomationId="65535")
            if texto.Exists(0, 0):
                mensagem = (texto.Name or "").strip()
        except Exception:
            pass

        if not mensagem:
            mensagem = "Erro RM durante faturamento (mensagem nao capturada)"

        print(f"⚠️ Erro RM durante faturamento detectado: {mensagem[:120]}")

        try:
            btn_ok.Click()
            t(0.5)
        except Exception:
            pass

        return mensagem
    except Exception:
        return None


def _aceitar_dialog_confirmacao_rm(timeout: float = 10) -> bool:
    """
    Aguarda e aceita diálogo de confirmação do RM (Name='RM', ClassName='#32770')
    clicando em 'Sim' ou 'OK'. Retorna True se clicou, False se esgotou o timeout.
    """
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            janela = auto.WindowControl(Name="RM", ClassName="#32770")
            if janela.Exists(0, 0):
                for nome_btn in ("Sim", "OK"):
                    try:
                        btn = auto.ButtonControl(searchFromControl=janela, Name=nome_btn)
                        if btn.Exists(0, 0):
                            btn.Click()
                            t(0.5)
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _fechar_janelas_faturamento_apos_erro(janela_movimento=None, timeout: float = 40) -> None:
    """
    Após erro RM durante faturamento:
    1. Fecha o wizard 'Faturar/Receber' via btnCancel (se aberto).
    2. Fecha o formulário do movimento via botão Close da barra de título (se ainda aberto).
    Após cada tentativa de fechamento trata diálogo de confirmação (clica Sim/OK).
    """
    print("🔧 Fechando janelas de faturamento apos erro RM...")
    inicio = time.time()

    while time.time() - inicio < timeout:
        # 1. Wizard Faturar/Receber (caso mais comum — erro durante processamento)
        janela_faturar = _obter_janela_faturar_receber()
        if janela_faturar:
            btn, nome = _obter_botao_fechar_confirmacao(janela_faturar)
            if btn:
                print(f"🖱️ Cancelando wizard Faturar/Receber via {nome}")
                _clicar_botao_seguro(btn, nome)
                t(1.5)
            _aceitar_dialog_confirmacao_rm(timeout=8)
            t(0.5)
            continue

        # 2. Formulário do movimento (erro ocorreu antes do wizard abrir)
        if janela_movimento:
            try:
                if janela_movimento.Exists(0, 0):
                    title_bar = auto.TitleBarControl(searchFromControl=janela_movimento)
                    if title_bar.Exists(0, 0):
                        btn_close = auto.ButtonControl(
                            searchFromControl=title_bar, Name="Close"
                        )
                        if btn_close.Exists(0, 0):
                            print("🖱️ Fechando formulario do movimento via botao Close")
                            btn_close.Click()
                            t(1.5)
                            _aceitar_dialog_confirmacao_rm(timeout=8)
                            t(0.5)
                            continue
            except Exception:
                pass

        # Nenhuma janela encontrada — cleanup concluido
        break

    print("✅ Limpeza apos erro RM concluida")


def _obter_janela_faturar_receber():
    def _eh_janela_candidata(win):
        try:
            if win.ControlTypeName != "WindowControl":
                return False
            if not win.Exists(0, 0):
                return False
            if hasattr(win, "IsVisible") and not win.IsVisible:
                return False
        except Exception:
            return False

        try:
            titulo = (win.Name or "").strip().lower()
        except Exception:
            titulo = ""

        # Sinais estruturais observados no Inspect para a janela Faturar / Receber.
        tem_estrutura_rm = _janela_tem_estrutura_faturar_receber(win)

        tem_btn_cancel = False
        for criterio_btn in ({"Name": "btnCancel"}, {"AutomationId": "btnCancel"}):
            try:
                btn = auto.ButtonControl(searchFromControl=win, **criterio_btn)
                if btn.Exists(0, 0):
                    tem_btn_cancel = True
                    break
            except Exception:
                continue

        tem_titulo_compativel = ("faturar" in titulo and "receber" in titulo)
        # Evita falso positivo: precisa ter estrutura da tela e algum sinal complementar.
        return tem_estrutura_rm and (tem_titulo_compativel or tem_btn_cancel)

    try:
        root = auto.GetRootControl()
        for win in root.GetChildren():
            if _eh_janela_candidata(win):
                return win
    except Exception:
        pass

    return None


def _obter_janela_por_assinatura(assinatura):
    if not assinatura:
        return None

    try:
        root = auto.GetRootControl()
        for win in root.GetChildren():
            try:
                if win.ControlTypeName != "WindowControl":
                    continue
                if not win.Exists(0, 0):
                    continue
                if _assinatura_controle(win) == assinatura:
                    return win
            except Exception:
                continue
    except Exception:
        pass

    return None


def _fechar_janela_faturar_receber_pos_progress(janela_confirmacao, timeout=60, intervalo=0.3):
    print("⏳ Tentando fechar janela Faturar/Receber apos fim do progress...")

    assinatura_alvo = _assinatura_controle(janela_confirmacao)
    titulo_alvo = (_obter_titulo_janela(janela_confirmacao) or "").strip().lower()
    inicio = time.time()
    ausente_estavel = 0
    ultimo_alt_f = 0.0
    ultimo_click = 0.0

    while True:
        janela_alvo = None

        if assinatura_alvo:
            janela_alvo = _obter_janela_por_assinatura(assinatura_alvo)
        else:
            # Sem assinatura confiavel, primeiro tenta o mesmo objeto capturado.
            try:
                if janela_confirmacao and janela_confirmacao.Exists(0, 0):
                    janela_alvo = janela_confirmacao
            except Exception:
                janela_alvo = None

            # Fallback restrito: so aceita janela candidata se o titulo bater com a janela original.
            if not janela_alvo and titulo_alvo:
                janela_candidata = _obter_janela_faturar_receber()
                if janela_candidata:
                    titulo_candidato = (_obter_titulo_janela(janela_candidata) or "").strip().lower()
                    if titulo_candidato and titulo_candidato == titulo_alvo:
                        janela_alvo = janela_candidata

        if not janela_alvo:
            ausente_estavel += 1
            if ausente_estavel >= 2:
                print("✅ Janela Faturar/Receber fechada.")
                return
        else:
            ausente_estavel = 0
            if not _janela_tem_estrutura_faturar_receber(janela_alvo):
                # Janela mudou de contexto; evita tentar fechar o RM por botao generico.
                print("ℹ️ Janela alvo sem estrutura de Faturar/Receber; considerando fluxo encerrado.")
                return

            btn_fechar, nome_botao = _obter_botao_fechar_confirmacao(janela_alvo)
            if btn_fechar:
                agora = time.time()
                if agora - ultimo_click >= 1.0:
                    print(f"🖱️ Tentando fechar janela Faturar/Receber via botao: {nome_botao}")
                    _clicar_botao_seguro(btn_fechar, nome_botao)
                    ultimo_click = agora
            else:
                # Sem btnCancel habilitado: evita fallback agressivo que pode fechar o RM.
                agora = time.time()
                if agora - ultimo_alt_f >= 3.0:
                    print("ℹ️ btnCancel indisponivel; aguardando reaparecer ou janela encerrar.")
                    ultimo_alt_f = agora

        if time.time() - inicio > timeout:
            raise TimeoutError("❌ Timeout aguardando janela confirmacao de alteracao fechar")

        time.sleep(intervalo)


def confirmar_movimento(janela_movimento):
    print("✅ Confirmando criacao do movimento (btnOK)")

    # 1) Clica no OK do movimento (commitBar)
    commit_bar = aguardar_controle(
        lambda: auto.PaneControl(searchFromControl=janela_movimento, Name="commitBar"),
        timeout=20,
        descricao="commitBar",
    )

    btn_ok = aguardar_controle(
        lambda: auto.ButtonControl(searchFromControl=commit_bar, Name="btnOK"),
        timeout=15,
        descricao="botao OK do movimento",
    )

    assinatura_commit_original = _assinatura_controle(commit_bar)
    btn_ok.Click()

    # 2–4) Fluxo pós-confirmação: mensagens, movimento criado e wizard.
    # Se o RM exibir janela de erro em qualquer desses passos (ex.: restrição
    # de data de fechamento de estoque), o erro já foi capturado e fechado
    # internamente. Aqui fazemos o cleanup das janelas restantes e re-lançamos
    # para o orquestrador marcar o lote como NAO FATURADO e reiniciar o ciclo.
    try:
        # 2) Mensagens de aviso do RM (captura + fecha)
        mensagem_rm = tratar_mensagem_aviso_movimento(janela_movimento)

        # 3) Aguarda movimento criado e confirma no btnOK
        confirmar_movimento_criado(assinatura_commit_original=assinatura_commit_original)

        # 4) Aguarda janela de confirmacao/alteracao e clica no Cancel
        tratar_janela_confirmacao_alteracao()

    except ErroRMDuranteFaturamentoError:
        _fechar_janelas_faturamento_apos_erro(janela_movimento)
        raise

    # 5) Garante que a janela original fechou (apenas no caminho de sucesso)
    aguardar_controle_sumir(
        lambda: janela_movimento,
        timeout=180,
        descricao="janela do movimento original",
    )

    print("🏁 Confirmacao completa finalizada.")
    return mensagem_rm


def tratar_mensagem_aviso_movimento(janela_movimento=None):
    print("📢 Verificando mensagens de aviso do movimento...")

    # Aguarda a janela esperada, mas também monitora se o RM exibiu um erro
    # em vez da mensagem de aviso (ex.: restrição de data de fechamento de estoque).
    inicio = time.time()
    timeout_aviso = 120
    janela_msg = None

    while time.time() - inicio < timeout_aviso:
        erro_rm = _capturar_e_fechar_erro_rm_modal()
        if erro_rm:
            raise ErroRMDuranteFaturamentoError(erro_rm)

        try:
            ctrl = auto.WindowControl(Name="Mensagens de Aviso do Movimento")
            if ctrl.Exists(0, 0):
                janela_msg = ctrl
                break
        except Exception:
            pass

        time.sleep(0.4)

    if janela_msg is None:
        raise TimeoutError("❌ Timeout aguardando janela Mensagens de Aviso do Movimento (120s)")

    # Captura texto da mensagem
    campo_msg = aguardar_controle(
        lambda: auto.EditControl(searchFromControl=janela_msg, Name="tbMensagem"),
        timeout=20,
        descricao="campo tbMensagem",
    )

    try:
        mensagem = campo_msg.GetValuePattern().Value
    except Exception:
        mensagem = ""

    print("🧾 Mensagem do RM:")
    print(mensagem)

    # Fecha a janela
    btn_ok = aguardar_controle(
        lambda: auto.ButtonControl(searchFromControl=janela_msg, Name="btnOk"),
        timeout=15,
        descricao="btnOk mensagem aviso",
    )

    btn_ok.Click()

    # Aguarda janela sumir
    aguardar_controle_sumir(
        lambda: janela_msg,
        timeout=60,
        descricao="janela Mensagens de Aviso do Movimento",
    )

    return mensagem


def confirmar_movimento_criado(assinatura_commit_original=None):
    print("📂 Aguardando janela do movimento criado (1.1.15)...")

    start = time.time()
    timeout = 180
    commit_bar_mov_criado = None

    while True:
        for commit_bar in _iterar_commit_bars(max_depth=8):
            try:
                assinatura_commit = _assinatura_controle(commit_bar)
                if (
                    assinatura_commit_original
                    and assinatura_commit
                    and assinatura_commit == assinatura_commit_original
                ):
                    continue

                btn_ok = auto.ButtonControl(searchFromControl=commit_bar, Name="btnOK")
                if not btn_ok.Exists(0, 0):
                    continue

                # Se o titulo existir, ele ajuda a evitar falso positivo.
                janela = commit_bar.GetTopLevelControl()
                titulo = _obter_titulo_janela(janela)
                if titulo and "Movimento" in titulo and "1.1.15" not in titulo:
                    continue

                commit_bar_mov_criado = commit_bar
                if titulo:
                    print(f"🔎 Janela candidata detectada: {titulo}")
                else:
                    print("🔎 Janela candidata detectada (titulo indisponivel)")
                break
            except Exception:
                continue

        if commit_bar_mov_criado:
            break

        if time.time() - start > timeout:
            raise TimeoutError(
                "❌ Timeout aguardando janela do movimento criado (1.1.15)"
            )

        time.sleep(0.5)

    print("✅ Janela do movimento criada detectada com sucesso")

    # Confirma no commitBar
    commit_bar = aguardar_controle(
        lambda: commit_bar_mov_criado,
        timeout=30,
        descricao="commitBar movimento criado",
    )

    btn_ok = aguardar_controle(
        lambda: auto.ButtonControl(
            searchFromControl=commit_bar,
            Name="btnOK"
        ),
        timeout=30,
        descricao="btnOK movimento criado",
    )

    btn_ok.Click()
    print("✅ Movimento criado confirmado")


def tratar_janela_confirmacao_alteracao():
    print("⚠️ Aguardando janela de confirmacao de alteracao...")

    janela_confirmacao = aguardar_controle(
        lambda: _obter_janela_faturar_receber(),
        timeout=120,
        descricao="janela confirmacao de alteracao",
    )

    _aguardar_fim_progress_faturar_receber(
        janela_confirmacao=janela_confirmacao,
        timeout=300,
    )
    _fechar_janela_faturar_receber_pos_progress(
        janela_confirmacao=janela_confirmacao,
        timeout=60,
    )

    print("✅ Janela de confirmacao tratada")
