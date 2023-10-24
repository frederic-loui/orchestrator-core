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
from enum import Enum  # noqa: F401 (doctest)
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Any, Callable, Dict, Iterable, List, Literal, Optional, Tuple, Union
from uuid import UUID

import strawberry
from annotated_types import Len, MinLen
from more_itertools import first, last
from pydantic.fields import FieldInfo
from pydantic.v1.typing import is_union  # TODO find replacement
from typing_extensions import get_args, get_origin

# TODO: eventually enforce code migration for downstream users to import
# these types from pydantic_forms themselves
from pydantic_forms.types import (
    JSON,
    AcceptData,
    AcceptItemType,
    FormGenerator,
    FormGeneratorAsync,
    InputForm,
    InputFormGenerator,
    InputStepFunc,
    SimpleInputFormGenerator,
    State,
    StateInputFormGenerator,
    StateInputFormGeneratorAsync,
    StateInputStepFunc,
    StateSimpleInputFormGenerator,
    SubscriptionMapping,
    SummaryData,
    UUIDstr,
    strEnum,
)

__all__ = [
    "JSON",
    "BroadcastFunc",
    "AcceptData",
    "AcceptItemType",
    "ErrorDict",
    "ErrorState",
    "FormGenerator",
    "FormGeneratorAsync",
    "InputForm",
    "InputFormGenerator",
    "InputStepFunc",
    "SimpleInputFormGenerator",
    "State",
    "StateInputFormGenerator",
    "StateInputFormGeneratorAsync",
    "StateInputStepFunc",
    "StateSimpleInputFormGenerator",
    "StateStepFunc",
    "StepFunc",
    "SubscriptionLifecycle",
    "SubscriptionMapping",
    "SummaryData",
    "UUIDstr",
    "is_list_type",
    "is_of_type",
    "is_optional_type",
    "is_union_type",
    "get_possible_product_block_types",
    "strEnum",
]

if TYPE_CHECKING:
    from orchestrator.domain.base import ProductBlockModel

# ErrorState is either a string containing an error message, a catched Exception or a tuple containing a message and
# a HTTP status code
ErrorState = Union[str, Exception, Tuple[str, Union[int, HTTPStatus]]]
# An ErrorDict should have the following keys:
# error: str  # A message describing the error
# class: str[Optional]  # The exception class name (type)
# status_code: Optional[int]  # HTTP Status code (optional)
# traceback: Optional[str]  # A python traceback as a string formatted by nwastdlib.ex.show_ex
ErrorDict = Dict[str, Union[str, int, List[Dict[str, Any]], InputForm, None]]
StateStepFunc = Callable[[State], State]
StepFunc = Callable[..., Optional[State]]
BroadcastFunc = Callable[[UUID, Dict], None]


@strawberry.enum
class SubscriptionLifecycle(strEnum):
    INITIAL = "initial"
    ACTIVE = "active"
    MIGRATING = "migrating"
    DISABLED = "disabled"
    TERMINATED = "terminated"
    PROVISIONING = "provisioning"


# TODO #1321: old code that protected against unsafe changes in subs
# The key is the Parent subscription life cycle status. The keys are lists of safe transitions for child subscriptions.
SAFE_USED_BY_TRANSITIONS_FOR_STATUS = {
    SubscriptionLifecycle.INITIAL: [
        SubscriptionLifecycle.INITIAL,
    ],
    SubscriptionLifecycle.ACTIVE: [
        SubscriptionLifecycle.INITIAL,
        SubscriptionLifecycle.PROVISIONING,
        SubscriptionLifecycle.MIGRATING,
        SubscriptionLifecycle.ACTIVE,
        SubscriptionLifecycle.TERMINATED,
        SubscriptionLifecycle.DISABLED,
    ],
    SubscriptionLifecycle.MIGRATING: [
        SubscriptionLifecycle.INITIAL,
        SubscriptionLifecycle.MIGRATING,
        SubscriptionLifecycle.TERMINATED,
    ],
    SubscriptionLifecycle.PROVISIONING: [
        SubscriptionLifecycle.INITIAL,
        SubscriptionLifecycle.PROVISIONING,
        SubscriptionLifecycle.ACTIVE,
        SubscriptionLifecycle.TERMINATED,
    ],
    SubscriptionLifecycle.TERMINATED: [SubscriptionLifecycle.INITIAL, SubscriptionLifecycle.TERMINATED],
    SubscriptionLifecycle.DISABLED: [
        SubscriptionLifecycle.INITIAL,
        SubscriptionLifecycle.DISABLED,
        SubscriptionLifecycle.TERMINATED,
    ],
}


