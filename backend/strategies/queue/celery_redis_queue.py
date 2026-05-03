from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init

from backend.config import settings
from backend.models import IngestionJob, IngestionStatus
from backend.strategies.base import QueueStrategy

celery_app = Celery(
    "kapa_ingestion",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["backend.tasks.ingest"],
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.worker_hijack_root_logger = False  # let our LogSetupFactory own the root logger


@worker_process_init.connect
def configure_worker_logging(**kwargs) -> None:
    """Configure our logging system in each Celery worker subprocess."""
    from backend.logging import LogSetupFactory
    LogSetupFactory.create(settings.environment).configure("celery")


class CeleryRedisQueue(QueueStrategy):
    """
    Submits ingestion jobs to Celery workers via Redis broker.

    enqueue() returns the Celery task ID so the caller can poll status
    via get_status() without knowing anything about Celery internals.
    """

    async def enqueue(self, job: IngestionJob) -> str:
        result = celery_app.send_task(
            "backend.tasks.ingest.run_ingestion_job",
            kwargs={"job_id": str(job.id)},
            task_id=str(job.id),
        )
        return result.id

    async def get_status(self, task_id: str) -> IngestionStatus:
        result = celery_app.AsyncResult(task_id)
        state_map = {
            "PENDING": IngestionStatus.PENDING,
            "STARTED": IngestionStatus.PROCESSING,
            "SUCCESS": IngestionStatus.COMPLETED,
            "FAILURE": IngestionStatus.FAILED,
        }
        return state_map.get(result.state, IngestionStatus.PENDING)
    






    
