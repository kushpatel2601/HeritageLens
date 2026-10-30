"""FastAPI dependencies. Everything hangs off one `Services` container on `app.state`, so tests can
build an app with their own settings, database and storage without monkey-patching globals."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database
from app.services.events import EventHub
from app.services.jobs import JobQueue
from app.services.pipeline import JobContext
from app.services.search import SearchService
from app.services.storage import Storage
from app.workers.local import LocalWorker


@dataclass(slots=True)
class Services:
    settings: Settings
    db: Database
    storage: Storage
    queue: JobQueue
    search: SearchService
    events: EventHub
    worker: LocalWorker | None = None

    @property
    def ctx(self) -> JobContext:
        return JobContext(self.settings, self.db, self.storage, self.queue)


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_session(services: ServicesDep) -> AsyncIterator[AsyncSession]:
    async with services.db.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
