from datetime import datetime, timedelta

import jwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import License, User
from app.utils import ALGORITHM, SECRET_KEY, create_access_token, hash_password, verify_password

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LicenseActivateRequest(BaseModel):
    license_key: str
    token: str


def ok(data):
    return {"status": "ok", "data": data}


def error(message):
    return {"status": "error", "message": message}


@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing_user = (
        db.query(User)
        .filter((User.username == payload.username) | (User.email == payload.email))
        .first()
    )
    if existing_user:
        return error("username or email already exists")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return ok(
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
        }
    )


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        return error("invalid username or password")

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return ok({"token": token, "token_type": "bearer"})


@router.post("/license/activate")
def activate_license(payload: LicenseActivateRequest, db: Session = Depends(get_db)):
    try:
        token_data = jwt.decode(payload.token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(token_data.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        return error("invalid or expired token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return error("user not found")

    license_record = (
        db.query(License).filter(License.license_key == payload.license_key).first()
    )
    if not license_record:
        return error("license key not found")

    if license_record.status != "unused" and license_record.activated_by == user.id:
        return ok(
            {
                "license_key": license_record.license_key,
                "status": license_record.status,
                "activated_by": license_record.activated_by,
                "activated_at": license_record.activated_at.isoformat()
                if license_record.activated_at
                else None,
                "expires_at": license_record.expires_at.isoformat()
                if license_record.expires_at
                else None,
                "device_limit": license_record.device_limit,
            }
        )

    if license_record.status != "unused":
        return error("license key already activated")

    now = datetime.utcnow()
    license_record.status = "active"
    license_record.activated_by = user.id
    license_record.activated_at = now
    license_record.expires_at = now + timedelta(days=license_record.duration_days)

    db.commit()
    db.refresh(license_record)

    return ok(
        {
            "license_key": license_record.license_key,
            "status": license_record.status,
            "activated_by": license_record.activated_by,
            "activated_at": license_record.activated_at.isoformat(),
            "expires_at": license_record.expires_at.isoformat(),
            "device_limit": license_record.device_limit,
        }
    )
