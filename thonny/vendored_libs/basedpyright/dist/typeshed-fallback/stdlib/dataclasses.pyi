import enum
import sys
import types
from _typeshed import DataclassInstance
from builtins import type as Type  # alias to avoid name clashes with fields named "type"
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Generic, Literal, Protocol, TypeVar, overload
from typing_extensions import Never, TypeAlias, TypeIs

if sys.version_info >= (3, 9):
    from types import GenericAlias

_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)

__all__ = [
    "dataclass",
    "field",
    "Field",
    "FrozenInstanceError",
    "InitVar",
    "MISSING",
    "fields",
    "asdict",
    "astuple",
    "make_dataclass",
    "replace",
    "is_dataclass",
]

if sys.version_info >= (3, 10):
    __all__ += ["KW_ONLY"]

_DataclassT = TypeVar("_DataclassT", bound=DataclassInstance)

# define _MISSING_TYPE as an enum within the type stubs,
# even though that is not really its type at runtime
# this allows us to use Literal[_MISSING_TYPE.MISSING]
# for background, see:
#   https://github.com/python/typeshed/pull/5900#issuecomment-895513797
class _MISSING_TYPE(enum.Enum):
    MISSING = enum.auto()

MISSING = _MISSING_TYPE.MISSING

if sys.version_info >= (3, 10):
    class KW_ONLY: ...

@overload
def asdict(obj: DataclassInstance) -> dict[str, Any]: ...
@overload
def asdict(obj: DataclassInstance, *, dict_factory: Callable[[list[tuple[str, Any]]], _T]) -> _T: ...
@overload
def astuple(obj: DataclassInstance) -> tuple[Any, ...]: ...
@overload
def astuple(obj: DataclassInstance, *, tuple_factory: Callable[[list[Any]], _T]) -> _T: ...
@overload
def dataclass(cls: None, /) -> Callable[[type[_T]], type[_T]]: ...
@overload
def dataclass(cls: type[_T], /) -> type[_T]: ...

if sys.version_info >= (3, 11):
    @overload
    def dataclass(
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        match_args: bool = True,
        kw_only: bool = False,
        slots: bool = False,
        weakref_slot: bool = False,
    ) -> Callable[[type[_T]], type[_T]]: ...

elif sys.version_info >= (3, 10):
    @overload
    def dataclass(
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        match_args: bool = True,
        kw_only: bool = False,
        slots: bool = False,
    ) -> Callable[[type[_T]], type[_T]]: ...

else:
    @overload
    def dataclass(
        *,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
    ) -> Callable[[type[_T]], type[_T]]: ...

# See https://github.com/python/mypy/issues/10750
class _DefaultFactory(Protocol[_T_co]):
    def __call__(self) -> _T_co: ...

class Field(Generic[_T]):
    name: str
    type: Type[_T] | str | Any
    default: _T | Literal[_MISSING_TYPE.MISSING]
    default_factory: _DefaultFactory[_T] | Literal[_MISSING_TYPE.MISSING]
    repr: bool
    hash: bool | None
    init: bool
    compare: bool
    metadata: types.MappingProxyType[Any, Any]
    if sys.version_info >= (3, 10):
        kw_only: bool | Literal[_MISSING_TYPE.MISSING]
        def __init__(
            self,
            default: _T,
            default_factory: Callable[[], _T],
            init: bool,
            repr: bool,
            hash: bool | None,
            compare: bool,
            metadata: Mapping[Any, Any],
            kw_only: bool,
        ) -> None: ...
    else:
        def __init__(
            self,
            default: _T,
            default_factory: Callable[[], _T],
            init: bool,
            repr: bool,
            hash: bool | None,
            compare: bool,
            metadata: Mapping[Any, Any],
        ) -> None: ...

    def __set_name__(self, owner: Type[Any], name: str) -> None: ...
    if sys.version_info >= (3, 9):
        def __class_getitem__(cls, item: Any, /) -> GenericAlias:
            """
            Represent a PEP 585 generic type

            E.g. for t = list[int], t.__origin__ is list and t.__args__ is (int,).
            """
            ...

