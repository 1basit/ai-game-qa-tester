"""Authentication, authorisation and audit (SRS 5.4).

* Passwords: bcrypt (salted), minimum length from config (8).
* Sessions: HS256-signed JWT. Besides the token's own expiry, the server enforces the
  SRS rule "expire after twelve hours of inactivity" using ``users.last_activity``,
  updated on every authenticated request — a stolen-but-idle token stops working.
* Roles (SRS Table 1): tester and developer upload/view/export within their projects;
  qa_lead additionally sees cross-project statistics; admin manages accounts and can
  access every project.
* Project isolation: every project-scoped endpoint checks membership (admin exempt).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from gameqa.api.models import AuditLog, Project, ProjectMember, Role, User

ALGO = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode())
    except ValueError:
        return False


def create_token(user: User, secret: str, lifetime_days: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user.id, "role": user.role.value, "iat": int(now.timestamp()),
               "exp": int((now + timedelta(days=lifetime_days)).timestamp())}
    return jwt.encode(payload, secret, algorithm=ALGO)


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    token = creds.credentials if creds else None
    if not token:
        raise unauthorized
    cfg = request.app.state.settings.api
    try:
        payload = jwt.decode(token, cfg.secret_key, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise unauthorized from None
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise unauthorized
    now = datetime.now(timezone.utc)
    last = user.last_activity
    if last is not None:
        if last.tzinfo is None:  # SQLite returns naive datetimes
            last = last.replace(tzinfo=timezone.utc)
        if now - last > timedelta(hours=cfg.inactivity_hours):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired after inactivity",
                                headers={"WWW-Authenticate": "Bearer"})
    user.last_activity = now
    db.commit()
    return user


def require_role(*roles: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role is not Role.admin and user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user
    return dep


def check_project_access(db: Session, user: User, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    if user.role is Role.admin:
        return project
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                   ProjectMember.user_id == user.id))
    if member is None:
        # 404 rather than 403: do not reveal that another team's project exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


# ---------------------------------------------------------------- signed file URLs
# <img>/<video> elements cannot send an Authorization header. Instead of putting the
# session token in a URL (it would leak into logs and history), an authenticated,
# membership-checked API call returns short-lived URLs signed for one file and one user.
import hashlib  # noqa: E402
import hmac  # noqa: E402
import time  # noqa: E402

FILE_URL_TTL_S = 600


def sign_file(secret: str, rel_path: str, user_id: str, ttl_s: int = FILE_URL_TTL_S) -> str:
    exp = int(time.time()) + ttl_s
    msg = f"{rel_path}|{user_id}|{exp}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:40]
    return f"exp={exp}&uid={user_id}&sig={sig}"


def verify_file_signature(secret: str, rel_path: str, user_id: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    msg = f"{rel_path}|{user_id}|{exp}".encode()
    good = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(good, sig)


def audit(db: Session, user: User | None, action: str, target_type: str, target_id: str = "", **details) -> None:
    db.add(AuditLog(user_id=user.id if user else None, user_email=user.email if user else "",
                    action=action, target_type=target_type, target_id=target_id, details=details))
    db.commit()
