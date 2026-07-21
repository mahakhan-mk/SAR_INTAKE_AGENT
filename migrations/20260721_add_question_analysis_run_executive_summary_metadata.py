from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    database_schema = os.getenv("DATABASE_SCHEMA", "kpmg_sar")
    schema_name = quote_identifier(database_schema)
    table_name = f"{schema_name}.question_analysis_runs"

    engine = create_async_engine(database_url, future=True)
    statements = [
        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS executive_summary_model TEXT",
        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS executive_summary_prompt_version TEXT",
        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS executive_summary_input_hash TEXT",
        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS executive_summary_generated_at TIMESTAMPTZ",
    ]

    async with engine.begin() as connection:
        for statement in statements:
            await connection.execute(text(statement))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
