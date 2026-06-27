# House style, anti-patterns, worked examples, checklist

Sections 38–48 of the dignified-pydantic guide.

## 38. House style for `ty`

If using `ty`, optimize for ordinary Python typing — `ty` does not support mypy plugins, so do not
rely on Pydantic-plugin magic.

```text
1. Constructors should receive values of the declared Python types.
2. External data should enter through model_validate.
3. Avoid relying on constructor coercion.
4. Prefer explicit return types.
5. Prefer dataclasses/plain classes for internal domain objects.
6. Prefer Pydantic models for external contracts.
7. Avoid plugin-dependent magic.
```

Good:

```python
from pydantic import BaseModel


class UserPayload(BaseModel):
    id: int
    email: str


def parse_user_payload(raw: object) -> UserPayload:
    return UserPayload.model_validate(raw)


def create_payload() -> UserPayload:
    return UserPayload(id=123, email="matt@example.com")
```

Avoid (passes at runtime, not type-checker-friendly):

```python
def create_payload() -> UserPayload:
    return UserPayload(id="123", email="matt@example.com")
```

If you need coercion, make it explicit via `model_validate`.

> **The single strongest rule.** Constructor calls should type-check **without** relying on Pydantic
> coercion; coercion should enter through `model_validate`. That one convention prevents a lot of
> weirdness.

## 39. Good model names

Model names should say **which boundary** they belong to.

```text
Good:      CreateUserRequest · PatchUserRequest · UserResponse · RunAbstractionTaskPayload
           · TrialMatchEvent · Settings · ThirdPartyPatientPayload
Less good: UserModel · UserSchema · UserData · UserBase
```

`UserModel` doesn't say whether it is input, output, database-adjacent, internal, or external.
Prefer names that encode role (`CreateUserRequest`, `UserResponse`, `UserRecord`,
`UserTaskPayload`).

## 40. Anti-patterns

### Anti-pattern 1 — One model for everything

```python
# Bad: create request + update request + DB object + response, all at once
class User(BaseModel):
    id: int | None = None
    email: str | None = None
    password: str | None = None
    password_hash: str | None = None
    created_at: datetime | None = None
    is_admin: bool | None = None
```

```python
# Better: separate contracts
class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: str


class PatchUserRequest(BaseModel):
    email: str | None = None
    display_name: str | None = None


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    created_at: datetime
```

### Anti-pattern 2 — Business logic in validators

```python
# Bad
class CreateOrderRequest(BaseModel):
    sku: str

    @field_validator("sku")
    @classmethod
    def ensure_inventory_exists(cls, value: str) -> str:
        if get_inventory_count(value) <= 0:
            raise ValueError("out of stock")
        return value
```

```python
# Better
class CreateOrderRequest(BaseModel):
    sku: str


def create_order(raw: object) -> None:
    request = CreateOrderRequest.model_validate(raw)
    if get_inventory_count(request.sku) <= 0:
        raise OutOfStock(request.sku)
    place_order(request.sku)
```

### Anti-pattern 3 — Revalidating constantly

```python
# Bad: re-validate at every step
def process_items(raw_items: list[object]) -> None:
    for raw_item in raw_items:
        item = Item.model_validate(raw_item)
        step_one(item.model_dump())
        step_two(Item.model_validate(item.model_dump()))
```

```python
# Better: validate once at the boundary
def process_items(raw_items: list[object]) -> None:
    items = [Item.model_validate(raw_item) for raw_item in raw_items]
    for item in items:
        step_one(item)
        step_two(item)
        step_three(item)
```

### Anti-pattern 4 — Hiding coercion from the type checker

```python
user = User(id="123")                      # Bad
user = User.model_validate({"id": "123"})  # Better
```

### Anti-pattern 5 — Pydantic as a substitute for thinking about contracts

```python
class Blob(BaseModel):       # Bad
    data: dict


class PatientPayload(BaseModel):  # Better — precise contract
    external_id: str
    date_of_birth: date | None = None
    diagnoses: list[str] = Field(default_factory=list)
```

The point is not merely to have a model — it's to make the contract precise.

## 41. Complete example: API request → domain → response

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------- API input ----------
class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


# ---------- Domain ----------
@dataclass(frozen=True)
class Project:
    id: UUID
    name: str
    description: str | None
    created_at: datetime


# ---------- API output ----------
class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime


# ---------- Service ----------
def create_project_service(name: str, description: str | None) -> Project:
    return Project(id=uuid4(), name=name, description=description,
                   created_at=datetime.now(timezone.utc))


# ---------- Boundary orchestration ----------
def handle_create_project(raw_body: object) -> ProjectResponse:
    request = CreateProjectRequest.model_validate(raw_body)
    project = create_project_service(name=request.name, description=request.description)
    return ProjectResponse(id=project.id, name=project.name,
                           description=project.description, created_at=project.created_at)
```

The whole philosophy in one flow: request validates input, `Project` is the internal value,
`ProjectResponse` defines output, the service does logic with normal typed Python values.

## 42. Complete example: Celery task payload

```python
from dataclasses import dataclass
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field


class RunExtractionTaskPayload(BaseModel):
    model_config = ConfigDict(strict=True)
    task_id: UUID
    document_ids: list[str] = Field(min_length=1)
    schema_name: str = Field(min_length=1)


@dataclass(frozen=True)
class RunExtractionCommand:
    task_id: UUID
    document_ids: tuple[str, ...]
    schema_name: str