def is_of_type(t: Any, test_type: Any) -> bool:
    """Check if annotation type is valid for type.

    >>> is_of_type(list, list)
    True
    >>> is_of_type(List[int], List[int])
    True
    >>> is_of_type(strEnum, str)
    True
    >>> is_of_type(strEnum, Enum)
    True
    >>> is_of_type(int, str)
    False
    >>> is_of_type(Any, Any)
    True
    >>> is_of_type(Any, int)
    True
    """
    if t is Any:
        return True

    if is_union_type(test_type):
        return any(get_origin(t) is get_origin(arg) for arg in get_args(test_type))

    if (
        get_origin(t)
        and get_origin(test_type)
        and get_origin(t) is get_origin(test_type)
        and get_args(t) == get_args(test_type)
    ):
        return True

    if test_type is t:
        # Test type is a typing type instance and matches
        return True

    # Workaround for the fact that you can't call issubclass on typing types
    try:
        return issubclass(t, test_type)
    except TypeError:
        return False


# TODO #1330: Fix comparison of is_of_type(Union[str, int], Union[int, str]), it returns False but it should be True
def is_list_type(t: Any, test_type: Optional[type] = None) -> bool:
    """Check if `t` is list type.

    And optionally check if the list items are of `test_type`

    >>> is_list_type(List[int])
    True
    >>> is_list_type(List[Any], int)
    True
    >>> is_list_type(list, int)
    True
    >>> is_list_type(Optional[List[int]])
    True
    >>> is_list_type(Optional[List[int]], int)
    True
    >>> is_list_type(Annotated[Optional[List[int]], "foo"], int)
    True
    >>> is_list_type(Optional[List[int]], str)
    False
    >>> is_list_type(Annotated[Optional[List[int]], "foo"], str)
    False
    >>> is_list_type(Optional[int])
    False
    >>> is_list_type(List[Tuple[int, int]])
    True
    >>> is_list_type(List[Tuple[int, int]], int)
    False
    >>> is_list_type(List[Tuple[int, int]], Tuple[int, int])
    True
    >>> is_list_type(List[strEnum], Enum)
    True
    >>> is_list_type(int)
    False
    >>> is_list_type(Literal[1,2,3])
    False
    >>> is_list_type(List[Union[str, int]])
    True
    >>> is_list_type(List[Union[str, int]], Union[str, int])
    False
    >>> is_list_type(List[Union[str, int]], str)
    True
    >>> is_list_type(List[Union[str, int]], int)
    False
    >>> is_list_type(List[Union[str, int]], Union[int, int])
    False
    >>> from pydantic import conlist
    >>> is_list_type(conlist(int))
    True
    >>> is_list_type(Annotated[list, "foo"])
    True
    >>> is_list_type(Annotated[list, "foo"], int)
    True
    >>> is_list_type(Annotated[list[str], "foo"], int)
    False
    >>> is_list_type(Annotated[list[str], "foo"], str)
    True
    """
    t_origin, t_args = get_origin_and_args(t)
    if t_origin is None:
        return has_list_in_mro(t)

    if is_optional_type(t) or is_union_type(t):
        for arg in t_args:
            if is_list_type(arg, test_type):
                return True
    elif t_origin == Literal:
        return False  # Literal cannot contain lists see pep 586
    elif issubclass(t_origin, list):
        if test_type and t_args:
            first_arg = first(t_args)
            # To support a list with union of multiple product blocks.
            if is_union_type(first_arg) and get_args(first_arg) and not is_union_type(test_type):
                first_arg = get_args(first_arg)[0]
            return is_of_type(first_arg, test_type)
        return True

    return False


def get_origin_and_args(t: Any) -> tuple[Union[Any, None], tuple[Any]]:
    """Return the origin and args of the given type.

    When wrapped in Annotated[] this is removed.
    """
    origin, args = get_origin(t), get_args(t)
    if origin is not Annotated:
        return origin, args

    t_unwrapped = first(args)
    return get_origin(t_unwrapped), get_args(t_unwrapped)


def filter_nonetype(types_: Iterable[Any]) -> Iterable[Any]:
    def not_nonetype(type_: Any) -> bool:
        return type_ is not None.__class__

    return filter(not_nonetype, types_)


def is_optional_type(t: Any, test_type: Optional[type] = None) -> bool:
    """Check if `t` is optional type (Union[None, ...]).

    And optionally check if T is of `test_type`

    >>> is_optional_type(Optional[int])
    True
    >>> is_optional_type(Annotated[Optional[int], "foo"])
    True
    >>> is_optional_type(Annotated[int, "foo"])
    False
    >>> is_optional_type(Union[None, int])
    True
    >>> is_optional_type(Union[int, str, None])
    True
    >>> is_optional_type(Union[int, str])
    False
    >>> is_optional_type(Optional[int], int)
    True
    >>> is_optional_type(Optional[int], str)
    False
    >>> is_optional_type(Annotated[Optional[int], "foo"], int)
    True
    >>> is_optional_type(Annotated[Optional[int], "foo"], str)
    False
    >>> is_optional_type(Optional[State], int)
    False
    >>> is_optional_type(Optional[State], State)
    True
    """
    origin, args = get_origin_and_args(t)

    if is_union(origin) and None.__class__ in args:
        field_type = first(filter_nonetype(args))
        return test_type is None or is_of_type(field_type, test_type)
    return False


