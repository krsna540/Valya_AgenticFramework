"""MinIO — PLATFORM_ARCHITECTURE.md §3.8/§8.2, content-addressed blob
storage. Scope actually wired this session, honestly stated:

  WIRED:    a content-addressed put/get for skill package files, used
            alongside (not instead of) the existing local `dir_path`
            extraction in app/skills/package_extract.py — every uploaded
            skill file also lands in MinIO under blobs/sha256:<hash>, so
            the object store has a real, verifiable copy from day one,
            while nothing that currently reads from local disk is touched.
  DEFERRED: migrating skill *serving* off local disk onto MinIO exclusively,
            the bundle-manifest Merkle-root scheme (§8.2), and buckets for
            persona/policy/documents/artifacts — those are additive follow-
            ons, not a change to anything already working. See the gap map
            in docs/PLATFORM_ARCHITECTURE.md §17.1.

One process-wide client, same lazy-singleton shape as redis_client.py. The
`minio` SDK is synchronous, so calls here are wrapped with
`asyncio.to_thread` at call sites that are already async (skills.py's
upload route) rather than blocking the event loop.
"""
from __future__ import annotations

import hashlib
import logging

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger("agentic_mvp.minio")

_client: Minio | None = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _client


def ensure_bucket(bucket: str) -> None:
    """Idempotent bucket creation. Called from main.py's startup hook and
    safe to call repeatedly — S3Error on an already-existing bucket is
    swallowed, matching the `minio-init` one-shot container's job in
    docker-compose for buckets that need to exist before any app code runs.
    """
    client = get_minio()
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("Created MinIO bucket %s", bucket)
    except S3Error:
        logger.warning("Could not verify/create MinIO bucket %s (non-fatal — MinIO may not be up yet)", bucket, exc_info=True)


def content_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def put_blob(bucket: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
    """Store `data` content-addressed and return its digest-based key
    (§8.2's "the filename IS the SHA-256 of the contents"). A second write
    of identical bytes is a no-op cost-wise (MinIO overwrites the same key
    with itself) and always returns the same digest — that idempotency is
    the whole point of content addressing.
    """
    import io

    digest = content_digest(data)
    key = f"blobs/{digest}"
    client = get_minio()
    client.put_object(bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)
    return digest


def get_blob(bucket: str, digest: str) -> bytes:
    """Fetch by digest and re-verify on read (§3.8: "re-hash what you
    downloaded; if it doesn't match the name you asked for, something is
    wrong"). Raises ValueError on a mismatch rather than returning
    tampered/corrupted bytes silently.
    """
    client = get_minio()
    key = f"blobs/{digest}"
    response = client.get_object(bucket, key)
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    if content_digest(data) != digest:
        raise ValueError(f"MinIO blob {key} failed digest verification — refusing to return it")
    return data
