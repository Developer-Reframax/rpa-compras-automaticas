-- 001_init.sql
-- Cria as tabelas do zero para o RPA (drop + create)

-- Extensao para gerar UUID (se ainda nao estiver habilitada)
create extension if not exists "pgcrypto";

-- Remove tabelas antigas para recriar do zero
drop table if exists public.rpa_logs;
drop table if exists public.dados_lof_rpa;

-- Tabela de dados do faturamento
create table public.dados_lof_rpa (
    id bigserial primary key,
    numero_movimento text not null,
    cod_prd text not null,
    cnpj_fornecedor text not null,
    preco_unitario numeric(18, 4),
    "IPI" text,
    "ICMS" text,
    cod_comprador text not null,
    tipo_frete text not null,
    filial text not null,
    cod_pagamento text not null,
    dias_entrega_fornecedor integer,
    msg_mov_gerado text,
    status text not null default 'A FATURAR',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint chk_status_dados_lof_rpa
        check (status in ('A FATURAR', 'FATURADO'))
);

create index idx_dados_lof_rpa_status on public.dados_lof_rpa (status);
create index idx_dados_lof_rpa_filial on public.dados_lof_rpa (filial);
create index idx_dados_lof_rpa_fornecedor on public.dados_lof_rpa (cnpj_fornecedor);
create index idx_dados_lof_rpa_movimento on public.dados_lof_rpa (numero_movimento);

-- Tabela de logs do RPA
create table public.rpa_logs (
    id bigserial primary key,
    execution_id uuid not null,
    timestamp timestamptz not null,
    level text not null,
    step text not null,
    message text not null,
    payload jsonb,
    movimento_origem text,
    movimento_destino text,
    filial text,
    fornecedor text,
    item text,
    duration_ms integer
);

create index idx_rpa_logs_execution_id on public.rpa_logs (execution_id);
create index idx_rpa_logs_timestamp on public.rpa_logs (timestamp);
create index idx_rpa_logs_level on public.rpa_logs (level);
create index idx_rpa_logs_step on public.rpa_logs (step);
