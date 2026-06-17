import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.postgres import close_pool
from app.services.ingestion_service import ingestion_service, parse_key_value_metadata
from app.workers.ingest_worker import ingest_manifest as ingest_manifest_task
from app.workers.ingest_worker import ingest_source as ingest_source_task


def build_source_from_args(args: argparse.Namespace) -> dict:
    metadata = parse_key_value_metadata(args.metadata)
    source = {
        "id": args.source_id,
        "title": args.title or "",
        "metadata": metadata,
    }
    if args.file:
        source["path"] = args.file
    if args.url:
        source["url"] = args.url
    if args.loader:
        source["loader"] = args.loader
    if args.source_type:
        source["source_type"] = args.source_type
    return source


async def run_now(args: argparse.Namespace):
    try:
        if args.manifest:
            return await ingestion_service.ingest_manifest(
                args.manifest,
                collection_name=args.collection,
                dry_run=args.dry_run,
            )
        return await ingestion_service.ingest_source(
            build_source_from_args(args),
            defaults={},
            collection_name=args.collection,
            dry_run=args.dry_run,
        )
    finally:
        await close_pool()


def main():
    parser = argparse.ArgumentParser(description="Ingest files, URLs, or a manifest into Qdrant.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--manifest", help="JSON manifest with multiple sources.")
    input_group.add_argument("--file", help="Path to one input file (.docx/.pdf/.txt/.xlsx).")
    input_group.add_argument("--url", help="One public URL to ingest.")
    parser.add_argument("--collection", help="Qdrant collection name. Defaults to QDRANT_COLLECTION.")
    parser.add_argument("--source-id", help="Stable source id for single-source ingest.")
    parser.add_argument("--title", help="Human-readable title for single-source ingest.")
    parser.add_argument("--source-type", help="Metadata source_type for single-source ingest.")
    parser.add_argument("--loader", choices=["xlsx_food_table"], help="Force a specialized loader.")
    parser.add_argument("--metadata", action="append", default=[], help="Extra metadata, format KEY=VALUE.")
    parser.add_argument("--dry-run", action="store_true", help="Load and chunk without uploading to Qdrant.")
    parser.add_argument("--queue", action="store_true", help="Queue a Celery ingest task instead of running inline.")
    args = parser.parse_args()

    if args.queue:
        if args.manifest:
            task = ingest_manifest_task.delay(args.manifest, args.collection, args.dry_run)
        else:
            task = ingest_source_task.delay(build_source_from_args(args), {}, args.collection, args.dry_run)
        print(json.dumps({"status": "queued", "task_id": task.id}, ensure_ascii=False))
        return

    result = asyncio.run(run_now(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
