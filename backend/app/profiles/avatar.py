"""Profile pictures.

The browser sends the raw image bytes (no multipart). Whatever arrives is untrusted: it is size-capped while
streaming, decoded with Pillow under a pixel limit, cropped to a square and re-encoded as a small WebP. The
original bytes are never stored or served, which also drops EXIF (GPS, camera) and any trailing payload.
"""

import hashlib
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Session

from backend.app import ratelimit
from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import get_session_and_user, require_admin
from backend.app.db import Base, get_db
from backend.app.tenancy import TenantOwned
from backend.app.users.model import User

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 25_000_000  # decoded size; blocks decompression bombs before any pixel is decoded
MIN_SIDE = 64
OUTPUT_SIDE = 256
ACCEPTED_TYPES = {"image/jpeg", "image/png", "image/webp"}
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}
UPLOADS_PER_WINDOW = 10
WINDOW_SECONDS = 600

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class UserAvatar(TenantOwned, Base):
    """The processed picture. Kept apart from `users` so listing users never loads image bytes."""

    __tablename__ = "user_avatars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    content_type = Column(String(32), nullable=False, default="image/webp")
    data = Column(LargeBinary, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AvatarError(ValueError):
    """The upload cannot be used; the message is safe to show."""


def process(raw: bytes) -> bytes:
    """Validate an uploaded image and return the stored form: a 256x256 WebP with no metadata."""
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ACCEPTED_FORMATS:
                raise AvatarError("Use a JPEG, PNG or WebP image")
            width, height = im.size
            if width * height > MAX_PIXELS:
                raise AvatarError("That image is too large; use one under 25 megapixels")
            if min(width, height) < MIN_SIDE:
                raise AvatarError(f"That image is too small; use one at least {MIN_SIDE} pixels on each side")
            im.seek(0)  # animated files: first frame only
            im.load()
            im = ImageOps.exif_transpose(im)
            has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            im = im.convert("RGBA" if has_alpha else "RGB")
            im = ImageOps.fit(im, (OUTPUT_SIDE, OUTPUT_SIDE), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            out = io.BytesIO()
            im.save(out, format="WEBP", quality=85, method=4)  # no exif/icc passed, so none is written
            return out.getvalue()
    except AvatarError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, EOFError, SyntaxError):
        raise AvatarError("That file could not be read as an image")


def etag_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


async def read_capped(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="That image is larger than 2 MB")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="That image is larger than 2 MB")
    if not buf:
        raise HTTPException(status_code=400, detail="No image was sent")
    return bytes(buf)


def _store(db: Session, user: User, data: bytes) -> None:
    row = db.query(UserAvatar).filter(UserAvatar.user_id == user.id).first()
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(UserAvatar(user_id=user.id, content_type="image/webp", data=data, updated_at=now))
    else:
        row.data, row.content_type, row.updated_at = data, "image/webp", now
    user.avatar_etag = etag_of(data)


def _clear(db: Session, user: User) -> bool:
    removed = db.query(UserAvatar).filter(UserAvatar.user_id == user.id).delete()
    user.avatar_etag = None
    return bool(removed)


router = APIRouter(tags=["profile"])


@router.put("/me/avatar")
async def upload_avatar(request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    _, user, _ = ctx
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in ACCEPTED_TYPES:
        raise HTTPException(status_code=415, detail="Use a JPEG, PNG or WebP image")
    ident = f"u{user.id}"
    ratelimit.check("avatar", ident, UPLOADS_PER_WINDOW)
    ratelimit.hit("avatar", ident, WINDOW_SECONDS)
    raw = await read_capped(request)
    try:
        data = process(raw)
    except AvatarError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _store(db, user, data)
    record(db, AuditAction.AVATAR_UPDATED, request, user, user.id, "user", {"bytes": len(data)})
    db.commit()
    return {"avatar_etag": user.avatar_etag}


@router.delete("/me/avatar")
def remove_avatar(request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    _, user, _ = ctx
    if _clear(db, user):
        record(db, AuditAction.AVATAR_REMOVED, request, user, user.id, "user", {})
    db.commit()
    return {"avatar_etag": None}


@router.delete("/admin/users/{user_id}/avatar")
def admin_remove_avatar(
    user_id: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)
):
    """Moderation: an administrator can clear anyone's picture."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if _clear(db, target):
        record(db, AuditAction.AVATAR_REMOVED, request, actor, target.id, "user", {"by_admin": True})
    db.commit()
    return {"avatar_etag": None}


@router.get("/avatars/{user_id}")
def get_avatar(user_id: int, request: Request, ctx=Depends(get_session_and_user), db: Session = Depends(get_db)):
    """Only the owner and administrators can fetch a picture."""
    _, viewer, _ = ctx
    if viewer.id != user_id and not viewer.is_admin:
        raise HTTPException(status_code=404, detail="No picture")
    row = db.query(UserAvatar).filter(UserAvatar.user_id == user_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No picture")
    etag = f'"{etag_of(row.data)}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=row.data, media_type=row.content_type, headers=headers)