# NOTE: Actual return type is 'Field[_T]', but we want to help type checkers
# to understand the magic that happens at runtime.
if sys.version_info >= (3, 10):
    @overload  # `default` and `default_factory` are optional and mutually exclusive.
    def field(
        *,
        default: _T,
        init: bool = True,
        repr: bool = True,
        hash: bool | None = None,
        compare: bool = True,
        metadata: Mapping[Any, Any] | None = None,
        kw_only: bool = ...,
    ) -> _T: ...
    @overload
    def field(
        *,
        default_factory: Callable[[], _T],
        init: bool = True,
        repr: bool = True,
        hash: bool | None = None,
        compare: bool = True,
        metadata: Mapping[Any, Any] | None = None,
        kw_only: bool = ...,
    ) -> _T: ...
    @overload
    def field(
        *,
        init: bool = True,
        repr: bool = True,
        hash: bool | None = None,
        compare: bool = True,
        metadata: Mapping[Any, Any] | None = None,
        kw_only: bool = ...,
    ) -> Any: ...

else:
    @overload  # `default` and `default_factory` are optional and mutually exclusive.
    def field(
        *,
        default: _T,
        init: bool = True,
        repr: bool = True,
        hash: bool | None = None,
        compare: bool = True,
        metadata: Mapping[Any, Any] | None = None,
    ) -> _T: ...
    @overload
    def field(
        *,
        default_factory: Callable[[], _T],
        init: bool = True,
        repr: bool = True,
        hash: bool | None = None,
        compare: bool = True,
        metadata: Mapping[Any, Any] | None = None,
    ) -> _T: ...
    @overload
    def field(
        *,
        init: bool = True,
        repr: bool = True,
        hash: bool | None = None,
        compare: bool = True,
        metadata: Mapping[Any, Any] | None = None,
    ) -> Any: ...

def fields(class_or_instance: DataclassInstance | type[DataclassInstance]) -> tuple[Field[Any], ...]: ...

# HACK: `obj: Never` typing matches if object argument is using `Any` type.
@overload
def is_dataclass(obj: Never) -> TypeIs[DataclassInstance | type[DataclassInstance]]: ...  # type: ignore[narrowed-type-not-subtype]  # pyright: ignore[reportGeneralTypeIssues]
@overload
def is_dataclass(obj: type) -> TypeIs[type[DataclassInstance]]: ...
@overload
def is_dataclass(obj: object) -> TypeIs[DataclassInstance | type[DataclassInstance]]: ...

class FrozenInstanceError(AttributeError): ...

if sys.version_info >= (3, 9):
    _InitVarMeta: TypeAlias = type
else:
    class _InitVarMeta(type):
        # Not used, instead `InitVar.__class_getitem__` is called.
        # pyright (not unreasonably) thinks this is an invalid use of InitVar.
        def __getitem__(self, params: Any) -> InitVar[Any]: ...  # pyright: ignore[reportInvalidTypeForm]

class InitVar(Generic[_T], metaclass=_InitVarMeta):
    type: Type[_T]
    def __init__(self, type: Type[_T]) -> None: ...
    if sys.version_info >= (3, 9):
        @overload
        def __class_getitem__(cls, type: Type[_T]) -> InitVar[_T]: ...  # pyright: ignore[reportInvalidTypeForm]
        @overload
        def __class_getitem__(cls, type: Any) -> InitVar[Any]: ...  # pyright: ignore[reportInvalidTypeForm]

if sys.version_info >= (3, 12):
    def make_dataclass(
        cls_name: str,
        fields: Iterable[str | tuple[str, Any] | tuple[str, Any, Any]],
        *,
        bases: tuple[type, ...] = (),
        namespace: dict[str, Any] | None = None,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        match_args: bool = True,
        kw_only: bool = False,
        slots: bool = False,
        weakref_slot: bool = False,
        module: str | None = None,
    ) -> type: ...

elif sys.version_info >= (3, 11):
    def make_dataclass(
        cls_name: str,
        fields: Iterable[str | tuple[str, Any] | tuple[str, Any, Any]],
        *,
        bases: tuple[type, ...] = (),
        namespace: dict[str, Any] | None = None,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        match_args: bool = True,
        kw_only: bool = False,
        slots: bool = False,
        weakref_slot: bool = False,
    ) -> type: ...

elif sys.version_info >= (3, 10):
    def make_dataclass(
        cls_name: str,
        fields: Iterable[str | tuple[str, Any] | tuple[str, Any, Any]],
        *,
        bases: tuple[type, ...] = (),
        namespace: dict[str, Any] | None = None,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
        match_args: bool = True,
        kw_only: bool = False,
        slots: bool = False,
    ) -> type: ...

else:
    def make_dataclass(
        cls_name: str,
        fields: Iterable[str | tuple[str, Any] | tuple[str, Any, Any]],
        *,
        bases: tuple[type, ...] = (),
        namespace: dict[str, Any] | None = None,
        init: bool = True,
        repr: bool = True,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool = False,
    ) -> type: ...

def replace(obj: _DataclassT, /, **changes: Any) -> _DataclassT: ...