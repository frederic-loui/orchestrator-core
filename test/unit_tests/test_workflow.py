from copy import deepcopy
from functools import reduce
from typing import List, NoReturn, Tuple
from unittest import mock
from uuid import UUID, uuid4

import pytest
from nwastdlib import const

from orchestrator.config.assignee import Assignee
from orchestrator.forms import FormPage
from orchestrator.services.processes import SYSTEM_USER
from orchestrator.types import FormGenerator, State, UUIDstr
from orchestrator.workflow import Abort, Failed, Process, ProcessStat, Skipped, Success, Suspend, Waiting
from orchestrator.workflow import _purestep as purestep
from orchestrator.workflow import (
    abort,
    abort_wf,
    begin,
    conditional,
    done,
    focussteps,
    init,
    inputstep,
    retrystep,
    runwf,
    step,
    workflow,
)
from test.unit_tests.workflows import (
    WorkflowInstanceForTests,
    assert_aborted,
    assert_complete,
    assert_failed,
    assert_state,
    assert_success,
    assert_suspended,
    assert_waiting,
    extract_error,
    resume_workflow,
    run_workflow,
)


@step("Step 1")
def step1():
    return {"steps": [1]}


@step("Step 2")
def step2(steps):
    return {"steps": [*steps, 2]}


@step("Step 3")
def step3(steps):
    return {"steps": [*steps, 3]}


@inputstep("Input Name", assignee=Assignee.SYSTEM)
def user_action():
    class Form(FormPage):
        name: str

    return Form


@retrystep("Waiting step")
def soft_fail():
    raise ValueError("Failure Message")


@step("Fail")
def fail():
    raise ValueError("Failure Message")


@workflow("Sample workflow")
def sample_workflow():
    return begin >> step1 >> step2 >> step3


def test_process_state_assertions():
    process_success = Success({"done": True})
    assert_success(process_success)
    with pytest.raises(AssertionError):
        assert_failed(process_success)

    process_failed_with_message = Failed("Failure message")

    assert_failed(process_failed_with_message)

    with pytest.raises(AssertionError):
        assert_success(process_failed_with_message)

    process_failed_with_exception = Failed(ValueError("A is not B"))

    assert_failed(process_failed_with_exception)

    with pytest.raises(ValueError):
        # When a Failed or Waiting state is encountered with an exception it will be reraised
        assert_success(process_failed_with_exception)


def create_new_process_stat(workflow, initial_state):
    return ProcessStat(
        pid=str(uuid4()), workflow=workflow, state=Success(initial_state), log=workflow.steps, current_user=SYSTEM_USER
    )


def test_exec_through_all_steps():
    log = []

    pstat = create_new_process_stat(sample_workflow, {})
    result = runwf(pstat, store(log))
    assert_success(result)
    assert_state(result, {"steps": [1, 2, 3]})


def test_store_all_steps():
    log = []

    pstat = create_new_process_stat(sample_workflow, {})
    runwf(pstat, store(log))

    assert [
        ("Step 1", Success({"steps": [1]})),
        ("Step 2", Success({"steps": [1, 2]})),
        ("Step 3", Success({"steps": [1, 2, 3]})),
    ] == log


def test_recover():
    log = []

    p = ProcessStat(
        pid=1,
        workflow=sample_workflow,
        state=Success({"steps": [4]}),
        log=sample_workflow.steps[1:],
        current_user="john.doe",
    )
    result = runwf(p, store(log))
    assert_success(result)
    assert_state(result, {"steps": [4, 2, 3]})


def test_waiting():
    wf = workflow("Workflow with soft fail")(lambda: begin >> step1 >> soft_fail >> step2)

    log = []

    pstat = create_new_process_stat(wf, {})
    result = runwf(pstat, store(log))

    assert_waiting(result)
    assert extract_error(result) == "Failure Message"

    assert [
        ("Step 1", Success({"steps": [1]})),
        ("Waiting step", Waiting({"class": "ValueError", "error": "Failure Message", "traceback": mock.ANY})),
    ] == log


