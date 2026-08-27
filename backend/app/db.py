from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    # pgvector's operators (<=>, etc.) were installed into the metag schema,
    # so metag must be on the search_path for unqualified operator lookup.
    connect_args={"server_settings": {"search_path": f"{settings.db_schema}, public"}},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    # Every table's timestamp columns are `timestamptz` in the DB; map bare
    # `Mapped[datetime]` fields to a tz-aware column type everywhere so a
    # tz-aware Python value never collides with an inferred naive column type.
    type_annotation_map = {datetime: DateTime(timezone=True)}


async def get_db():
    async with SessionLocal() as session:
        yield session
