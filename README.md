# RPA RM Faturamento

Projeto corporativo para faturamento automatizado no TOTVS RM com orquestracao, observabilidade e integracao com Supabase.

**Arquitetura**

Estrutura de pastas:

```
rpa_rm_faturamento/
├── main.py
├── orchestrator/
├── rm/
├── supabase/
├── services/
├── logging/
├── utils/
├── config/
└── README.md
```

**Fluxo**

1. Abre o RM e aguarda atualizacao.
2. Realiza login automaticamente.
3. Acessa Solicitação de Compras (1.1.04).
4. Filtra pendentes e marca movimentos.
5. Executa Receber e cria movimento 1.1.15.
6. Preenche cabecalho, itens e tributos.
7. Confirma faturamento e captura mensagem do RM.
8. Atualiza status no Supabase e grava logs.
9. Rele o Supabase e continua o loop sem reiniciar o RM.

**Regras de Negocio**

1. Processar somente itens com status `A FATURAR`.
2. Um faturamento nao pode misturar filiais diferentes.
3. Um faturamento nao pode misturar fornecedores diferentes.
4. Um faturamento pode conter multiplos movimentos 1.1.04.
5. Ao finalizar, atualizar status para `FATURADO` e registrar `msg_mov_gerado`.
6. A cada faturamento, reler o Supabase para evitar duplicidade.
7. O RM nao e fechado entre faturamentos.

**Tabelas no Supabase**

`dados_lof_rpa`:

- id
- numero_movimento
- cod_prd
- cnpj_fornecedor
- preco_unitario
- IPI
- ICMS
- cod_comprador
- tipo_frete
- filial
- cod_pagamento
- dias_entrega_fornecedor
- msg_mov_gerado
- status

`rpa_logs`:

- id
- execution_id
- timestamp
- level
- step
- message
- payload
- movimento_origem
- movimento_destino
- filial
- fornecedor
- item
- duration_ms

**Logs e Observabilidade**

Os logs sao gravados em:

- Terminal
- Arquivo local rotativo
- Supabase (tabela `rpa_logs`)

Exemplos de analises no Power BI:

1. Quantidade de itens faturados por dia.
2. Tempo medio por faturamento.
3. Erros por etapa.
4. Faturamentos por fornecedor e filial.
5. SLA do robo.

**Como Rodar**

1. Instale as dependencias.
   - Via `pip` (recomendado):
     ```bash
     python -m pip install --upgrade pip
     python -m pip install uiautomation supabase psutil comtypes
     ```
   - Opcional via `requirements.txt` (se preferir manter um arquivo de dependencias):
     ```bash
     python -m pip install -r requirements.txt
     ```
2. Configure as variaveis de ambiente.
3. Execute `python -m rpa_rm_faturamento.main`.

Dependencias principais:

- Python 3.10+
- uiautomation
- supabase
- psutil
- comtypes

**Variaveis de Ambiente**

- `RPA_ENV` (default: `DEV`, use `PROD` em producao)
- `DEV_CONFIG_PATH` (default: `rpa_rm_faturamento/config/dev_settings.json`)
- `RM_EXECUTABLE_PATH`
- `RM_USUARIO`
- `RM_SENHA`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_TABLE_DADOS` (default: `dados_lof_rpa`)
- `SUPABASE_TABLE_LOGS` (default: `rpa_logs`)
- `HISTORICO_MOVIMENTO` (default: texto padrao)
- `LOG_LEVEL` (default: `INFO`)
- `LOG_FILE_PATH` (default: `logs/rpa_rm_faturamento.log`)
- `LOG_MAX_BYTES` (default: `5242880`)
- `LOG_BACKUP_COUNT` (default: `5`)

**Ambiente DEV**

Em desenvolvimento o robo utiliza o arquivo `rpa_rm_faturamento/config/dev_settings.json`.
Em producao o robo usa apenas variaveis de ambiente (`RPA_ENV=PROD`).

**Notas Importantes**

- O arquivo `teteRm.py` permanece intacto e serve como referencia do fluxo funcional.
- As regras de interacao com a tela foram preservadas.
- Ajuste os dados no Supabase para garantir consistencia de comprador, frete e pagamento dentro do mesmo lote.
