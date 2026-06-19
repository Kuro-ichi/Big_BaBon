import asyncio

from app.db.postgres import close_pool
from app.services.ingestion_service import ingestion_service
from app.workers.celery_app import celery_app


@celery_app.task
def ingest_manifest(manifest_path: str, collection_name: str | None = None, dry_run: bool = False):
    return asyncio.run(_ingest_manifest(manifest_path, collection_name, dry_run))


@celery_app.task
def ingest_source(source: dict, defaults: dict | None = None, collection_name: str | None = None, dry_run: bool = False):
    return asyncio.run(_ingest_source(source, defaults, collection_name, dry_run))


async def _ingest_manifest(manifest_path: str, collection_name: str | None, dry_run: bool):
    try:
        return await ingestion_service.ingest_manifest(
            manifest_path,
            collection_name=collection_name,
            dry_run=dry_run,
        )
    finally:
        await close_pool()


async def _ingest_source(source: dict, defaults: dict | None, collection_name: str | None, dry_run: bool):
    try:
        return await ingestion_service.ingest_source(
            source,
            defaults=defaults or {},
            collection_name=collection_name,
            dry_run=dry_run,
        )
    finally:
        await close_pool()
