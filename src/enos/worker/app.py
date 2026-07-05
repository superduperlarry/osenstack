"""enos-worker role: Celery over RabbitMQ (broker) + Redis (results).

Phase 0 has one periodic job: expiring stale approvals (auto_expire_hours).
The saga/workflow machinery from the canonical stack lands with real provider
integrations in Phase 1.
"""

import asyncio

from celery import Celery

from enos.config import get_settings

settings = get_settings()

celery_app = Celery("enos", broker=settings.broker_url, backend=settings.result_backend)
celery_app.conf.beat_schedule = {
    "expire-stale-approvals": {"task": "enos.expire_approvals", "schedule": 60.0},
}
celery_app.conf.timezone = "UTC"


async def _expire_approvals_async() -> int:
    # Fresh engine per invocation: Celery tasks each run their own event loop.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from enos.services.approvals import expire_stale

    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            count = await expire_stale(session)
            await session.commit()
            return count
    finally:
        await engine.dispose()


@celery_app.task(name="enos.expire_approvals")
def expire_approvals() -> int:
    return asyncio.run(_expire_approvals_async())
