"""Create and retrieve application users from Google OIDC claims."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import User

PROFILE_FIELDS = (
    "email",
    "name",
    "given_name",
    "family_name",
    "picture_url",
    "locale",
    "email_verified",
)


def _clean_text(value, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_length is not None:
        text = text[:max_length]
    return text


def claims_to_profile(claims: dict) -> dict:
    """Map verified Google ID-token claims to user columns.

    Only ``sub`` is used as the identity key. Email and profile fields are
    descriptive and are refreshed when they change in Google.
    """
    if not isinstance(claims, dict):
        raise ValueError("Authentication claims must be a mapping.")

    google_sub = _clean_text(claims.get("sub"), max_length=255)
    if not google_sub:
        raise ValueError("Google subject identifier (sub) is required.")

    email = _clean_text(claims.get("email"), max_length=255)
    if not email:
        raise ValueError("Google account did not provide an email address.")

    return {
        "google_sub": google_sub,
        "email": email,
        "name": _clean_text(claims.get("name"), max_length=255),
        "given_name": _clean_text(claims.get("given_name"), max_length=255),
        "family_name": _clean_text(claims.get("family_name"), max_length=255),
        "picture_url": _clean_text(claims.get("picture"), max_length=1024),
        "locale": _clean_text(claims.get("locale"), max_length=20),
        "email_verified": bool(claims.get("email_verified", False)),
    }


def validate_user_id(user_id) -> int:
    """Return a positive integer user id or raise a user-safe ValueError."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("A valid user_id is required.")
    return user_id


def require_user(db: Session, user_id) -> int:
    """Validate the id and confirm the user row exists before a write."""
    user_id = validate_user_id(user_id)
    if db.get(User, user_id) is None:
        raise ValueError("A valid user_id for an existing user is required.")
    return user_id


def get_user_by_google_sub(db: Session, google_sub: str) -> User | None:
    if not google_sub:
        return None
    return db.scalar(select(User).where(User.google_sub == google_sub))


def get_or_create_user(db: Session, claims: dict) -> User:
    """Return the user for these claims, creating or refreshing the row.

    Safe for repeated logins: the unique constraint on ``google_sub`` and an
    IntegrityError fallback prevent duplicate identities under a race.
    """
    profile = claims_to_profile(claims)
    now = datetime.now(timezone.utc)
    user = get_user_by_google_sub(db, profile["google_sub"])

    if user is None:
        user = User(**profile, last_login_at=now)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Another worker created the same identity first.
            db.rollback()
            user = get_user_by_google_sub(db, profile["google_sub"])
            if user is None:
                raise
        else:
            db.refresh(user)
            return user

    for field in PROFILE_FIELDS:
        setattr(user, field, profile[field])
    user.last_login_at = now
    db.commit()
    db.refresh(user)
    return user
