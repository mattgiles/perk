# Integrations & mechanisms (settings, Celery, FastAPI, ORM, serialization, PATCH)

Sections 23–37 of the dignified-pydantic guide.

## 23. Pydantic settings

Application configuration is a natural Pydantic use case — env vars are inherently stringly-typed
external input. Use `pydantic-settings` for env-sourced settings:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    log_level: str = "INFO"
    max_workers: int = Field(default=4, ge=1)
```

Configured via `APP_DATABASE_URL=...`, `APP_LOG_LEVEL=DEBUG`, etc. Cache to avoid reparsing:

```python
from functools import lru_cache


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

## 24. Celery task payloads

Define the payload as a model; validate at both producer and worker boundaries.

```python
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class RunAbstractionTaskPayload(BaseModel):
    model_config = ConfigDict(strict=True)
    task_id: UUID
    patient_ids: list[str]
    schema_id: str
```

Producer:

```python
payload = RunAbstractionTaskPayload(task_id=uuid4(), patient_ids=["p1", "p2"], schema_id="onco-v1")
celery_app.send_task("run_abstraction", kwargs={"payload": payload.model_dump(mode="json")})
```

Worker:

```python
@celery_app.task(name="run_abstraction")
def run_abstraction(payload: object) -> None:
    parsed = RunAbstractionTaskPayload.model_validate(payload)
    run_abstraction_service(task_id=parsed.task_id, patient_ids=parsed.patient_ids,
                            schema_id=parsed.schema_id)
```

Convention:

```text
Every Celery task has exactly one Pydantic payload model.
The producer validates before sending; the worker validates after receiving.
The worker passes clean Python values into service code.
```

For tasks emitted only by your own code, strict mode is useful. Remember JSON-serialized values
(UUIDs, datetimes) cross the wire as strings and are parsed back.

## 25. FastAPI request and response models

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()


class CreateUserRequest(BaseModel):
    email: str
    display_name: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str


@app.post("/users", response_model=UserResponse)
def create_user(request: CreateUserRequest) -> UserResponse:
    user = create_user_in_database(email=request.email, display_name=request.display_name)
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)
```

Do not return arbitrary ORM objects unless you are deliberate about conversion — a response model
should be the explicit public contract. List endpoints wrap the item model:

```python
class UserListResponse(BaseModel):
    users: list[UserResponse]
```

## 26. ORM objects and `from_attributes`

To build models from objects with attributes, enable `from_attributes`:

```python
from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str


response = UserResponse.model_validate(user_orm_object)
```

Be careful: auto-exposing ORM fields couples DB schema to API schema. Explicit mapping is often
safer:

```python
def to_user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)
```

Use `from_attributes` when it reduces boilerplate without obscuring the boundary.

## 27. Avoid `model_construct` unless you know exactly why

`model_construct` creates a model **without** normal validation — bypassing the main reason to use
Pydantic:

```python
class User(BaseModel):
    id: int


User.model_construct(id="not-an-int").id  # "not-an-int" — violates the type contract
```

Use it only when the data is already validated, the performance benefit matters, the path is narrow
and well-tested, and you understand validators won't protect you. Most code should use the
constructor or `model_validate`.

## 28. Avoid Pydantic models as mutable application state

Models are mutable by default, which can make code harder to reason about. For internal state prefer
frozen dataclasses, or freeze the model:

```python
from pydantic import BaseModel, ConfigDict