def test_resume_waiting_workflow():
    hack = {"error": True}

    @retrystep("Waiting step")
    def soft_fail():
        if hack["error"]:
            raise ValueError("error")
        else:
            return {"some_key": True}

    wf = workflow("Workflow with soft fail")(lambda: begin >> step1 >> soft_fail >> step2)

    log = []

    state = Waiting({"steps": [1]})

    hack["error"] = False
    p = ProcessStat(pid=1, workflow=wf, state=state, log=wf.steps[1:], current_user="john.doe")
    result = runwf(p, logstep=store(log))

    assert_success(result)
    assert [
        ("Waiting step", Success({"steps": [1], "some_key": True})),
        ("Step 2", Success({"steps": [1, 2], "some_key": True})),
    ] == log


def test_suspend():
    wf = workflow("Workflow with user interaction")(lambda: begin >> step1 >> user_action >> step2)

    log = []

    pstat = create_new_process_stat(wf, {})
    result = runwf(pstat, store(log))

    assert_suspended(result)
    assert [("Step 1", Success({"steps": [1]})), ("Input Name", Suspend({"steps": [1]}))] == log


def test_resume_suspended_workflow():
    wf = workflow("Workflow with user interaction")(lambda: begin >> step1 >> user_action >> step2)

    log = []

    p = ProcessStat(
        pid=1,
        workflow=wf,
        state=Suspend({"steps": [1], "name": "Jane Doe"}),
        log=wf.steps[1:],
        current_user="john.doe",
    )
    result = runwf(p, logstep=store(log))

    assert_success(result)
    assert result == Success({"steps": [1, 2], "name": "Jane Doe"})
    assert [
        ("Input Name", Success({"steps": [1], "name": "Jane Doe"})),
        ("Step 2", Success({"steps": [1, 2], "name": "Jane Doe"})),
    ] == log


def test_abort():
    wf = workflow("Aborting workflow")(lambda: init >> abort)

    log = []

    pstat = create_new_process_stat(wf, {"name": "aborting"})
    result = runwf(pstat, store(log))
    assert_aborted(result)
    assert_state(result, {"name": "aborting"})


def test_failed_step():
    wf = workflow("Failing workflow")(lambda: init >> fail)

    log = []

    pstat = create_new_process_stat(wf, {"name": "init-state"})
    result = runwf(pstat, store(log))
    assert_failed(result)
    assert extract_error(result) == "Failure Message"
    assert [
        ("Start", Success({"name": "init-state"})),
        ("Fail", Failed({"class": "ValueError", "error": "Failure Message", "traceback": mock.ANY})),
    ] == log


def test_failed_log_step():
    wf = workflow("Failing workflow")(lambda: init >> done)

    def failing_store(stat, step, state):
        return Failed("Failure Message")

    pstat = create_new_process_stat(wf, {"name": "init-state"})
    result = runwf(pstat, failing_store)
    assert_failed(result)
    assert extract_error(result) == "Failure Message"


def test_exception_log_step():
    wf = workflow("Failing workflow")(lambda: init >> done)

    def failing_store(stat, step, state):
        raise Exception("Failing store error")

    with pytest.raises(Exception) as exc_info:
        pstat = create_new_process_stat(wf, {"name": "init-state"})
        runwf(pstat, failing_store)
    assert "Failing store error" in str(exc_info.value)


def test_complete():
    wf = workflow("WF")(lambda: init >> done)

    log = []
    pstat = create_new_process_stat(wf, {"name": "completion"})
    result = runwf(pstat, store(log))
    assert_complete(result)
    assert_state(result, {"name": "completion"})


def test_abort_workflow():
    wf = workflow("Workflow with user interaction")(lambda: begin >> step1 >> user_action)

    log = []
    state = {"steps": [1]}
    pstat = ProcessStat(pid=1, workflow=wf, state=Success(state), log=wf.steps[1:], current_user="john.doe")

    result = abort_wf(pstat, store(log))

    assert Abort({"steps": [1]}) == result
    assert log == [("User Aborted", Abort(state))]


