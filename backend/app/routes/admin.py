import os
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AIConfig, AIUsageLog, License, User
from app.utils import ALGORITHM
from ai_provider import test_ai_config

load_dotenv()

router = APIRouter(prefix="/admin")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
ADMIN_JWT_SECRET = os.getenv("ADMIN_JWT_SECRET")
ADMIN_TOKEN_EXPIRE_HOURS = 12
LICENSE_ALPHABET = string.ascii_uppercase + string.digits
SUPPORTED_AI_PROVIDERS = {"deepseek", "qwen", "openai", "apirouter", "aipower"}


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class LicenseCreateRequest(BaseModel):
    duration_days: int = Field(gt=0)
    device_limit: int = Field(gt=0)
    count: int = Field(gt=0, le=500)


class LicenseUpdateRequest(BaseModel):
    license_key: Optional[str] = None
    duration_days: Optional[int] = Field(default=None, gt=0)
    device_limit: Optional[int] = Field(default=None, gt=0)
    status: Optional[str] = None
    activated_by: Optional[int] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class AIConfigRequest(BaseModel):
    id: Optional[int] = None
    provider: str
    model_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled: bool = True
    is_default: bool = False
    description: Optional[str] = None


def ok(data):
    return {"status": "ok", "data": data}


def ensure_admin_configured():
    if not ADMIN_USERNAME or not ADMIN_PASSWORD or not ADMIN_JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="admin credentials are not configured",
        )


def create_admin_token():
    ensure_admin_configured()
    now = datetime.utcnow()
    payload = {
        "sub": ADMIN_USERNAME,
        "scope": "admin",
        "iat": now,
        "exp": now + timedelta(hours=ADMIN_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=ALGORITHM)


def verify_admin_token(
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
):
    ensure_admin_configured()
    token = x_admin_token
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin_token is required",
        )

    try:
        payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired admin_token",
        ) from exc

    if payload.get("scope") != "admin" or payload.get("sub") != ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin_token",
        )
    return payload


def serialize_license(license_record: License):
    return {
        "id": license_record.id,
        "license_key": license_record.license_key,
        "duration_days": license_record.duration_days,
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


def serialize_admin_user(user: User, license_record: Optional[License]):
    license_status = "none"
    license_expires_at = None
    if license_record:
        license_status = license_record.status
        if license_record.expires_at:
            license_expires_at = license_record.expires_at.isoformat()
            if license_record.expires_at < datetime.utcnow():
                license_status = "expired"

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
        "license_status": license_status,
        "license_expires_at": license_expires_at,
    }


def serialize_ai_usage_log(log: AIUsageLog):
    return {
        "id": log.id,
        "user_id": log.user_id,
        "license_key": log.license_key,
        "model_used": log.model_used,
        "estimated_cost_usd": log.estimated_cost_usd,
        "ai_status": log.ai_status,
        "created_at": log.created_at.isoformat(),
    }


def mask_api_key(api_key: Optional[str]):
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return f"{api_key[:2]}****"
    return f"{api_key[:6]}****{api_key[-3:]}"


def serialize_ai_config(config: AIConfig):
    return {
        "id": config.id,
        "provider": config.provider,
        "model_name": config.model_name,
        "api_key": mask_api_key(config.api_key),
        "base_url": config.base_url,
        "enabled": config.enabled,
        "is_default": config.is_default,
        "description": config.description,
        "created_at": config.created_at.isoformat(),
        "updated_at": config.updated_at.isoformat(),
    }


def generate_license_key():
    parts = [
        "".join(secrets.choice(LICENSE_ALPHABET) for _ in range(4))
        for _ in range(3)
    ]
    return f"JCC-{'-'.join(parts)}"


def generate_unique_license_key(db: Session, pending_keys: set[str]):
    while True:
        license_key = generate_license_key()
        exists = (
            license_key in pending_keys
            or db.query(License).filter(License.license_key == license_key).first()
        )
        if not exists:
            pending_keys.add(license_key)
            return license_key


@router.post("/login")
def admin_login(payload: AdminLoginRequest):
    ensure_admin_configured()
    if payload.username != ADMIN_USERNAME or payload.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin username or password",
        )
    return ok({"admin_token": create_admin_token(), "token_type": "bearer"})


