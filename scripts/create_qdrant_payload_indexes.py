import asyncio
import sys
from pathlib import Path

from qdrant_client.http import models as rest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.services.retrieval_service import retrieval_service


INDEXES = [
    ("metadata.source_type", rest.PayloadSchemaType.KEYWORD),
    ("metadata.risk_level", rest.PayloadSchemaType.KEYWORD),
    ("metadata.language", rest.PayloadSchemaType.KEYWORD),
    ("metadata.source", rest.PayloadSchemaType.KEYWORD),
    ("metadata.condition", rest.PayloadSchemaType.KEYWORD),
    ("metadata.title", rest.PayloadSchemaType.TEXT),
]


async def main():
    client = retrieval_service._get_client()
    info = await client.get_collection(settings.QDRANT_COLLECTION)
    existing = set((getattr(info, "payload_schema", {}) or {}).keys())

    created = []
    skipped = []
    for field_name, field_schema in INDEXES:
        if field_name in existing:
            skipped.append(field_name)
            continue
        await client.create_payload_index(
            collection_name=settings.QDRANT_COLLECTION,
            field_name=field_name,
            field_schema=field_schema,
        )
        created.append(field_name)

    print({
        "collection": settings.QDRANT_COLLECTION,
        "created": created,
        "skipped": skipped,
    })


if __name__ == "__main__":
    asyncio.run(main())
