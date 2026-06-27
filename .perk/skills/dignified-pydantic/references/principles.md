# First principles (core concepts, validators, types)

Sections 1–22 of the dignified-pydantic guide. Pydantic v2; `ty` is the assumed type checker (no
mypy plugin — see `house-style-and-examples.md` §38).

## 1. The core idea

Pydantic is best understood as a **runtime data validation and serialization library built around
Python type annotations**. Three important parts:

**Runtime.** Python's type hints are not enforced at runtime:

```python
def greet(name: str) -> str:
    return f"Hello, {name}"

greet(123)  # Python allows this at runtime
```

A type checker might complain, but Python itself does not. Pydantic takes type annotations and uses
them as runtime instructions for validating and converting data.

**Data.** Its sweet spot is data that crosses a boundary: HTTP requests/responses, JSON files,
YAML/TOML config, environment variables, message-queue / Celery payloads, third-party API responses,
database-adjacent DTOs, LLM structured outputs, webhooks.

**Validation *and* serialization.** It is not only a way to reject bad input — it is also a way to
produce reliable output:

```python
from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str


user = User(id=123, email="matt@example.com")
as_python = user.model_dump()
as_json = user.model_dump_json()
```

Mental model:

```text
messy external data -> Pydantic model -> clean internal Python values
clean internal Python values -> Pydantic model -> serialized external data
```

Pydantic models are most valuable at the edges of a system.

## 2. Pydantic is not "just a better dataclass"

A dataclass does not enforce annotations at runtime:

```python
from dataclasses import dataclass


@dataclass
class User:
    id: int
    email: str


user = User(id="123", email=456)
print(user)  # User(id='123', email=456)
```

A Pydantic model does:

```python
from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str


user = User(id="123", email="matt@example.com")
print(user.id)        # 123
print(type(user.id))  # <class 'int'>
```

By default Pydantic often **coerces** values when it can do so safely enough. `"123"` becomes `123`.
But not every value can be converted:

```python
from pydantic import BaseModel, ValidationError


class User(BaseModel):
    id: int
    email: str


try:
    User(id="not-an-int", email="matt@example.com")
except ValidationError as exc:
    print(exc)
```

The distinction:

```text
dataclass = construct a Python object
BaseModel = validate/parse data into a Python object
```

Use dataclasses when data is already trusted and internal. Use Pydantic when data comes from outside,
leaves your system, or needs a formal contract.

## 3. The boundary principle

> Use Pydantic at boundaries, not everywhere.

A boundary is any place where your code interacts with something less trustworthy than ordinary
internal Python code.

```python
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    email: str
    display_name: str


def handle_create_user(raw_body: object) -> None:
    request = CreateUserRequest.model_validate(raw_body)
    # request.email and request.display_name are now known strings.
    create_user(email=request.email, display_name=request.display_name)
```

Once data has passed through validation, internal code does not need to keep using Pydantic models.
Convert into dataclasses, plain classes, or ORM objects:

```python
from dataclasses import dataclass
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    email: str
    display_name: str


@dataclass(frozen=True)
class NewUser:
    email: str
    display_name: str


def parse_new_user(raw_body: object) -> NewUser:
    request = CreateUserRequest.model_validate(raw_body)
    return NewUser(email=request.email, display_name=request.display_name)
```

Pydantic has runtime cost, validation/serialization/alias/default semantics, and framework
integrations — excellent at boundaries, confusing if every object in the codebase is a model. A good
default architecture:

```text
External input
    ↓
Pydantic request/input model
    ↓
Application service
    ↓
Domain dataclass / plain class / ORM object
    ↓
Pydantic response/output model
    ↓
External output
```

## 4. Constructor versus model validation

The two most important construction paths are the constructor and `model_validate`.

```python
from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str


user = User(id=123, email="matt@example.com")                 # constructor
user = User.model_validate({"id": "123", "email": "m@e.com"})  # validation
```

They often behave similarly at runtime but communicate different intent. The constructor is for
already-shaped Python values; `model_validate` is for data from outside the system.

