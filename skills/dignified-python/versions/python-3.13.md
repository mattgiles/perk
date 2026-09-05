---
---

# Type Annotations - Python 3.13

> **Modification notice:** perk corrected this file's Python 3.13 annotation-evaluation,
> forward-reference, and circular-import guidance and examples. The upstream license remains
> in `../LICENSE`.

This document captures type annotation guidance for Python 3.13. Function and class annotations
are still evaluated eagerly by default. PEP 649/749 deferred annotation evaluation arrived in
**Python 3.14**, not 3.13; see the
[Python 3.14 release notes](https://docs.python.org/3.14/whatsnew/3.14.html#pep-649-and-pep-749-deferred-evaluation-of-annotations).

## Overview

**On Python 3.13, quote forward references or use `from __future__ import annotations` when
appropriate for the project. Neither approach fixes a runtime circular import.**

All type features from previous versions (3.10-3.12) continue to work.

**Annotation evaluation in 3.13:**

- An unquoted name not yet defined can raise `NameError` while defining a function or class.
- Quote the entire annotation containing a forward reference, such as `"Node | None"`.
- `from __future__ import annotations` is still valid: it stores annotations as strings,
  rather than providing Python 3.14's deferred evaluation semantics. Follow project conventions.
- Use `TYPE_CHECKING` for imports needed only by annotations, or restructure runtime dependencies
  to break circular imports.

**Available from 3.12:**

- PEP 695 type parameter syntax: `def func[T](x: T) -> T`
- `type` statement for better type aliases

**Available from 3.11:**

- `Self` type for self-returning methods

## Universal Philosophy

**Code Clarity:**

- Types serve as inline documentation
- Make function contracts explicit
- Reduce cognitive load when reading code
- Help understand data flow without tracing through implementation

**IDE Support:**

- Enable autocomplete and intelligent suggestions
- Catch typos and attribute errors before runtime
- Support refactoring tools (rename, move, extract)
- Provide jump-to-definition for typed objects

**Bug Prevention:**

- Catch type mismatches during static analysis
- Prevent None-related errors with explicit optional types
- Document expected input/output without running code
- Enable early detection of API contract violations

## Consistency Rules

**All public APIs:**

- 🔴 MUST: Type all function parameters (except `self` and `cls`)
- 🔴 MUST: Type all function return values
- 🔴 MUST: Type all class attributes
- 🟡 SHOULD: Type module-level constants

**Internal code:**

- 🟡 SHOULD: Type function signatures where helpful for clarity
- 🟢 MAY: Type complex local variables where type isn't obvious
- 🟢 MAY: Omit types for obvious cases (e.g., `count = 0`)

## Basic Collection Types

✅ **PREFERRED** - Use built-in generic types:

```python
names: list[str] = []
mapping: dict[str, int] = {}
unique_ids: set[str] = set()
coordinates: tuple[int, int] = (0, 0)
```

❌ **WRONG** - Don't use typing module equivalents:

```python
from typing import List, Dict, Set, Tuple  # Don't do this

names: List[str] = []
```

**Why**: Built-in types are more concise, don't require imports, and are the modern Python standard
(available since 3.10).

## Union Types

✅ **PREFERRED** - Use `|` operator:

```python
def process(value: str | int) -> str:
    return str(value)


def find_config(name: str) -> dict[str, str] | dict[str, int]: ...


# Multiple unions
def parse(input: str | int | float) -> str:
    return str(input)
```

❌ **WRONG** - Don't use `typing.Union`:

```python
from typing import Union


def process(value: Union[str, int]) -> str:  # Don't do this
    ...
```

## Optional Types

✅ **PREFERRED** - Use `X | None`:

```python
def find_user(id: str) -> User | None:
    """Returns user or None if not found."""
    if id in users:
        return users[id]
    return None
```

❌ **WRONG** - Don't use `typing.Optional`:

```python
from typing import Optional


def find_user(id: str) -> Optional[User]:  # Don't do this
    ...
```

## Callable Types

✅ **PREFERRED** - Use `collections.abc.Callable`:

```python
from collections.abc import Callable

# Function that takes int, returns str
processor: Callable[[int], str] = str

# Function with no args, returns None
callback: Callable[[], None] = lambda: None

# Function with multiple args
validator: Callable[[str, int], bool] = lambda s, i: len(s) > i
```

## Interfaces: ABC vs Protocol

✅ **PREFERRED** - Use ABC for interfaces:

```python
from abc import ABC, abstractmethod


class Repository(ABC):
    @abstractmethod
    def get(self, id: str) -> User | None:
        """Get user by ID."""

    @abstractmethod
    def save(self, user: User) -> None:
        """Save user."""
```

🟡 **VALID** - Use Protocol only for structural typing:

```python
from typing import Protocol


class Drawable(Protocol):
    def draw(self) -> None: ...


def render(obj: Drawable) -> None:
    obj.draw()
```

**Dignified Python prefers ABC** because it makes inheritance and intent explicit.

## Self Type for Self-Returning Methods (3.11+)

✅ **PREFERRED** - Use Self for methods that return the instance:

```python
from typing import Self


class Builder:
    def set_name(self, name: str) -> Self:
        self.name = name
        return self

    def set_value(self, value: int) -> Self:
        self.value = value
        return self
```

## Generic Functions with PEP 695 (3.12+)

✅ **PREFERRED** - Use PEP 695 type parameter syntax:

```python
def first[T](items: list[T]) -> T | None:
    """Return first item or None if empty."""
    if not items:
        return None
    return items[0]


def identity[T](value: T) -> T:
    """Return value unchanged."""
    return value


# Multiple type parameters
def zip_dicts[K, V](keys: list[K], values: list[V]) -> dict[K, V]:
    """Create dict from separate key and value lists."""
    return dict(zip(keys, values))
```

🟡 **VALID** - TypeVar still works:

```python
from typing import TypeVar

T = TypeVar("T")


def first(items: list[T]) -> T | None:
    if not items:
        return None
    return items[0]
```

**Note**: Prefer PEP 695 syntax for simple generics. TypeVar is still needed for constraints/bounds.

## Generic Classes with PEP 695 (3.12+)

✅ **PREFERRED** - Use PEP 695 class syntax:

```python
from typing import Self


class Stack[T]:
    """A generic stack data structure."""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> Self:
        self._items.append(item)
        return self

    def pop(self) -> T | None:
        if not self._items:
            return None
        return self._items.pop()


# Usage
int_stack = Stack[int]()
int_stack.push(42).push(43)
```

🟡 **VALID** - Generic with TypeVar still works:

```python
from typing import Generic, TypeVar

T = TypeVar("T")


class Stack(Generic[T]):
    def __init__(self) -> None:
        self._items: list[T] = []

    # ... rest of implementation
```

**Note**: PEP 695 is cleaner - no imports needed, type parameter scope is local to class.

## Type Parameter Bounds (3.12+)

✅ **Use bounds with PEP 695**:

```python
class Comparable:
    def compare(self, other: object) -> int: ...


def max_value[T: Comparable](items: list[T]) -> T:
    """Get maximum value from comparable items."""
    return max(items, key=lambda x: x)
```

## Constrained TypeVars (Still Use TypeVar)

✅ **Use TypeVar for specific type constraints**:

```python
from typing import TypeVar

# Constrained to specific types - must use TypeVar
Numeric = TypeVar("Numeric", int, float)


def add(a: Numeric, b: Numeric) -> Numeric:
    return a + b
```

❌ **WRONG** - PEP 695 doesn't support constraints:

```python
# This doesn't constrain to int|float
def add[Numeric](a: Numeric, b: Numeric) -> Numeric:
    return a + b
```

## Type Aliases with type Statement (3.12+)

✅ **PREFERRED** - Use `type` statement:

```python
# Simple alias
type UserId = str
type Config = dict[str, str | int | bool]

# Generic type alias
type Result[T] = tuple[T, str | None]


def process(value: str) -> Result[int]:
    try:
        return (int(value), None)
    except ValueError as e:
        return (0, str(e))
```

🟡 **VALID** - Simple assignment still works:

```python
UserId = str  # Still valid
Config = dict[str, str | int | bool]  # Still valid
```

**Note**: `type` statement is more explicit and works better with generics.

## Forward References and Circular Imports

### Quoted forward references

✅ **CORRECT** - Quote names that are not bound when the annotation is evaluated:

```python
class Node:
    def __init__(self, value: int, parent: "Node | None" = None) -> None:
        self.value = value
        self.parent = parent
```

Quote the whole union (`"Node | None"`), not just the name (`"Node" | None`, which attempts a
runtime union between a string and `None`). The class name is not bound until its body finishes.

### Optional postponed annotations

🟡 **VALID** - If project conventions permit, the future import stores annotations as strings:

```python
from __future__ import annotations


class Node:
    def __init__(self, value: int, parent: Node | None = None) -> None:
        self.value = value
        self.parent = parent
```

This import must appear at the beginning of the module, after any module docstring. It does not
postpone ordinary expressions, base classes, or runtime imports. Runtime consumers such as
`typing.get_type_hints()` still need referenced names to be resolvable when they evaluate the
annotations.

### Type-only circular imports

When the dependency is needed only for typing, keep it under `TYPE_CHECKING` and quote the
annotation. These two modules can then be imported in either order:

#### a.py

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from b import B


class A:
    def method(self) -> "B | None":
        return None
```

#### b.py

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from a import A


class B:
    def method(self) -> "A | None":
        return None
```

`TYPE_CHECKING` is false at runtime, so these imported names are absent then. Code that evaluates
these annotations at runtime must supply the missing names (for example, to
`typing.get_type_hints()`), or use a design that makes them available without a cycle. If either
module needs the other class for actual execution, restructure the dependencies instead of
hiding a required runtime import behind `TYPE_CHECKING`.

### Recursive type aliases

The `type` statement already evaluates its alias value lazily in Python 3.12+. This is distinct
from the eager default for function and class annotations on Python 3.13:

```python
type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None
```

## Complete Examples

### Tree Structure with Quoted Forward References

```python
from typing import Self
from collections.abc import Callable


class Node[T]:
    """Tree node with forward references quoted for Python 3.13."""

    def __init__(
        self,
        value: T,
        parent: "Node[T] | None" = None,
        children: "list[Node[T]] | None" = None,
    ) -> None:
        self.value = value
        self.parent = parent
        self.children = children or []

    def add_child(self, child: "Node[T]") -> Self:
        """Add child and return self for chaining."""
        self.children.append(child)
        child.parent = self
        return self

    def find(self, predicate: Callable[[T], bool]) -> "Node[T] | None":
        """Find first node matching predicate."""
        if predicate(self.value):
            return self

        for child in self.children:
            result = child.find(predicate)
            if result:
                return result

        return None


# Quoted forward references keep this usable without a future import.
root = Node[int](1)
root.add_child(Node[int](2)).add_child(Node[int](3))
```

### Generic Repository with PEP 695

```python
from abc import ABC, abstractmethod
from typing import Self


class Entity[T]:
    """Base class for entities."""

    def __init__(self, id: T) -> None:
        self.id = id


class Repository[T](ABC):
    """Generic repository interface."""

    @abstractmethod
    def get(self, id: str) -> T | None:
        """Get entity by ID."""

    @abstractmethod
    def save(self, entity: T) -> None:
        """Save entity."""

    @abstractmethod
    def delete(self, id: str) -> bool:
        """Delete entity, return True if deleted."""


class User(Entity[str]):
    def __init__(self, id: str, name: str) -> None:
        super().__init__(id)
        self.name = name


class UserRepository(Repository[User]):
    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def get(self, id: str) -> User | None:
        if id not in self._users:
            return None
        return self._users[id]

    def save(self, entity: User) -> None:
        self._users[entity.id] = entity

    def delete(self, id: str) -> bool:
        if id not in self._users:
            return False
        del self._users[id]
        return True
```

## General Best Practices

**Prefer specificity:**

```python
# ✅ GOOD - Specific
def get_config() -> dict[str, str | int]: ...


# ❌ WRONG - Too vague
def get_config() -> dict: ...
```

**Use Union sparingly:**

```python
# ✅ GOOD - Union only when necessary
def process(value: str | int) -> str: ...


# ❌ WRONG - Too permissive
def process(value: str | int | list | dict) -> str | None | list: ...
```

**Be explicit with None:**

```python
# ✅ GOOD - Explicit optional
def find_user(id: str) -> User | None: ...


# ❌ WRONG - Implicit None return
def find_user(id: str) -> User:
    return None  # Type checker error!
```

**Avoid Any when possible:**

```python
# ✅ GOOD - Specific type
def serialize(obj: User | Config) -> str: ...


# ❌ WRONG - Defeats purpose of types
from typing import Any


def serialize(obj: Any) -> str: ...
```

## When to Use Types

**Always type:**

- Public function signatures (parameters + return)
- Class attributes (including private ones)
- Function parameters that cross module boundaries
- Return values that aren't immediately obvious

**Type when helpful:**

- Complex local variables
- Closures and nested functions
- Lambda expressions used as callbacks

**Can skip:**

- Obvious cases: `count = 0`, `name = "example"`
- Trivial private helpers
- Test fixture setup code (if types add no clarity)

## Type Checking with ty

Dignified Python uses ty for static type checking:

```bash
# Check all files
ty check

# Check specific file
ty check src/mymodule.py

# Check with specific Python version
ty check --python-version 3.13
```

**Configuration** (in `pyproject.toml`):

```toml
[tool.ty.environment]
python-version = "3.13"
```

## Anti-Patterns

**❌ Don't ignore type errors with `# type: ignore`**

```python
# ❌ WRONG - Hiding type error
result = unsafe_function()  # type: ignore

# ✅ CORRECT - Fix the type error
result: Expected = cast(Expected, unsafe_function())
```

**❌ Don't use bare Exception in type hints**

```python
# ❌ WRONG - No value from typing exception
def risky() -> str | Exception: ...


# ✅ CORRECT - Let exceptions bubble
def risky() -> str: ...  # Raises ValueError on error
```

**❌ Don't over-type simple cases**

```python
# ❌ WRONG - Obvious from context
def add_numbers(a: int, b: int) -> int:
    result: int = a + b  # Unnecessary type annotation
    return result


# ✅ CORRECT - Type only signature
def add_numbers(a: int, b: int) -> int:
    result = a + b  # Type is obvious
    return result
```

## Migration from 3.10/3.11

If migrating from Python 3.10/3.11:

1. **Keep forward references safe** - Retain quotes or an existing future import while 3.13
   remains supported; upgrading to 3.13 does not make unresolved annotation names safe.
2. **Consider upgrading to PEP 695 syntax** - Cleaner generics
3. **Use `type` statement for aliases** - More explicit than assignment
4. **Check runtime annotation consumers** - String annotations still need resolvable names when
   evaluated; neither quoted annotations nor a future import fixes runtime import cycles.

### Python 3.10/3.11

```python
from typing import TypeVar, Generic

T = TypeVar("T")


class Node(Generic[T]):
    def __init__(self, value: T, parent: "Node[T] | None" = None): ...
```

### Python 3.13

```python
class Node[T]:
    def __init__(self, value: T, parent: "Node[T] | None" = None): ...
```

The generic syntax changes, but the forward reference still needs quotes without a future
import. Do not remove that protection merely because the project now targets Python 3.13.

## What typing imports are still needed?

**Very rare:**

- `TypeVar` - Only for constrained/bounded type variables
- `Any` - Use sparingly when type truly unknown
- `Protocol` - Structural typing (prefer ABC)
- `TYPE_CHECKING` - Conditional imports to avoid circular dependencies

**Never needed:**

- `List`, `Dict`, `Set`, `Tuple` - Use built-in types
- `Union` - Use `|` operator
- `Optional` - Use `X | None`
- `Generic` - Use PEP 695 class syntax
