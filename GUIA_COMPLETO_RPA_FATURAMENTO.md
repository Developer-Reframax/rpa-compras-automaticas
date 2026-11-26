# Guia Completo do RPA de Faturamento RM

Versão para usuários de negocio e operação.

---

## 1. Objetivo deste documento

Este guia explica, de forma simples, como o robo funciona no dia a dia:

- de onde ele busca os dados;
- como ele decide o que faturar;
- como ele executa o fluxo no RM;
- como ele registra logs;
- como ele se comporta em caso de erro.

O foco aqui e entendimento do processo, sem entrar em detalhes técnicos de código.

---

## 2. O que o robô faz

O RPA automatiza o faturamento no TOTVS RM a partir de itens que chegam com status **`A FATURAR`** na base de dados.

Quando um lote termina com sucesso, o robo:

- atualiza os itens para **`FATURADO`**;
- grava a mensagem de retorno do RM em `msg_mov_gerado`;
- registra logs da execução.

---

## 3. Visão geral em 1 minuto

1. O robo abre o RM (se necessario) e verifica se o sistema esta pronto.
2. Le os itens `A FATURAR` na tabela `dados_lof_rpa`.
3. Agrupa os itens em lotes coerentes (mesma filial e mesmo fornecedor).
4. Executa o faturamento no RM para o lote.
5. Confirma, finaliza e fecha telas do processo.
6. Atualiza status dos itens para `FATURADO`.
7. Relê a base e continua ate não haver mais itens pendentes.

---

## 4. Arquitetura funcional (linguagem de negócio)

O robô pode ser entendido em 4 blocos:

1. **Entrada de dados**
- Fonte: tabela `dados_lof_rpa` no Supabase.
- Regra principal: processar apenas itens com status `A FATURAR`.

2. **Orquestração**
- Controla o ciclo completo.
- Decide qual lote executar.
- Garante que o RM esteja na tela certa para cada etapa.

3. **Execução no RM**
- Faz a navegação de telas.
- Preenche campos obrigatórios.
- Processa itens e tributos.
- Conclui o faturamento.

4. **Observabilidade**
- Gera log em terminal.
- Gera log em arquivo local.
- Gera log na tabela `rpa_logs`.

---

## 5. Fluxo completo do processo

## 5.1 Inicio do ciclo

1. O robô verifica se o RM esta aberto.
2. Se não estiver, abre o RM.
3. Se houver tela de atualização, aguarda concluir.
4. Se houver tela de login, realiza autenticação.

## 5.2 Leitura e organizacao dos dados

1. Consulta itens com status `A FATURAR`.
2. Agrupa por `filial` e `cnpj_fornecedor`.
3. Monta o primeiro lote pronto para execução.

Regras de negocio aplicadas:

- não mistura filiais no mesmo lote;
- não mistura fornecedores no mesmo lote;
- pode incluir mais de um movimento de origem no mesmo lote.

## 5.3 Execução no RM

1. Acessa Solicitação de Compras.
2. Aplica filtros e marca movimentos do lote.
3. Clica em Receber.
4. Trata o wizard de recebimento.
5. Seleciona movimento de destino.
6. Preenche cabeçaalho do movimento.
7. Processa os itens (preço e tributos quando aplicável).
8. Confirma o movimento.
9. Trata mensagens de aviso do RM.
10. Trata a janela final de confirmação (Faturar/Receber).
11. Fecha a aba do movimento ao final.

## 5.4 Fechamento do ciclo

1. Atualiza os IDs do lote para `FATURADO`.
2. Grava `msg_mov_gerado`.
3. Registra log de sucesso.
4. Relê a base para próximo ciclo.

---

## 6. Como os dados sao tratados

Campos importantes para operação:

- `status`: controla entrada e saida do fluxo (`A FATURAR` -> `FATURADO`);
- `numero_movimento`: identifica o movimento de origem;
- `filial` e `cnpj_fornecedor`: base do agrupamento em lote;
- `cod_comprador`, `tipo_frete`, `cod_pagamento`: dados de preenchimento no RM;
- `preco_unitario`, `IPI`, `ICMS`: dados por item;
- `msg_mov_gerado`: retorno final do RM.

Resultado esperado apos sucesso:

- status alterado para `FATURADO`;
- mensagem do RM registrada no item;
- trilha de log disponivel.

---

## 7. Papel do orquestrador

O orquestrador e o "gestor do processo". Ele:

- coordena todo o ciclo;
- garante ordem correta das etapas;
- escolhe o proximo lote;
- chama os modulos de execucao;
- decide quando continuar, quando parar e quando interromper por segurança.

Comportamentos importantes:

- se não houver item `A FATURAR`, finaliza a execução;
- se houver erro durante um lote, registra erro e segue para novo ciclo;
- se o faturamento concluir mas a atualização de status falhar, interrompe para evitar reprocessamento indevido.

---

## 8. Logs e rastreabilidade

O robo registra os eventos em 3 lugares:

1. Terminal (acompanhamento em tempo real).
2. Arquivo local: `logs/rpa_rm_faturamento.log`.
3. Tabela Supabase: `rpa_logs`.

Cada registro de log informa contexto da execução, por exemplo:

- etapa do processo;
- mensagem do evento;
- filial e fornecedor;
- movimento de origem e destino;
- duração de etapas;
- detalhes de erro (quando houver).

Com os logs, voce consegue responder perguntas como:

- "Qual lote foi processado agora?"
- "Onde ocorreu a falha?"
- "O status foi atualizado para FATURADO?"

---

## 9. Como o robo se comporta em caso de erro

### Erro durante o processamento do lote

- o robo registra a falha do lote;
- inicia novo ciclo;
- relê os itens pendentes na base.

### Erro na atualização de status apos faturamento concluido

- o robo registra erro crítico;
- interrompe a execução para evitar loop de reprocessamento.

### Lentidão de tela do RM

- o fluxo usa esperas controladas para detectar elementos antes de agir;
- se o tempo limite estourar, registra erro com a etapa exata.

---

## 10. Como validar se o processo deu certo

Checklist simples para operação:

1. Verificar se os itens do lote mudaram para `FATURADO`.
2. Confirmar preenchimento de `msg_mov_gerado`.
3. Confirmar log "Status atualizado para FATURADO".
4. Validar que nao restou item do mesmo lote com `A FATURAR`.

---

## 11. Boas práticas para evitar problemas

- garantir dados obrigatórios preenchidos antes da execução;
- evitar inconsistencias de cadastro dentro do mesmo lote;
- acompanhar logs durante operação;
- validar periodicamente se ha itens antigos presos em `A FATURAR`.

---

## 12. Glossario rápido

- **RPA**: robo de automação de processos.
- **Lote**: conjunto de itens processados juntos.
- **Orquestrador**: componente que coordena todo o fluxo.
- **Supabase**: base de dados usada como entrada e auditoria.
- **RM**: sistema onde o faturamento e executado.

---

## 13. Resumo executivo

O robo foi desenhado para:

- faturar com padrao e repetibilidade;
- reduzir retrabalho manual;
- manter rastreabilidade por logs;
- atualizar status automaticamente na base;
- executar em ciclos ate zerar pendências.

Em uma frase: ele transforma itens `A FATURAR` em `FATURADO` com controle de processo, evidências de execução e governança operacional.