This matters under static type checkers. A checker sees `id: int` and reasonably assumes the
constructor wants an `int`:

```python
User(id=123)    # good
User(id="123")  # type checker may object
```

Even if Pydantic accepts `"123"` at runtime, the checker is not wrong. So the idiom:

```python
user = User(id=123)                          # Good: trusted Python-shaped data
user = User.model_validate({"id": "123"})    # Good: untrusted external data
user = User(id="123")                        # Avoid: relying on constructor coercion internally
```

This is one of the most important habits for keeping Pydantic code type-checker-friendly.

## 5. Pydantic and type checkers

A type checker answers: *can this Python program be shown, statically, to use values consistently?*
Pydantic answers: *can this runtime input be converted into the shape this model requires?* The
goals overlap but are not identical.

```python
from pydantic import BaseModel


class QueryParams(BaseModel):
    limit: int


params = QueryParams(limit="10")  # Pydantic may accept; a checker may object
```

The more type-checker-friendly version says what it means:

```python
raw_query_params: object = {"limit": "10"}
params = QueryParams.model_validate(raw_query_params)
```

### With `ty`

Assume `ty` understands normal Python typing well, but do **not** assume it has Pydantic-specific
behavior that mypy gets through Pydantic's mypy plugin. Prefer portable patterns:

```python
from typing import Self
from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str

    @classmethod
    def from_raw(cls, raw: object) -> Self:
        return cls.model_validate(raw)


raw_user: object = {"id": "123", "email": "matt@example.com"}
user = User.from_raw(raw_user)
```

That gives a convenient constructor-like API while keeping the coercive parsing path explicit.

## 6. Validation is not business logic

A validator should answer: *is this value structurally valid? Can it be normalized safely? Does this
object satisfy basic input invariants?* It should usually **not** answer: *is this user allowed to do
this? Does this row exist? Should this workflow proceed?*

Good — local constraints and normalization:

```python
from pydantic import BaseModel, Field, field_validator


class CreateUserRequest(BaseModel):
    email: str
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()
```

Risky — a validator depending on database state:

```python
@field_validator("email")
@classmethod
def check_user_does_not_exist(cls, value: str) -> str:
    if user_exists_in_database(value):  # Bad: validator now depends on DB state
        raise ValueError("User already exists")
    return value
```

That belongs in the service:

```python
def create_user(raw_body: object) -> None:
    request = CreateUserRequest.model_validate(raw_body)
    if user_exists_in_database(request.email):
        raise UserAlreadyExists(request.email)
    insert_user(request.email)
```

## 7. Use `Field` for constraints and metadata

```python
from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
```

Also for descriptions/examples that flow into JSON Schema / API docs:

```python
class CreatePatientRequest(BaseModel):
    external_id: str = Field(description="Stable id in the source system.", min_length=1)
    date_of_birth: str = Field(description="YYYY-MM-DD.", examples=["1980-01-31"])
```

## 8. Prefer explicit constrained types over clever validators

If a constraint is expressible declaratively, prefer that:

```python
from pydantic import BaseModel, Field


class Score(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
```

instead of a custom `field_validator` doing the same `< 0.0 or > 1.0` check. The declarative version
is shorter, serializes to JSON Schema, and is obviously part of the data contract. Use custom
validators only when the rule isn't expressible with built-in constraints.

## 9. Field validators

Use `field_validator` when a single field needs custom validation or normalization:

```python
from pydantic import BaseModel, field_validator


class User(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("email must contain @")
        return value
```

Keep field validators small and local — they should not reach the network, DB, cache, or filesystem.

```text
Good: strip whitespace · lowercase an identifier · reject empty · normalize simple formats
Bad:  check DB uniqueness · call an API · look up a permission · decide workflow state · mutate
```

## 10. Model validators

Use `model_validator` when the rule depends on multiple fields:

```python
from datetime import date
from pydantic import BaseModel, model_validator


class DateRange(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> "DateRange":
        if self.end < self.start:
            raise ValueError("end must be on or after start")
        return self
```

