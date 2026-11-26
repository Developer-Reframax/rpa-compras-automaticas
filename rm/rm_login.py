# -*- coding: utf-8 -*-
import time
import uiautomation as auto

from rpa_rm_faturamento.utils.wait import aguardar_controle


def realizar_login(usuario: str, senha: str, login_window_title: str) -> None:
    print("🔐 Realizando login...")

    win = aguardar_controle(
        lambda: auto.WindowControl(Name=login_window_title),
        descricao="tela login",
    )

    win.SetActive()
    time.sleep(1)

    painel_usuario = aguardar_controle(
        lambda: auto.PaneControl(
            searchFromControl=win,
            Name="Insira seu Usuário ou E-mail",
            searchDepth=15,
        ),
        descricao="painel usuario",
    )

    edits_usuario = [
        c
        for c, _ in auto.WalkControl(painel_usuario, maxDepth=5)
        if c.ControlTypeName == "EditControl" and c.Name == "cUser"
    ]

    campo_usuario = edits_usuario[-1]
    if not (campo_usuario.GetValuePattern().Value or "").strip():
        campo_usuario.SendKeys("{Ctrl}a{Del}")
        campo_usuario.SendKeys(usuario)

    edits_todos = [
        c
        for c, _ in auto.WalkControl(win, maxDepth=20)
        if c.ControlTypeName == "EditControl" and c.Name == "cUser"
    ]

    campo_senha = [c for c in edits_todos if c not in edits_usuario][-1]
    campo_senha.SendKeys("{Ctrl}a{Del}")
    campo_senha.SendKeys(senha)

    auto.ButtonControl(searchFromControl=win, Name="Entrar").Click()

    # Aguarda a janela de login fechar ou mensagem de erro aparecer (max 30s)
    MENSAGENS_ERRO_RM = (
        "Usuário ou senha inválidos",
        "Usuário ou senha invalidos",
        "Usuário inválido",
        "Senha inválida",
        "Acesso negado",
        "Erro de autenticação",
        "Erro de autenticacao",
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        if not auto.WindowControl(Name=login_window_title).Exists(0, 0):
            print("✅ Login efetuado com sucesso — janela de login fechou")
            return

        # Verifica se o RM exibiu alguma mensagem de erro de autenticação
        for msg_name in MENSAGENS_ERRO_RM:
            try:
                janela_erro = auto.WindowControl(Name=msg_name)
                if janela_erro.Exists(0, 0):
                    print(f"❌ Falha no login: mensagem de erro detectada — '{msg_name}'")
                    # Fecha a janela de erro para liberar o próximo ciclo
                    try:
                        auto.ButtonControl(searchFromControl=janela_erro, Name="OK").Click()
                    except Exception:
                        try:
                            janela_erro.SendKeys("{Enter}")
                        except Exception:
                            pass
                    return
            except Exception:
                pass

        time.sleep(1)

    print("⚠️ Janela de login ainda aberta apos 30s — credenciais podem nao ter sido aceitas")
