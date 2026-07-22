-- =====================================================================
-- KN_Valya :: Multimodal support (Milestone 6, §6 Stages 2-3 / §9.4)
-- =====================================================================
-- `chunks.modality` distinguishes an image chunk from a text chunk so the
-- Retrieval Service's modality-balance cap (§7.3 Step 6, wired as a no-op in
-- Milestone 4) has something real to bind on. `image_sha256`/
-- `minio_image_uri`/`thumbnail_uri` let a citation for an image chunk link
-- back to the actual image (and a small thumbnail) instead of just text.
--
-- `image_captions` mirrors Milestone 4's `chunk_contextualizations` caching
-- discipline: captioning an image is an LLM call, and the SAME image
-- (content-addressed by sha256 — app/services/image_storage.py) showing up
-- again in another document, or the same document on reindex, should not
-- re-pay that cost. Keyed purely by `image_sha256` (not also by document_id
-- like the contextualization cache) because a caption genuinely only
-- depends on the image's pixels plus the surrounding text passed in at
-- caption time — see app/ingestion/activities.py's caption_images_activity
-- for the one caveat this implies (a cache hit skips re-reading
-- surrounding-text context, so a captioned-once image won't pick up a
-- different caption if it's later surrounded by very different text; judged
-- an acceptable tradeoff against the cost savings, same as Milestone 4's
-- caching judgment call).
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

ALTER TABLE chunks
    ADD COLUMN modality VARCHAR(16) NOT NULL DEFAULT 'text',
    ADD COLUMN image_sha256 VARCHAR(64),
    ADD COLUMN minio_image_uri TEXT,
    ADD COLUMN thumbnail_uri TEXT;

CREATE INDEX idx_chunks_modality ON chunks(modality);

CREATE TABLE image_captions (
    image_sha256   VARCHAR(64) PRIMARY KEY,
    caption        TEXT NOT NULL,
    ocr_text       TEXT,
    entities       JSONB NOT NULL DEFAULT '[]',
    model          VARCHAR(128) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
