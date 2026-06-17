import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.postgres import close_pool, get_pool


async def main():
    schema_path = PROJECT_ROOT / "app" / "db" / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql)
    await close_pool()
    print({"status": "success", "schema": str(schema_path)})


if __name__ == "__main__":
    asyncio.run(main())
