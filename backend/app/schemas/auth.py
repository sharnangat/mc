import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: str | None = None
    company_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # str, not EmailStr: addresses on reserved domains (vidyanand@mc.local) are
    # stored and used to log in, but EmailStr rejects them and /auth/me then fails.
    email: str
    full_name: str
    phone: str | None
    company_name: str | None
    is_active: bool
    roles: list[str] = []
