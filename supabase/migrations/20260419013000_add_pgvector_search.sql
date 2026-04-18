create extension if not exists vector;

create index if not exists document_chunks_embedding_hnsw_idx
    on public.document_chunks
    using hnsw (embedding vector_cosine_ops)
    where embedding is not null;

create or replace function public.match_document_chunks(
    query_embedding vector(1536),
    match_count integer default 5,
    match_threshold double precision default 0,
    tenant_key text default 'demo',
    document_id uuid default null
)
returns table (
    chunk_id uuid,
    chunk_document_id uuid,
    page_start integer,
    page_end integer,
    chunk_index integer,
    text text,
    metadata jsonb,
    similarity double precision
)
language sql
stable
as $$
    with scored_chunks as (
        select
            dc.id as chunk_id,
            dc.document_id as chunk_document_id,
            dc.page_start,
            dc.page_end,
            dc.chunk_index,
            dc.text,
            dc.metadata,
            greatest(
                0::double precision,
                least(
                    1::double precision,
                    1 - (dc.embedding <=> query_embedding)
                )
            ) as similarity
        from public.document_chunks as dc
        where dc.embedding is not null
          and dc.tenant_key = match_document_chunks.tenant_key
          and (
              match_document_chunks.document_id is null
              or dc.document_id = match_document_chunks.document_id
          )
    )
    select
        scored_chunks.chunk_id,
        scored_chunks.chunk_document_id,
        scored_chunks.page_start,
        scored_chunks.page_end,
        scored_chunks.chunk_index,
        scored_chunks.text,
        scored_chunks.metadata,
        scored_chunks.similarity
    from scored_chunks
    where scored_chunks.similarity >= coalesce(match_threshold, 0)
    order by
        scored_chunks.similarity desc,
        scored_chunks.chunk_index asc,
        scored_chunks.chunk_id asc
    limit least(greatest(match_count, 1), 50);
$$;
