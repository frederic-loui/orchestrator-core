# Copyright 2019-2020 SURF, GÉANT.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from functools import partial
from uuid import UUID

import structlog
from celery import Celery, Task
from celery.app.control import Inspect
from celery.utils.log import get_task_logger
from kombu.serialization import registry

from orchestrator.schemas.engine_settings import WorkerStatus
from orchestrator.services.executors.threadpool import thread_resume_process, thread_start_process
from orchestrator.services.processes import _get_process, ensure_correct_process_status, load_process
from orchestrator.types import BroadcastFunc
from orchestrator.utils.json import json_dumps, json_loads
from orchestrator.workflow import ProcessStatus

logger = get_task_logger(__name__)

local_logger = structlog.get_logger(__name__)

_celery: Celery | None = None

NEW_TASK = "tasks.new_task"
NEW_WORKFLOW = "tasks.new_workflow"
RESUME_TASK = "tasks.resume_task"
RESUME_WORKFLOW = "tasks.resume_workflow"


def get_celery_task(task_name: str) -> Task:
    if _celery:
        return _celery.signature(task_name)
    raise AssertionError("Celery has not been initialised yet")


def register_custom_serializer() -> None:
    # orchestrator specific serializer to correctly handle more complex classes
    registry.register("orchestrator-json", json_dumps, json_loads, "application/json", "utf-8")


def initialise_celery(celery: Celery) -> None:  # noqa: C901
    global _celery
    if _celery:
        raise AssertionError("You can only initialise Celery once")
    _celery = celery

    # Different routes/queues so we can assign them priorities
    celery.conf.task_routes = {
        NEW_TASK: {"queue": "new_tasks"},
        NEW_WORKFLOW: {"queue": "new_workflows"},
        RESUME_TASK: {"queue": "resume_tasks"},
        RESUME_WORKFLOW: {"queue": "resume_workflows"},
    }

    register_custom_serializer()

    process_broadcast_fn: BroadcastFunc | None = getattr(celery, "process_broadcast_fn", None)

    def start_process(process_id: UUID, user: str) -> UUID | None:
        try:
            process = _get_process(process_id)
            pstat = load_process(process)
            ensure_correct_process_status(process_id, ProcessStatus.CREATED)
            thread_start_process(pstat, user)

        except Exception as exc:
            local_logger.error("Worker failed to execute workflow", process_id=process_id, details=str(exc))
            return None
        else:
            return process_id

    def resume_process(process_id: UUID, user: str) -> UUID | None:
        try:
            process = _get_process(process_id)
            ensure_correct_process_status(process_id, ProcessStatus.RESUMED)
            thread_resume_process(process, user=user, broadcast_func=process_broadcast_fn)
        except Exception as exc:
            local_logger.error("Worker failed to resume workflow", process_id=process_id, details=str(exc))
            return None
        else:
            return process_id

    celery_task = partial(celery.task, log=local_logger, serializer="orchestrator-json")

    @celery_task(name=NEW_TASK)  # type: ignore
    def new_task(process_id: UUID, user: str) -> UUID | None:
        local_logger.info("Start task", process_id=process_id)
        return start_process(process_id, user=user)

    @celery_task(name=NEW_WORKFLOW)  # type: ignore
    def new_workflow(process_id: UUID, user: str) -> UUID | None:
        local_logger.info("Start workflow", process_id=process_id)
        return start_process(process_id, user=user)

    @celery_task(name=RESUME_TASK)  # type: ignore
    def resume_task(process_id: UUID, user: str) -> UUID | None:
        local_logger.info("Resume task", process_id=process_id)
        return resume_process(process_id, user=user)

    @celery_task(name=RESUME_WORKFLOW)  # type: ignore
    def resume_workflow(process_id: UUID, user: str) -> UUID | None:
        local_logger.info("Resume workflow", process_id=process_id)
        return resume_process(process_id, user=user)


class CeleryJobWorkerStatus(WorkerStatus):
    def __init__(self) -> None:
        super().__init__(executor_type="celery")
        if not _celery:
            logger.error("Can't create CeleryJobStatistics. Celery is not initialised.")
            return

        inspection: Inspect = _celery.control.inspect()
        stats = inspection.stats()
        self.number_of_workers_online = len(stats)

        def sum_items(d: dict) -> int:
            return sum(len(lines) for _, lines in d.items()) if d else 0

        self.number_of_queued_jobs = sum_items(inspection.scheduled()) + sum_items(inspection.reserved())
        self.number_of_running_jobs = sum(len(tasks) for w, tasks in inspection.active().items())