class UserDTO(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    email: str
```

```text
Pydantic request/response models: usually immutable by convention
Internal domain values:           frozen dataclasses if possible
Long-lived mutable state:         plain classes with explicit methods
```

## 29. Keep model inheritance shallow

Avoid elaborate hierarchies (`BaseUser -> CreateUser -> UpdateUser -> UserInDB -> UserResponse`).
Prefer composition and explicit models. Inheritance is fine for **shared config**:

```python
from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateUserRequest(ApiModel):
    email: str
    display_name: str
```

But don't turn Pydantic inheritance into your domain model hierarchy.

## 30. PATCH models are different from create models

```python
class CreateUserRequest(BaseModel):
    email: str
    display_name: str = Field(min_length=1)


class PatchUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None
```

Create usually requires fields; patch usually allows omitted fields. Apply with `exclude_unset`:

```python
def patch_user(user_id: int, raw_body: object) -> None:
    patch = PatchUserRequest.model_validate(raw_body)
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        return
    update_user_in_database(user_id=user_id, **updates)
```

`{}` means "no changes"; `{"display_name": null}` means "explicitly clear display_name". The model
represents this distinction only if you use `exclude_unset=True` deliberately.

## 31. Error handling

Pydantic raises `ValidationError`; the structured `.errors()` list is usually more useful than the
string:

```python
from pydantic import ValidationError


try:
    User.model_validate({"id": "bad"})
except ValidationError as exc:
    print(exc.errors())
# [{"type": "int_parsing", "loc": ("id",),
#   "msg": "Input should be a valid integer, ...", "input": "bad"}]
```

For APIs, convert validation errors into client-facing responses (FastAPI does this for request
models). For workers, log the structured error and decide fail / retry / dead-letter:

```python
def handle_task(raw_payload: object) -> None:
    try:
        payload = RunAbstractionTaskPayload.model_validate(raw_payload)
    except ValidationError as exc:
        logger.exception("Invalid task payload", extra={"validation_errors": exc.errors()})
        raise
    run_service(payload)
```

## 32. JSON Schema generation

```python
schema = CreateUserRequest.model_json_schema()
```

Useful for OpenAPI, client generation, schema docs, LLM structured-output contracts, fixtures, and
contract tests. Don't confuse JSON Schema with your whole domain model — it represents your external
contract. Prefer declarative `Field` constraints + typed fields; they produce clearer schema than
arbitrary Python validators.

## 33. Computed fields

A field that appears in serialized output but is not part of input:

```python
from pydantic import BaseModel, computed_field


class Rectangle(BaseModel):
    width: float
    height: float

    @computed_field
    @property
    def area(self) -> float:
        return self.width * self.height


Rectangle(width=3, height=4).model_dump()  # {'width': 3.0, 'height': 4.0, 'area': 12.0}
```

Good for `full_name`, `area`, `status_label`. Avoid expensive operations or side effects (DB fetch,
API call, scoring pipeline).

## 34. Custom serializers

When the output format is part of the external contract:

```python
from datetime import datetime, timezone
from pydantic import BaseModel, field_serializer


class Event(BaseModel):
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()
```

Serialization should transform representation, not decide policy.

## 35. Validating function calls

```python
from pydantic import validate_call


@validate_call
def send_email(to: str, subject: str, retries: int = 3) -> None:
    print(to, subject, retries)
```

Useful at script boundaries, CLI utilities, notebooks, small integration points. Be cautious about
using it everywhere — in normal application code, static typing plus tests are usually preferable.
Use it for boundary-like functions, not ordinary internal helpers.

## 36. Dataclasses and Pydantic together

A healthy architecture uses both — Pydantic for the external contract, dataclasses for internal
domain values:

```python
from dataclasses import dataclass
from pydantic import BaseModel


class CreateTrialRequest(BaseModel):
    title: str
    phase: str
    sponsor: str


@dataclass(frozen=True)
class Trial:
    title: str
    phase: str
    sponsor: str


def parse_trial(raw: object) -> Trial:
    request = CreateTrialRequest.model_validate(raw)
    return Trial(title=request.title, phase=request.phase, sponsor=request.sponsor)
```

Dataclasses have simple static semantics; Pydantic has rich runtime behavior. Splitting them keeps
type-checker clarity high.

## 37. Recommended project conventions

```text
app/
  api/
    routes/users.py
    schemas/users.py        # Pydantic request and response models
    schemas/tasks.py
  domain/users.py           # dataclasses, plain classes, enums, business concepts
  domain/tasks.py
  services/users.py         # application logic
  workers/tasks.py          # Celery tasks; validate payloads at task boundary
  settings.py               # BaseSettings model
```

Direction of dependency stays clean:

```text
API schema validates external input.
Service receives clean values.
Domain model represents internal state.
API schema serializes external output.
```
