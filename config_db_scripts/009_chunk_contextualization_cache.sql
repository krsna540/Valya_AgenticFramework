-- =====================================================================
-- KN_Valya :: Contextualization cache (Milestone 4, §6 Stage 6 / B.1.4)
-- =====================================================================
-- The architecture note (B.1.4) says to cache contextualization LLM calls
-- by "(parent_chunk_id, chunk_hash)" so re-ingestion doesn't re-pay the LLM
-- cost for unchanged content. Taken literally that key is useless across
-- re-ingestions: `chunks.id` is a fresh uuid4() every time the chunker
-- runs (see app/ingestion/chunking.py), so the *same* parent section would
-- get a *different* parent_chunk_id on every reindex, and the cache would
-- never hit.
--
-- This table implements the same intent with a key that actually survives
-- reindexing: (document_id, parent_content_hash, child_content_hash).
-- `document_id` scopes the cache to one document (so the contextualizer's
-- other input — the document title — is implicitly held constant without
-- storing it separately); the two content hashes together stand in for
-- "this exact parent chunk, this exact child chunk" regardless of what
-- random uuid the chunker assigned them this time around.
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

CREATE TABLE chunk_contextualizations (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id           UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_content_hash    VARCHAR(64) NOT NULL,   -- sha256 of the parent chunk's display_text
    child_content_hash     VARCHAR(64) NOT NULL,   -- sha256 of the child chunk's display_text (= chunks.content_hash)
    contextual_header      TEXT NOT NULL,          -- the LLM's 50-100 token situating context
    model                  VARCHAR(128) NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, parent_content_hash, child_content_hash)
);
CREATE INDEX idx_chunk_ctx_lookup
    ON chunk_contextualizations(document_id, parent_content_hash, child_content_hash);

COMMIT;