def test_focus_state():
    @step("Step that works on substate")
    def substep():
        return {"result": "substep"}

    subwf = focussteps("sub")
    wf = workflow("Workflow with sub workflow that focuses on sub state")(lambda: subwf(substep) >> done)

    log = []
    pstat = create_new_process_stat(wf, {"sub": {}})
    result = runwf(pstat, store(log))
    assert_complete(result)
    assert_state(result, {"sub": {"result": "substep"}})

    # Test on empty key
    subwf = focussteps("sub")
    wf = workflow("Workflow with sub workflow that focuses on sub state")(lambda: subwf(substep) >> done)

    log = []
    pstat = create_new_process_stat(wf, {})
    result = runwf(pstat, store(log))
    assert_complete(result)
    assert_state(result, {"sub": {"result": "substep"}})


def test_error_in_focus_state():
    @step("Step that works on substate")
    def substep():
        raise ValueError("Error")

    subwf = focussteps("sub")
    wf = workflow("Workflow with sub workflow that focuses on sub state")(lambda: subwf(substep) >> done)

    log = []
    pstat = create_new_process_stat(wf, {"sub": {}})
    result = runwf(pstat, store(log))
    assert_failed(result)
    assert extract_error(result) == "Error"


def test_input_in_substate() -> None:
    @inputstep("Input Name", assignee=Assignee.SYSTEM)
    def input_action(state: State) -> FormGenerator:
        class SubForm(FormPage):
            a: int

        class TestForm(FormPage):
            sub: SubForm

        user_input = yield TestForm

        return user_input.dict()

    wf = workflow("Workflow with user interaction")(
        lambda: begin >> input_action >> purestep("process inputs")(Success)
    )

    log: List[Tuple[str, Process]] = []
    pid = uuid4()
    p = ProcessStat(
        pid=pid, workflow=wf, state=Suspend({"sub": {"a": 1, "b": 2}}), log=wf.steps[1:], current_user="john.doe"
    )
    result = runwf(p, logstep=store(log))

    assert_success(result)
    assert_state(result, {"sub": {"a": 1, "b": 2}})


def test_skip_step():
    wf = workflow("Workflow with skipped step")(lambda: init >> purestep("Skipped")(Skipped) >> done)

    log = []
    pstat = create_new_process_stat(wf, {})
    result = runwf(pstat, store(log))
    assert_complete(result)

    skipped = [x[1] for x in log if x[0] == "Skipped"]
    assert skipped[0].isskipped()


def test_conditionally_skip_a_step():
    @step("Inc N")
    def inc_n(n=0):
        return {"n": n + 1}

    limit_to_10 = conditional(lambda s: s.get("n", 0) < 10)

    incs = [limit_to_10(inc_n) for _ in range(0, 25)]
    wf = workflow("Limit the number of increments")(lambda: init >> reduce(lambda acc, e: acc >> e, incs) >> done)

    log = []

    pstat = create_new_process_stat(wf, {})
    result = runwf(pstat, store(log))
    assert_complete(result)
    # from ipdb import set_trace; set_trace()
    assert_state(result, {"n": 10})
    assert len([x for x in log if x[1].isskipped()]) == 15, "15 steps should be skipped"


def store(log):
    def _store(_, step, state):
        log.append((step.name, state))
        return state

    return _store


def test_failing_inputstep_with_form_state_params() -> None:
    @inputstep("Modify")
    def modify(subscription_id: UUIDstr) -> NoReturn:
        raise Exception("Something went wrong")

    class Form(FormPage):
        subscription_id: UUID

    @workflow("Workflow", initial_input_form=const(Form))
    def inject_args_test_workflow():
        return init >> modify >> done

    WorkflowInstanceForTests(inject_args_test_workflow, "inject_args_test_workflow")

    init_state = {"subscription_id": uuid4()}

    result, process, step_log = run_workflow("inject_args_test_workflow", init_state)
    assert_suspended(result)
    step_log_copy = deepcopy(step_log)

    with pytest.raises(Exception) as e:
        resume_workflow(process, step_log, {})

    assert "Something went wrong" in str(e.value)
    assert step_log_copy == step_log  # No steps have been logged because of the error


def test_update_wrapper():
    @step("Whatever")
    def whatever():
        """Do whatever."""
        pass

    assert whatever.__doc__ == "Do whatever."
