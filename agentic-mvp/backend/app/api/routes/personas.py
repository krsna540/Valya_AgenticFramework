import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_own_tenant, is_visible
from app.models.persona import Persona, UserPersonaMapping
from app.models.user import User
from app.schemas.persona import (
    PersonaCreate,
    PersonaRead,
    PersonaUpdate,
    UserPersonaMappingCreate,
    UserPersonaMappingRead,
)

router = APIRouter(prefix="/personas", tags=["personas"])

# NOTE on route order: the static "/mappings*" paths are declared before
# the dynamic "/{persona_id}" paths below. FastAPI/Starlette matches
# routes in registration order and "/{persona_id}" matches any single
# path segment — including the literal "mappings" — so if it were
# registered first, GET /personas/mappings would 422 (trying to parse
# "mappings" as a UUID) instead of ever reaching list_all_mappings.


def _get_tenant_persona(db: Session, current_user: User, persona_id: uuid.UUID) -> Persona:
    persona = db.get(Persona, persona_id)
    if persona is None or not is_visible(persona.tenant_id, current_user, shared_ok=False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona not found")
    return persona


@router.get("", response_model=list[PersonaRead])
def list_personas(db: Session = Depends(get_db), current_user: User = Depends(authorize("persona", "list"))) -> list[PersonaRead]:
    personas = (
        apply_own_tenant(db.query(Persona), Persona.tenant_id, current_user)
        .order_by(Persona.created_at.desc())
        .all()
    )
    return [PersonaRead.model_validate(p) for p in personas]


@router.post("", response_model=PersonaRead, status_code=status.HTTP_201_CREATED)
def create_persona(
    payload: PersonaCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("persona", "create")),
) -> PersonaRead:
    persona = Persona(
        tenant_id=current_admin.tenant_id,
        name=payload.name,
        description=payload.description,
        archetype=payload.archetype,
        base_model=payload.base_model,
        traits=payload.traits.model_dump(mode="json"),
        safety_compliance_tier=payload.traits.safety_compliance.dlp_tier,
        is_active=payload.is_active,
        created_by=current_admin.id,
    )
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return PersonaRead.model_validate(persona)


# --- User <-> Persona mappings (declared before "/{persona_id}" — see note above) ---


@router.get("/mappings/me", response_model=list[UserPersonaMappingRead])
def list_my_mappings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[UserPersonaMappingRead]:
    mappings = db.query(UserPersonaMapping).filter(UserPersonaMapping.user_id == current_user.id).all()
    return [UserPersonaMappingRead.model_validate(m) for m in mappings]


@router.get("/mappings", response_model=list[UserPersonaMappingRead])
def list_all_mappings(db: Session = Depends(get_db), current_admin: User = Depends(authorize("persona", "list"))) -> list[UserPersonaMappingRead]:
    mappings = apply_own_tenant(
        db.query(UserPersonaMapping).join(Persona, Persona.id == UserPersonaMapping.persona_id),
        Persona.tenant_id,
        current_admin,
    ).all()
    return [UserPersonaMappingRead.model_validate(m) for m in mappings]


@router.post("/mappings", response_model=UserPersonaMappingRead, status_code=status.HTTP_201_CREATED)
def create_mapping(
    payload: UserPersonaMappingCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("persona", "update")),
) -> UserPersonaMappingRead:
    _get_tenant_persona(db, current_admin, payload.persona_id)
    target_user = db.get(User, payload.user_id)
    if target_user is None or target_user.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found in this tenant")
    existing = (
        db.query(UserPersonaMapping)
        .filter(
            UserPersonaMapping.user_id == payload.user_id,
            UserPersonaMapping.persona_id == payload.persona_id,
            UserPersonaMapping.project_id == payload.project_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mapping already exists")
    mapping = UserPersonaMapping(**payload.model_dump())
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return UserPersonaMappingRead.model_validate(mapping)


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(
    mapping_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("persona", "update")),
) -> None:
    mapping = db.get(UserPersonaMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    persona = db.get(Persona, mapping.persona_id)
    if persona is None or persona.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    db.delete(mapping)
    db.commit()
    return None


# --- Single-persona CRUD (dynamic "/{persona_id}" — must stay after the
# static "/mappings*" routes above) ------------------------------------------


@router.get("/{persona_id}", response_model=PersonaRead)
def get_persona(persona_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("persona", "read"))) -> PersonaRead:
    return PersonaRead.model_validate(_get_tenant_persona(db, current_user, persona_id))


@router.put("/{persona_id}", response_model=PersonaRead)
def update_persona(
    persona_id: uuid.UUID,
    payload: PersonaUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("persona", "update")),
) -> PersonaRead:
    persona = _get_tenant_persona(db, current_admin, persona_id)
    data = payload.model_dump(exclude_unset=True)
    if "traits" in data:
        traits = payload.traits
        persona.traits = traits.model_dump(mode="json")
        persona.safety_compliance_tier = traits.safety_compliance.dlp_tier
        data.pop("traits")
    for field, value in data.items():
        setattr(persona, field, value)
    db.commit()
    db.refresh(persona)
    return PersonaRead.model_validate(persona)


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona(
    persona_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("persona", "delete")),
) -> None:
    persona = _get_tenant_persona(db, current_admin, persona_id)
    db.delete(persona)
    db.commit()
    return None
