import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.identity import Role, User, UserRole
from app.schemas.auth import RegisterRequest, TokenResponse, UserOut
from app.services.deps import get_current_user
from app.services.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        company_name=user.company_name,
        is_active=user.is_active,
        roles=[ur.role.code for ur in user.roles],
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        company_name=payload.company_name,
    )
    db.add(user)
    await db.flush()

    customer_role = await db.scalar(select(Role).where(Role.code == "customer"))
    if customer_role is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Base roles are not seeded")
    db.add(UserRole(user_id=user.id, role_id=customer_role.id))
    await db.commit()
    await db.refresh(user)
    logger.info("Registered new customer account: %s", user.email)
    return _user_out(user)


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.password_hash):
        logger.warning("Failed login attempt for %s", form_data.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        logger.warning("Login attempt for disabled account %s", user.email)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    roles = [ur.role.code for ur in user.roles]
    token = create_access_token(user.id, roles)
    logger.info("Login succeeded for %s (roles=%s)", user.email, roles)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return _user_out(user)