def is_union_type(t: Any, test_type: Optional[type] = None) -> bool:
    """Check if `t` is union type (Union[Type, AnotherType]).

    Optionally check if T is of `test_type` We cannot check for literal Nones.

    >>> is_union_type(Union[int, str])
    True
    >>> is_union_type(Annotated[Union[int, str], "foo"])
    True
    >>> is_union_type(Union[int, str], str)
    True
    >>> is_union_type(Union[int, str], bool)
    False
    >>> is_union_type(Union[int, str], Union[int, str])
    True
    >>> is_union_type(Union[int, None])
    True
    >>> is_union_type(Annotated[Union[int, None], "foo"])
    True
    >>> is_union_type(int)
    False
    """
    origin, args = get_origin_and_args(t)
    if not is_union(origin):
        return False
    if not test_type:
        return True

    if is_of_type(t, test_type):
        return True

    for arg in args:
        result = is_of_type(arg, test_type)
        if result:
            return result
    return False


def get_possible_product_block_types(
    list_field_type: Union["ProductBlockModel", Union["ProductBlockModel"]]
) -> dict[str, "ProductBlockModel"]:
    _origin, list_item_field_type_args = get_origin_and_args(list_field_type)
    if not is_union_type(list_field_type):
        return {list_field_type.name: list_field_type}

    possible_product_block_types = {}
    for list_item_field_type in filter_nonetype(list_item_field_type_args):
        if list_item_field_type.name not in possible_product_block_types:
            possible_product_block_types[list_item_field_type.name] = list_item_field_type
    return possible_product_block_types


def has_list_in_mro(type_: Any) -> bool:
    """Check if the type is (derived from) list.

    >>> has_list_in_mro(list)
    True
    >>> has_list_in_mro(List)
    True
    >>> has_list_in_mro(type("ListSubclass", (list,), {}))
    True
    >>> has_list_in_mro(tuple)
    False
    >>> has_list_in_mro(dict)
    False
    """
    try:
        return list in type_.mro()
    except AttributeError:
        return False


def yield_min_length(type_args: tuple) -> Iterable[int]:
    """Given a tuple with type args, yield min_length values found in Pydantic metadata."""
    for type_arg in type_args:
        if isinstance(type_arg, Len) or isinstance(type_arg, MinLen):
            yield type_arg.min_length
        if isinstance(type_arg, FieldInfo):
            yield from yield_min_length(type_arg.metadata)


def _get_default_type(type_: Any) -> Any:
    """Given a type, return the default type."""
    type_ = first(get_args(type_))
    if is_union_type(type_):
        # We return the last not-none type from the union (same as before in _init_instances())
        # Note that:
        # > If X is a union [..] the order [..] may be different from the order of the original arguments
        # https://docs.python.org/3.11/library/typing.html#typing.get_args
        type_ = last(filter_nonetype(get_args(type_)))
    return type_


def list_factory(type_: Any, *init_args, **init_kwargs) -> list:
    """Given a list type, create a list with optionally values.

    Args:
        type_: type of the list elements, is searched for min_length annotation
        init_args: positional args passed to created elements
        init_kwargs: keyword args passed to created elements

    >>> from annotated_types import Len
    >>> from pydantic import conlist, Field
    >>> from typing import get_args, List, Annotated
    >>> list_factory(list)
    []
    >>> list_factory(list[int])
    []
    >>> list_factory(List[int])
    []
    >>> list_factory(conlist(int))
    []
    >>> list_factory(Annotated[list[int], Field(min_length=2)], 1)
    [1, 1]
    >>> list_factory(Annotated[list, Field(min_length=2)], 1)
    []
    >>> list_factory(Annotated[list[int], Len(min_length=2)], 1)
    [1, 1]
    >>> list_factory(conlist(int, min_length=2), 1)
    [1, 1]
    >>> list_factory(conlist(Union[int, str], min_length=2), 1) in ([1, 1], ['1', '1'])
    True
    >>> list_factory(conlist(dict, min_length=1), foo="bar")
    [{'foo': 'bar'}]
    """
    from orchestrator.domain.base import ProductBlockModel

    if get_origin(type_) in (None, list):
        # List without annotations
        return []

    base_type, *type_args = get_args(type_)
    if base_type is list:
        # List with annotations but without a type
        return []

    if not has_list_in_mro(base_type):
        raise TypeError(f"Tried to initialize a list for a non-list pb field: {type_=}")

    # Look for a type_arg specifying a minimum length
    length = first(yield_min_length(type_args), None)
    # TODO when someone specifies min_length multiple times with different values, should we do something?
    if not length:
        return []

    def make_default_value(t: Any) -> Any:
        if issubclass(t, ProductBlockModel):
            return t.new(*init_args, **init_kwargs)

        # Support for non-ProductBlockModel types is mainly for doctests, we could remove it
        return t(*init_args, **init_kwargs)

    default_type = _get_default_type(base_type)
    return [make_default_value(default_type) for _ in range(length)]
