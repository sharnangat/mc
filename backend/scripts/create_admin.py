"""Creates (or resets) an administrator account.

Run with the venv's Python from the backend/ directory:
    .venv\\Scripts\\python.exe scripts\\create_admin.py [email] [password] [full_name]

Any omitted argument falls back to a default; password defaults to a
randomly generated one, printed on completion. Safe to re-run: an existing
account with the given email has its password reset and the admin role
attached if missing.
"""

import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db import SessionLocal
from app.models.identity import Role, User, UserRole
from app.services.security import hash_password


async def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@mc.local"
    password = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(12)
    full_name = sys.argv[3] if len(sys.argv) > 3 else "Administrator"

    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.code == "admin"))
        if role is None:
            raise RuntimeError("Role 'admin' is not seeded - run db/seed.sql first")

        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, full_name=full_name, password_hash=hash_password(password))
            db.add(user)
            await db.flush()
        else:
            user.password_hash = hash_password(password)

        existing_link = await db.scalar(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
        )
        if existing_link is None:
            db.add(UserRole(user_id=user.id, role_id=role.id))

        await db.commit()

    print("Admin account ready:")
    print(f"  email:    {email}")
    print(f"  password: {password}")


if __name__ == "__main__":
    asyncio.run(main())