"Exactly one of two fields" is the same shape:

```python
class SearchRequest(BaseModel):
    patient_id: str | None = None
    external_id: str | None = None

    @model_validator(mode="after")
    def require_exactly_one_identifier(self) -> "SearchRequest":
        provided = [self.patient_id is not None, self.external_id is not None]
        if sum(provided) != 1:
            raise ValueError("Provide exactly one of patient_id or external_id")
        return self
```

## 11. Defaults are not always validated by default

A default value is part of the contract. For dynamically generated defaults, use `default_factory`;
avoid mutable defaults:

```python
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class Job(BaseModel):
    id: UUID = Field(default_factory=uuid4)


class Batch(BaseModel):
    items: list[str] = Field(default_factory=list)  # not  items: list[str] = []
```

## 12. Optional does not mean optional

```python
class User(BaseModel):
    middle_name: str | None
```

means **the field is required; the value may be a string or `None`**. So `User(middle_name=None)` is
valid but `User()` is not. To make it omittable, give it a default:

```python
class User(BaseModel):
    middle_name: str | None = None  # now User() is valid
```

```text
T | None        = value may be None
field = default = field may be omitted
```

Those are different ideas.

## 13. Separate input models from output models

Do not reuse one model for requests, internal objects, and responses.

```python
class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(min_length=12)
    display_name: str


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    password_hash: str
    display_name: str
    created_at: datetime


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    created_at: datetime
```

The response omits `password`/`password_hash`. This separation prevents leaks and makes each
contract explicit:

```text
CreateUserRequest = what clients are allowed to send
User              = what the domain/service layer uses
UserResponse      = what clients are allowed to see
```

## 14. Use aliases at external boundaries

External APIs often use camelCase; Python uses snake_case.

```python
from pydantic import BaseModel, Field


class UserPayload(BaseModel):
    user_id: int = Field(alias="userId")
    display_name: str = Field(alias="displayName")


payload = UserPayload.model_validate({"userId": 123, "displayName": "Matt"})
print(payload.user_id)                      # 123
print(payload.model_dump(by_alias=True))    # {'userId': 123, 'displayName': 'Matt'}
```

For larger models, an alias generator is good house style for API DTOs:

```python
from pydantic import BaseModel, ConfigDict


def to_camel(snake: str) -> str:
    first, *rest = snake.split("_")
    return first + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UserPayload(ApiModel):
    user_id: int
    display_name: str
```

## 15. Decide what to do with extra fields

```python
from pydantic import BaseModel, ConfigDict


class IgnoreExtraModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown keys raise
    id: int


class FlexiblePayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
```

House style:

```text
Request models from your own clients: often extra="forbid"  (catches client mistakes early)
Third-party API responses:            often extra="ignore"  (robust when the vendor adds fields)
Exploratory ingestion pipelines:      sometimes extra="allow"
```

## 16. Strict mode: when coercion is a feature and when it is a bug

By default Pydantic is often permissive — useful for query params, form data, JSON, env vars that
arrive as strings:

```python
class User(BaseModel):
    id: int


User.model_validate({"id": "123"}).id  # 123
```

When you want runtime behavior to match the annotation exactly, use strict mode:

```python
from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int


User.model_validate({"id": "123"})  # raises ValidationError
```

Strict mode is valuable for internal DTOs, tests, and task payloads where coercion might hide a bug.

```text
External HTTP request models: allow normal coercion unless ambiguity is dangerous
Internal DTOs:                ConfigDict(strict=True)
Celery task payloads:         consider strict=True, especially if your own code produces them
Third-party API ingestion:    allow coercion, but be explicit about normalization
```

## 17. Serialization: use `model_dump`, not `dict`

```python
event.model_dump()       # Python objects
event.model_dump_json()  # JSON string
```

Exclude unset fields for PATCH semantics:

