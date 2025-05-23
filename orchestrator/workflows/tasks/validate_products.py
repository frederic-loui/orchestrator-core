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

from typing import Any

from more_itertools.more import one
from more_itertools.recipes import first_true
from pydantic import ValidationError
from sqlalchemy import not_, select
from sqlalchemy.orm import joinedload

import orchestrator.workflows
from orchestrator.db import FixedInputTable, ProductTable, SubscriptionTable, WorkflowTable, db
from orchestrator.domain.base import SubscriptionModel
from orchestrator.services import products
from orchestrator.services.products import get_products
from orchestrator.services.translations import generate_translations
from orchestrator.services.workflows import get_workflow_by_name, get_workflows
from orchestrator.targets import Target
from orchestrator.utils.errors import ProcessFailureError
from orchestrator.utils.fixed_inputs import fixed_input_configuration as fi_configuration
from orchestrator.workflow import StepList, done, init, step, workflow
from pydantic_forms.types import State

# Since these errors are probably programming failures we should not throw AssertionErrors


@step("Check all workflows in database")
def check_all_workflows_are_in_db() -> State:
    all_workflows_in_db = {k.name for k in get_workflows()}
    all_workflows = {k for k in orchestrator.workflows.ALL_WORKFLOWS.keys()}  # noqa: C416
    not_in_db = all_workflows - all_workflows_in_db
    not_in_lwi = all_workflows_in_db - all_workflows
    if not_in_db or not_in_lwi:
        raise ProcessFailureError(
            "Found missing workflows in database or implementations",
            {
                "Workflows not registered in the database": list(not_in_db),
                "Workflows not registered in a `LazyWorkflowInstance`": list(not_in_lwi),
            },
        )

    return {"check_all_workflows_are_in_db": True}


@step("Check workflows for matching targets and descriptions")
def check_workflows_for_matching_targets_and_descriptions() -> State:
    workflow_assertions = []
    for key, lazy_wf in orchestrator.workflows.ALL_WORKFLOWS.items():
        wf = lazy_wf.instantiate()
        db_workflow = get_workflow_by_name(key)
        if db_workflow:
            # Test workflows might not exist in the database
            if (
                wf.target != db_workflow.target
                or wf.name != db_workflow.name
                or wf.description != db_workflow.description
            ):
                message = (
                    f"Workflow {wf.name}: {wf.target} <=> {db_workflow.target}, "
                    f"{wf.name} <=> {db_workflow.name} and {wf.description} <=> {db_workflow.description}. "
                )
                workflow_assertions.append(message)

    if workflow_assertions:
        workflow_message = "\n".join(workflow_assertions)
        raise ProcessFailureError("Workflows with none matching targets and descriptions", workflow_message)

    # Check translations
    translations = generate_translations("en-GB")["workflow"]
    workflow_assertions = []
    for key in orchestrator.workflows.ALL_WORKFLOWS:
        if key not in translations:
            workflow_assertions.append(key)

    if workflow_assertions:
        workflow_message = "\n".join(workflow_assertions)
        raise ProcessFailureError("Workflows with missing translations", workflow_message)

    return {"check_workflows_for_matching_targets_and_descriptions": True}


@step("Check that all products have at least one workflow")
def check_that_products_have_at_least_one_workflow() -> State:
    stmt = select(ProductTable).filter(not_(ProductTable.workflows.any())).with_only_columns(ProductTable.name)
    prods_without_wf = db.session.scalars(stmt).all()
    if prods_without_wf:
        raise ProcessFailureError("Found products that do not have a workflow associated with them", prods_without_wf)

    return {"check_that_products_have_at_least_one_workflow": True}


@step("Check that all products have a create, modify, terminate and validate workflow")
def check_that_products_have_create_modify_and_terminate_workflows() -> State:
    product_data = get_products(filters=[ProductTable.status == "active"])

    workflows_not_complete: list = []
    targets = ["CREATE", "TERMINATE", "MODIFY", "VALIDATE"]
    for product in product_data:
        workflows = {c.target for c in product.workflows if c.target in targets and c.name != "modify_note"}
        if len(workflows) < len(targets):
            workflows_not_complete.append(product.name)

    # Do not raise an error but only report it in the `State` to allow exceptions.
    return {
        "products_without_at_least_create_modify_terminate_validate_workflows": workflows_not_complete,
        "check_that_products_have_create_modify_and_terminate_workflows": True,
    }


@step("Check that all active products have a modify note")
def check_that_active_products_have_a_modify_note() -> State:
    modify_workflow = db.session.scalars(WorkflowTable.select().filter(WorkflowTable.name == "modify_note")).first()

    product_data = db.session.scalars(select(ProductTable).filter(ProductTable.status == "active"))
    result = [product.name for product in product_data if modify_workflow not in product.workflows]
    if result:
        raise ProcessFailureError("Found products that do not have a modify_note workflow", result)

    return {"check_that_active_products_have_a_modify_note": True}


@step("Check the DB fixed input config")
def check_db_fixed_input_config() -> State:
    fixed_input_configuration = fi_configuration()
    product_tags = products.get_tags()
    stmt = select(FixedInputTable).options(joinedload(FixedInputTable.product))
    fixed_inputs = db.session.scalars(stmt)

    data: dict = {"fixed_inputs": [], "by_tag": {}}
    errors: list = []

    for tag in product_tags:
        data["by_tag"][tag] = []
    for fi in fixed_inputs:
        fi_data: dict = first_true(
            fixed_input_configuration["fixed_inputs"], {}, lambda i: i["name"] == fi.name  # noqa: B023
        )
        if not fi_data:
            errors.append(fi)

        if fi.value not in fi_data["values"]:
            errors.append(fi)

        tag_data = {one(fi) for fi in fixed_input_configuration["by_tag"][fi.product.tag]}
        tag_data_required = {one(fi) for fi in fixed_input_configuration["by_tag"][fi.product.tag] if fi[one(fi)]}

        if not tag_data:
            errors.append(fi)

        if {fi.name for fi in fi.product.fixed_inputs} - set(tag_data):
            errors.append(fi.product.name)
        if set(tag_data_required) - {fi.name for fi in fi.product.fixed_inputs}:
            errors.append(fi.product.name)

    if errors:
        raise ProcessFailureError("Errors in fixed input config", errors)

    return {"check_db_fixed_input_config": True}


@step("Check subscription models")
def check_subscription_models() -> State:
    subscriptions = db.session.scalars(select(SubscriptionTable))
    failures: dict[str, Any] = {}
    for subscription in subscriptions:
        try:
            SubscriptionModel.from_subscription(subscription.subscription_id)
        except ValidationError as e:
            failures[str(subscription.subscription_id)] = e.errors()
        except Exception as e:
            failures[str(subscription.subscription_id)] = str(e)

    if failures:
        raise ProcessFailureError("Found subscriptions that could not be loaded", failures)

    return {"check_subscription_models": True}


@workflow("Validate products", target=Target.SYSTEM)
def task_validate_products() -> StepList:
    return (
        init
        >> check_all_workflows_are_in_db
        >> check_workflows_for_matching_targets_and_descriptions
        >> check_that_products_have_at_least_one_workflow
        >> check_that_active_products_have_a_modify_note
        >> check_db_fixed_input_config
        >> check_that_products_have_create_modify_and_terminate_workflows
        >> check_subscription_models
        >> done
    )
