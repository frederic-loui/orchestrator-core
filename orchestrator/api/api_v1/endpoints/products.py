# Copyright 2019-2020 SURF.
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

from http import HTTPStatus
from uuid import UUID

from fastapi.param_functions import Body
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from orchestrator.api.error_handling import raise_status
from orchestrator.db import ProductBlockTable, ProductTable, db
from orchestrator.schemas import ProductSchema
from orchestrator.schemas.product import ProductPatchSchema

router = APIRouter()


@router.get(
    "/",
    response_model=list[ProductSchema],
)
def fetch(tag: str | None = None, product_type: str | None = None) -> list[ProductSchema]:
    stmt = select(ProductTable).options(
        selectinload(ProductTable.workflows),
        selectinload(ProductTable.fixed_inputs),
        selectinload(ProductTable.product_blocks).selectinload(ProductBlockTable.resource_types),
    )
    if tag:
        stmt = stmt.filter(ProductTable.__dict__["tag"] == tag)
    if product_type:
        stmt = stmt.filter(ProductTable.__dict__["product_type"] == product_type)

    return list(db.session.scalars(stmt))


@router.get(
    "/{product_id}",
    response_model=ProductSchema,
)
def product_by_id(product_id: UUID) -> ProductTable:
    product = _product_by_id(product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product id {product_id} not found")
    return product


def _product_by_id(product_id: UUID) -> ProductTable | None:
    stmt = (
        select(ProductTable)
        .options(
            joinedload(ProductTable.fixed_inputs),
            joinedload(ProductTable.product_blocks),
            joinedload(ProductTable.workflows),
        )
        .filter(ProductTable.product_id == product_id)
    )
    return db.session.scalars(stmt).unique().one_or_none()


@router.patch("/{product_id}", status_code=HTTPStatus.CREATED, response_model=ProductSchema)
async def patch_product_by_id(product_id: UUID, data: ProductPatchSchema = Body(...)) -> ProductTable:
    product = _product_by_id(product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product id {product_id} not found")

    return await _patch_product_description(data, product)


async def _patch_product_description(
    data: ProductPatchSchema,
    product: ProductTable,
) -> ProductTable:

    updated_properties = data.model_dump(exclude_unset=True)
    description = updated_properties.get("description", product.description)
    product.description = description
    db.session.commit()
    return product