```python
class PatchUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None


patch = PatchUserRequest(display_name="Matt")
patch.model_dump()                       # {'email': None, 'display_name': 'Matt'}
patch.model_dump(exclude_unset=True)     # {'display_name': 'Matt'}
PatchUserRequest().model_dump(exclude_unset=True)  # {}
```

For PATCH handlers you often need to distinguish:

```text
field omitted       -> do not change it
field provided None -> explicitly clear it
field provided val  -> set it
```

```python
def update_user(raw_body: object) -> None:
    patch = PatchUserRequest.model_validate(raw_body)
    updates = patch.model_dump(exclude_unset=True)
    if "email" in updates:
        set_email(updates["email"])
    if "display_name" in updates:
        set_display_name(updates["display_name"])
```

## 18. Nested models

Pydantic recursively validates nested models — a big advantage over plain dataclasses:

```python
class Address(BaseModel):
    line_1: str
    city: str
    state: str
    zip_code: str


class User(BaseModel):
    id: int
    email: str
    address: Address


user = User.model_validate(
    {"id": "123", "email": "m@e.com",
     "address": {"line_1": "123 Main St", "city": "Brooklyn", "state": "NY", "zip_code": "11201"}}
)
print(user.address.city)  # Brooklyn
```

## 19. Lists, dictionaries, and collection fields

Pydantic validates collection contents and points errors at the specific index:

```python
class BatchRequest(BaseModel):
    patient_ids: list[int]


BatchRequest.model_validate({"patient_ids": ["1", "2", "3"]}).patient_ids  # [1, 2, 3]
BatchRequest.model_validate({"patient_ids": ["1", "bad", "3"]})  # error at patient_ids.1
```

Nested collections work too. Be cautious with very large nested payloads — validation is real work;
validate once at the boundary and avoid repeated revalidation in hot paths.

## 20. `TypeAdapter` for validating types that are not models

```python
from pydantic import TypeAdapter


int_list_adapter = TypeAdapter(list[int])
int_list_adapter.validate_python(["1", "2", "3"])  # [1, 2, 3]
```

Use it for a bare list / dict / union / reusable type alias when you don't need a named model. Avoid
recreating adapters in hot loops — instantiate once and reuse:

```python
PATIENT_IDS_ADAPTER = TypeAdapter(list[int])


def parse_patient_ids(raw: object) -> list[int]:
    return PATIENT_IDS_ADAPTER.validate_python(raw)
```

## 21. `Annotated` for reusable constraints

```python
from typing import Annotated
from pydantic import Field


PositiveInt = Annotated[int, Field(gt=0)]
NonEmptyString = Annotated[str, Field(min_length=1)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class CreateOrderRequest(BaseModel):
    quantity: PositiveInt
    sku: NonEmptyString
```

Be careful with defaults, aliases, and constructor signatures: checkers generally understand the
assignment form better for those:

```python
class User(BaseModel):
    name: str = Field(default="Anonymous")
    user_id: int = Field(alias="userId")
```

Prefer `Annotated` for reusable constraints; prefer assignment-form `Field(...)` when defaults or
aliases materially affect construction.

## 22. Literal, Enum, and discriminated unions

Small set of allowed values → `Literal` or `Enum`:

```python
from typing import Literal
from enum import StrEnum


class TaskStatusUpdate(BaseModel):
    status: Literal["queued", "running", "succeeded", "failed"]


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
```

Polymorphic payloads → discriminated unions:

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field


class EmailNotification(BaseModel):
    kind: Literal["email"]
    to: str
    subject: str
    body: str


class SlackNotification(BaseModel):
    kind: Literal["slack"]
    channel: str
    text: str


Notification = Annotated[EmailNotification | SlackNotification, Field(discriminator="kind")]


class SendNotificationTask(BaseModel):
    notification: Notification


task = SendNotificationTask.model_validate(
    {"notification": {"kind": "email", "to": "m@e.com", "subject": "Hi", "body": "Hi"}}
)
print(type(task.notification))  # <class 'EmailNotification'>
```

Very useful for task payloads, event streams, and API request types.