def parse_run_extraction_command(raw_payload: object) -> RunExtractionCommand:
    payload = RunExtractionTaskPayload.model_validate(raw_payload)
    return RunExtractionCommand(task_id=payload.task_id,
                                document_ids=tuple(payload.document_ids),
                                schema_name=payload.schema_name)


def enqueue_run_extraction(document_ids: list[str], schema_name: str) -> None:
    payload = RunExtractionTaskPayload(task_id=uuid4(), document_ids=document_ids,
                                       schema_name=schema_name)
    send_task("run_extraction", kwargs={"payload": payload.model_dump(mode="json")})


def run_extraction_task(payload: object) -> None:
    command = parse_run_extraction_command(payload)
    run_extraction_service(command)
```

## 43. Complete example: third-party API response

Ignore extra fields because vendors add fields over time; convert to your internal representation:

```python
from datetime import date
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field


class VendorPatient(BaseModel):
    model_config = ConfigDict(extra="ignore")
    external_id: str = Field(alias="externalId")
    birth_date: date | None = Field(default=None, alias="birthDate")
    sex: str | None = None


@dataclass(frozen=True)
class Patient:
    external_id: str
    birth_date: date | None
    sex: str | None


def parse_vendor_patient(raw: object) -> Patient:
    vendor_patient = VendorPatient.model_validate(raw)
    return Patient(external_id=vendor_patient.external_id,
                   birth_date=vendor_patient.birth_date, sex=vendor_patient.sex)
```

This avoids coupling your internal domain to the vendor's JSON shape.

## 44. Complete example: PATCH semantics

```python
from pydantic import BaseModel, ConfigDict, Field


class PatchProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    archived: bool | None = None


def patch_project(project_id: str, raw_body: object) -> None:
    patch = PatchProjectRequest.model_validate(raw_body)
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        return
    if "name" in updates:
        update_project_name(project_id, updates["name"])
    if "description" in updates:
        update_project_description(project_id, updates["description"])
    if "archived" in updates:
        update_project_archived(project_id, updates["archived"])
```

`model_validate({})` → no fields changed; `model_validate({"description": None})` → description
explicitly cleared. That distinction is critical in real APIs.

## 45. Testing Pydantic models

Test the validation behavior that matters to your contract — not every Pydantic feature.

```python
import pytest
from pydantic import ValidationError


def test_create_project_requires_non_empty_name() -> None:
    with pytest.raises(ValidationError):
        CreateProjectRequest.model_validate({"name": ""})


def test_create_project_strips_name() -> None:
    request = CreateProjectRequest.model_validate({"name": "  Alpha  "})
    assert request.name == "Alpha"


def test_create_project_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CreateProjectRequest.model_validate({"name": "Alpha", "unexpected": "value"})
```

Worth testing: required fields · important constraints · normalization · aliases · extra-field
policy · PATCH omitted-vs-null · discriminated-union dispatch.

> Under a strict checker like `ty`, exercise validation through `Model.model_validate({...})`, **not**
> deliberately-invalid typed kwargs — `model_validate` takes `Any`, so the negative test stays
> ty-clean and matches the real boundary shape.

## 46. A practical decision checklist

When creating a new model, ask:

```text
1.  What boundary does this model represent?
2.  Is this input, output, config, task payload, or third-party data?
3.  Should extra fields be forbidden, ignored, or allowed?
4.  Should coercion be allowed, or should the model be strict?
5.  Are aliases needed for external names?
6.  Are defaults semantically correct?
7.  Are optional fields truly optional, or merely nullable?
8.  Should this be separate from the domain object?
9.  Is any validator doing business logic that belongs elsewhere?
10. How will this model serialize?
```

If you cannot answer question 1, the model may not need to exist.

## 47. Suggested house rules

```text
1.  Use Pydantic models at I/O boundaries.
2.  Use dataclasses or plain classes for internal domain objects.
3.  Use separate request, response, task, config, and vendor models.
4.  Use model_validate for untrusted/external data.
5.  Use constructors for trusted Python-shaped values.
6.  Avoid relying on constructor coercion.
7.  Use Field for declarative constraints.
8.  Use field validators for local field normalization.
9.  Use model validators for cross-field invariants.
10. Keep validators free of database/network/business policy logic.
11. Use extra="forbid" for your own API inputs unless you have a reason not to.
12. Use extra="ignore" for third-party API responses unless you need to detect vendor changes.
13. Use strict=True for internal DTOs and task payloads when coercion would hide bugs.
14. Use model_dump and model_dump_json for serialization.
15. Use exclude_unset=True for PATCH semantics.
16. Use TypeAdapter for validating bare types.
17. Keep inheritance shallow.
18. Prefer explicit mapping at boundaries over magical coupling.
19. Test important validation behavior.
20. With ty, write Pydantic code that remains understandable to ordinary static typing.
```

## 48. The shortest possible summary

Use Pydantic where data crosses a trust boundary. Do not use it as your entire object model.

```text
Prefer:                              Avoid:
external raw data                    everything is a BaseModel
  -> Pydantic validation model       validators contain business logic
  -> clean typed Python values       constructors rely on coercion
  -> domain/service logic            one model is used for input, DB, domain, and output
  -> Pydantic response model
  -> serialized external data
```

The best Pydantic code is boring: explicit models, clear boundaries, simple validators, predictable
serialization, and ordinary Python types inside the system.

## Sources

- Pydantic v2 docs (validation/serialization APIs, strictness, conversion table) —
  https://docs.pydantic.dev/latest/
- Astral `ty` — does not support mypy plugins (may add direct library support such as Pydantic
  later) — https://docs.astral.sh/ty/