@router.get("/dashboard")
def dashboard(
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    total_users = db.query(User).count()
    total_licenses = db.query(License).count()
    active_licenses = (
        db.query(License)
        .filter(
            License.status == "active",
            or_(License.expires_at.is_(None), License.expires_at >= now),
        )
        .count()
    )
    expired_licenses = (
        db.query(License)
        .filter(or_(License.status == "expired", License.expires_at < now))
        .count()
    )
    today_start = datetime(now.year, now.month, now.day)
    total_ai_calls = db.query(AIUsageLog).count()
    total_ai_cost_usd = db.query(func.sum(AIUsageLog.estimated_cost_usd)).scalar() or 0
    today_ai_calls = (
        db.query(AIUsageLog).filter(AIUsageLog.created_at >= today_start).count()
    )
    today_ai_cost_usd = (
        db.query(func.sum(AIUsageLog.estimated_cost_usd))
        .filter(AIUsageLog.created_at >= today_start)
        .scalar()
        or 0
    )
    return ok(
        {
            "total_users": total_users,
            "total_licenses": total_licenses,
            "active_licenses": active_licenses,
            "expired_licenses": expired_licenses,
            "total_ai_calls": total_ai_calls,
            "total_ai_cost_usd": total_ai_cost_usd,
            "today_ai_calls": today_ai_calls,
            "today_ai_cost_usd": today_ai_cost_usd,
        }
    )


@router.get("/licenses")
def list_licenses(
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    licenses = db.query(License).order_by(License.id.desc()).all()
    return ok([serialize_license(license_record) for license_record in licenses])


@router.get("/users")
def list_users(
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    normalized_keyword = keyword.strip() if keyword else ""
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        query = query.filter(or_(User.username.ilike(pattern), User.email.ilike(pattern)))

    total = query.count()
    users = (
        query.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for user in users:
        license_record = (
            db.query(License)
            .filter(License.activated_by == user.id)
            .order_by(License.activated_at.desc(), License.id.desc())
            .first()
        )
        items.append(serialize_admin_user(user, license_record))

    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/ai-usage")
def list_ai_usage(
    license_key: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    query = db.query(AIUsageLog)
    normalized_license_key = license_key.strip() if license_key else ""
    if normalized_license_key:
        query = query.filter(AIUsageLog.license_key.ilike(f"%{normalized_license_key}%"))
    if user_id is not None:
        query = query.filter(AIUsageLog.user_id == user_id)

    total = query.count()
    total_calls = total
    total_cost_usd = query.with_entities(func.sum(AIUsageLog.estimated_cost_usd)).scalar() or 0
    logs = (
        query.order_by(AIUsageLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return ok(
        {
            "items": [serialize_ai_usage_log(log) for log in logs],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_calls": total_calls,
            "total_cost_usd": total_cost_usd,
        }
    )


@router.get("/ai-config")
def list_ai_config(
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    configs = db.query(AIConfig).order_by(AIConfig.id.desc()).all()
    return ok([serialize_ai_config(config) for config in configs])


@router.post("/ai-config")
def save_ai_config(
    payload: AIConfigRequest,
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    provider = payload.provider.strip().lower()
    if provider not in SUPPORTED_AI_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported provider",
        )

    if payload.is_default:
        db.query(AIConfig).update({AIConfig.is_default: False})

    config = None
    if payload.id is not None:
        config = db.query(AIConfig).filter(AIConfig.id == payload.id).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ai config not found",
            )

    if not config:
        config = AIConfig(created_at=datetime.utcnow())
        db.add(config)

    config.provider = provider
    config.model_name = payload.model_name.strip()
    if payload.api_key is not None and "****" not in payload.api_key:
        config.api_key = payload.api_key.strip()
    config.base_url = payload.base_url.strip() if payload.base_url else None
    config.enabled = payload.enabled
    config.is_default = payload.is_default
    config.description = payload.description.strip() if payload.description else None
    config.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(config)
    return ok(serialize_ai_config(config))


@router.delete("/ai-config/{config_id}")
def delete_ai_config(
    config_id: int,
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    config = db.query(AIConfig).filter(AIConfig.id == config_id).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ai config not found",
        )

    db.delete(config)
    db.commit()
    return ok({"deleted": True, "id": config_id})


@router.post("/ai-config/{config_id}/test")
def test_admin_ai_config(
    config_id: int,
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    config = db.query(AIConfig).filter(AIConfig.id == config_id).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ai config not found",
        )

    result = test_ai_config(
        {
            "provider": config.provider,
            "model_name": config.model_name,
            "api_key": config.api_key,
            "base_url": config.base_url,
        }
    )
    return ok(
        {
            "status": result["ai_status"],
            "message": result["error"] or "AI config test succeeded",
            "model_used": result["model_used"],
            "estimated_cost_usd": result["cost_estimate_usd"],
        }
    )


@router.post("/licenses/create")
def create_licenses(
    payload: LicenseCreateRequest,
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    pending_keys: set[str] = set()
    licenses = []
    for _index in range(payload.count):
        licenses.append(
            License(
                license_key=generate_unique_license_key(db, pending_keys),
                duration_days=payload.duration_days,
                device_limit=payload.device_limit,
                status="unused",
            )
        )

    db.add_all(licenses)
    db.commit()
    for license_record in licenses:
        db.refresh(license_record)

    return ok([serialize_license(license_record) for license_record in licenses])


@router.patch("/licenses/{license_id}")
def update_license(
    license_id: int,
    payload: LicenseUpdateRequest,
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    license_record = db.query(License).filter(License.id == license_id).first()
    if not license_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="license not found")

    updates = payload.dict(exclude_unset=True)
    if "license_key" in updates and updates["license_key"] != license_record.license_key:
        existing = (
            db.query(License)
            .filter(License.license_key == updates["license_key"], License.id != license_id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="license_key already exists",
            )

    for field, value in updates.items():
        setattr(license_record, field, value)

    db.commit()
    db.refresh(license_record)
    return ok(serialize_license(license_record))


@router.delete("/licenses/{license_id}")
def delete_license(
    license_id: int,
    _: dict = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    license_record = db.query(License).filter(License.id == license_id).first()
    if not license_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="license not found")

    db.delete(license_record)
    db.commit()
    return ok({"deleted": True, "id": license_id})
