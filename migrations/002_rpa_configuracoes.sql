-- 002_rpa_configuracoes.sql
-- Tabela de configuracao consumida pela aplicacao web (aplicacao_rpa).

create table if not exists public.rpa_configuracoes (
    id bigserial primary key,
    slug text not null,
    vm_disponivel_inicio time not null default '08:00:00',
    vm_disponivel_fim time not null default '18:00:00',
    docs_md text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.rpa_configuracoes
    add column if not exists vm_disponivel_inicio time not null default '08:00:00',
    add column if not exists vm_disponivel_fim time not null default '18:00:00',
    add column if not exists docs_md text not null default '',
    add column if not exists created_at timestamptz not null default now(),
    add column if not exists updated_at timestamptz not null default now();

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'uq_rpa_configuracoes_slug'
    ) then
        alter table public.rpa_configuracoes
            add constraint uq_rpa_configuracoes_slug unique (slug);
    end if;
end $$;

create index if not exists idx_rpa_configuracoes_slug
    on public.rpa_configuracoes (slug);

-- Migra conteudo legado da tabela rpa_docs para docs_md, se existir.
do $$
begin
    if exists (
        select 1
        from information_schema.tables
        where table_schema = 'public'
          and table_name = 'rpa_docs'
    ) then
        insert into public.rpa_configuracoes (slug, docs_md, updated_at)
        select d.slug, coalesce(d.content, ''), coalesce(d.updated_at, now())
        from public.rpa_docs d
        on conflict (slug)
        do update set
            docs_md = excluded.docs_md,
            updated_at = excluded.updated_at;
    end if;
end $$;
