from collections.abc import Generator
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytz
from sqlalchemy import delete

from orchestrator.config.assignee import Assignee
from orchestrator.db import ProcessStepTable, ProcessSubscriptionTable, ProcessTable, db
from orchestrator.workflow import done, init, inputstep, step, workflow
from pydantic_forms.core import FormPage
from pydantic_forms.types import FormGenerator, UUIDstr
from pydantic_forms.validators import Choice
from test.unit_tests.workflows import WorkflowInstanceForTests


@pytest.fixture
def test_workflow(generic_subscription_1: UUIDstr, generic_product_type_1) -> Generator:
    _, GenericProductOne = generic_product_type_1

    @step("Insert UUID in state")
    def insert_object():
        return {"subscription_id": str(uuid4()), "model": GenericProductOne.from_subscription(generic_subscription_1)}

    @step("Test that it is a string now")
    def check_object(subscription_id: Any, model: dict) -> None:
        # This is actually a test. It would be nicer to have this in a proper test but that takes too much setup that
        # already happens here. So we hijack this fixture and run this test for all tests that use this fixture
        # (which should not be an issue)
        assert isinstance(subscription_id, str)
        assert isinstance(model, dict)

    @inputstep("Modify", assignee=Assignee.CHANGES)
    def modify(subscription_id: UUIDstr) -> FormGenerator:
        class TestChoice(Choice):
            A = "A"
            B = "B"
            C = "C"

        class TestForm(FormPage):
            generic_select: TestChoice

        user_input = yield TestForm
        return user_input.model_dump()

    @workflow("Workflow")
    def workflow_for_testing_processes_py():
        return init >> insert_object >> check_object >> modify >> done

    with WorkflowInstanceForTests(workflow_for_testing_processes_py, "workflow_for_testing_processes_py") as wf:
        yield wf


@pytest.fixture
def mocked_processes(test_workflow, generic_subscription_1, generic_subscription_2):
    first_datetime = datetime(2020, 1, 14, 9, 30, tzinfo=pytz.utc)

    def mock_process(subscription_id, status, started, assignee=Assignee.SYSTEM, is_task=False):
        process_id = uuid4()
        process = ProcessTable(
            process_id=process_id,
            workflow_id=test_workflow.workflow_id,
            last_status=status,
            last_step="Modify",
            started_at=started,
            last_modified_at=started + timedelta(minutes=10),
            assignee=assignee,
            is_task=is_task,
        )

        init_step = ProcessStepTable(process_id=process_id, name="Start", status="success", state={})
        db.session.add(process)

        if subscription_id:
            insert_step = ProcessStepTable(
                process_id=process_id,
                name="Insert UUID in state",
                status="success",
                state={"subscription_id": subscription_id},
            )
            check_step = ProcessStepTable(
                process_id=process_id,
                name="Test that it is a string now",
                status="success",
                state={"subscription_id": subscription_id},
            )
            step = ProcessStepTable(
                process_id=process_id, name="Modify", status="suspend", state={"subscription_id": subscription_id}
            )

            process_subscription = ProcessSubscriptionTable(process_id=process_id, subscription_id=subscription_id)

            db.session.add(init_step)
            db.session.add(insert_step)
            db.session.add(check_step)
            db.session.add(step)
            db.session.add(process_subscription)
        db.session.commit()

        return process_id

    return [
        mock_process(generic_subscription_1, "completed", first_datetime),
        mock_process(generic_subscription_1, "suspended", first_datetime + timedelta(days=1), assignee="NOC"),
        mock_process(generic_subscription_2, "completed", first_datetime + timedelta(days=2)),
        mock_process(generic_subscription_2, "failed", first_datetime + timedelta(days=3)),
        mock_process(generic_subscription_1, "resumed", first_datetime + timedelta(days=5)),
        mock_process(generic_subscription_1, "suspended", first_datetime + timedelta(days=1), is_task=True),
        mock_process(generic_subscription_2, "completed", first_datetime + timedelta(days=2), is_task=True),
        mock_process(None, "running", first_datetime + timedelta(days=4), is_task=True),
        mock_process(None, "resumed", first_datetime + timedelta(days=5), is_task=True),
    ]


@pytest.fixture
def mocked_processes_resumeall(test_workflow, generic_subscription_1, generic_subscription_2):
    first_datetime = datetime(2020, 2, 14, 9, 30, tzinfo=pytz.utc)

    def mock_process(subscription_id, status, started, assignee=Assignee.SYSTEM, is_task=False):
        process_id = uuid4()
        process = ProcessTable(
            process_id=process_id,
            workflow_id=test_workflow.workflow_id,
            last_status=status,
            last_step="Modify",
            started_at=started,
            last_modified_at=started + timedelta(minutes=10),
            assignee=assignee,
            is_task=is_task,
        )

        init_step = ProcessStepTable(process_id=process_id, name="Start", status="success", state={})
        db.session.add(process)

        if subscription_id:
            insert_step = ProcessStepTable(
                process_id=process_id,
                name="Insert UUID in state",
                status="success",
                state={"subscription_id": subscription_id},
            )
            check_step = ProcessStepTable(
                process_id=process_id,
                name="Test that it is a string now",
                status="success",
                state={"subscription_id": subscription_id},
            )
            step = ProcessStepTable(
                process_id=process_id, name="Modify", status="suspend", state={"subscription_id": subscription_id}
            )

            process_subscription = ProcessSubscriptionTable(process_id=process_id, subscription_id=subscription_id)

            db.session.add(init_step)
            db.session.add(insert_step)
            db.session.add(check_step)
            db.session.add(step)
            db.session.add(process_subscription)
        db.session.commit()

        return process_id

    mock_processes = [
        mock_process(generic_subscription_1, "api_unavailable", first_datetime, is_task=True),
        mock_process(
            generic_subscription_1, "suspended", first_datetime + timedelta(days=1), assignee="NOC", is_task=True
        ),
        mock_process(generic_subscription_2, "completed", first_datetime + timedelta(days=2), is_task=True),
        mock_process(generic_subscription_2, "running", first_datetime + timedelta(days=2), is_task=True),
        mock_process(generic_subscription_2, "failed", first_datetime + timedelta(days=3), is_task=True),
        mock_process(generic_subscription_1, "resumed", first_datetime + timedelta(days=5), is_task=True),
        mock_process(generic_subscription_1, "inconsistent_data", first_datetime + timedelta(days=1), is_task=True),
        mock_process(generic_subscription_2, "failed", first_datetime + timedelta(days=2), is_task=False),
        mock_process(None, "running", first_datetime + timedelta(days=4), is_task=True),
        mock_process(None, "resumed", first_datetime + timedelta(days=5), is_task=True),
    ]
    yield mock_processes
    db.session.execute(delete(ProcessTable).where(ProcessTable.process_id.in_(mock_processes)))
