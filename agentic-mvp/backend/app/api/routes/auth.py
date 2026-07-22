from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.core.slug import unique_slug
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.user import SuperAdminBootstrap, Token, UserCreate, UserRead
from app.skills import seed_default_skill

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    tenant_name = payload.tenant_name or f"{payload.full_name}'s Workspace"
    tenant = Tenant(name=tenant_name, slug=unique_slug(db, tenant_name))
    db.add(tenant)
    db.flush()  # assigns tenant.id without committing yet

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        tenant_id=tenant.id,
        role="admin",
    )
    db.add(user)
    db.flush()  # assigns user.id, needed as the seeded skill's uploaded_by

    # Give every new tenant one starter skill so its Skills page isn't empty
    # on day one. Non-fatal by design (see app/skills/default_seed.py) —
    # never lets seeding block signup.
    seed_default_skill(db, tenant_id=tenant.id, uploaded_by=user.id)

    db.commit()
    db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token, user=UserRead.model_validate(user))


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> Token:
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token, user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
def read_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


@router.post("/bootstrap-super-admin", response_model=Token, status_code=status.HTTP_201_CREATED)
def bootstrap_super_admin(payload: SuperAdminBootstrap, db: Session = Depends(get_db)) -> Token:
    """Creates the very first Super Admin account. Deliberately unauthenticated
    (there's no super_admin yet to authenticate as) but self-disabling: once
    a single super_admin row exists anywhere in the database, this always
    404s — it is not a standing "create more super admins" endpoint. Once
    the first one exists, PUT /platform/users/{id}/role (super_admin-only)
    is how additional super admins get created, an explicit act by an
    already-trusted account rather than another anonymous bootstrap call.

    404 rather than 403 on the "already bootstrapped" path — this endpoint
    should look like it doesn't exist at all once it's served its one
    purpose, not invite repeated unauthenticated attempts against it."""
    if db.query(User).filter(User.role == "super_admin").first() is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        tenant_id=None,
        role="super_admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token, user=UserRead.model_validate(user))
