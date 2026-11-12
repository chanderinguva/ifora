"""Profile pictures: validation, re-encoding, access control, removal."""

import io

import pytest
from PIL import Image

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.profiles.avatar import UserAvatar
from tests.conftest import Api, make_user


def img(fmt="PNG", size=(300, 200), color=(200, 40, 40), mode="RGB", **save):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt, **save)
    return buf.getvalue()


def put(api, data, ctype="image/png", csrf=True):
    headers = api._h(csrf)
    headers["Content-Type"] = ctype
    return api.c.put("/api/v1/me/avatar", content=data, headers=headers)


def served(api, user_id):
    return api.get(f"/avatars/{user_id}")


def test_upload_is_cropped_and_reencoded_as_webp(member):
    r = put(member, img("PNG", (300, 200)))
    assert r.status_code == 200, r.text
    assert r.json()["avatar_etag"]
    me = member.get("/me/profile").json()
    assert me["avatar_etag"] == r.json()["avatar_etag"]
    s = served(member, member.user.id)
    assert s.status_code == 200
    assert s.headers["content-type"] == "image/webp"
    assert s.headers["x-content-type-options"] == "nosniff"
    out = Image.open(io.BytesIO(s.content))
    assert out.format == "WEBP" and out.size == (256, 256)


def test_transparency_is_kept(member):
    put(member, img("PNG", (128, 128), (10, 200, 10, 0), mode="RGBA"))
    out = Image.open(io.BytesIO(served(member, member.user.id).content))
    assert out.mode == "RGBA"


def test_metadata_is_dropped(member):
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"  # Make
    exif[0x8825] = {1: "N", 2: (40.0, 0.0, 0.0)}  # GPS block
    raw = img("JPEG", (200, 200), exif=exif.tobytes())
    assert b"SecretCameraMaker" in raw
    assert put(member, raw, "image/jpeg").status_code == 200
    body = served(member, member.user.id).content
    assert b"SecretCameraMaker" not in body
    assert len(Image.open(io.BytesIO(body)).getexif()) == 0


def test_trailing_payload_is_not_stored(member):
    raw = img("PNG", (100, 100)) + b"<script>alert(1)</script>"
    assert put(member, raw).status_code == 200
    assert b"<script>" not in served(member, member.user.id).content


@pytest.mark.parametrize("ctype", ["image/svg+xml", "image/gif", "text/html", "application/octet-stream", ""])
def test_other_content_types_are_refused(member, ctype):
    assert put(member, img("PNG"), ctype).status_code == 415


def test_a_lie_about_the_type_is_caught_by_decoding(member):
    assert put(member, b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", "image/png").status_code == 422
    assert put(member, b"not an image at all", "image/jpeg").status_code == 422


def test_gif_bytes_sent_as_png_are_refused(member):
    assert put(member, img("GIF", (100, 100)), "image/png").status_code == 422


def test_too_small(member):
    r = put(member, img("PNG", (32, 32)))
    assert r.status_code == 422 and "too small" in r.json()["detail"]


def test_decompression_bomb_is_refused_without_decoding(member):
    raw = img("PNG", (6000, 6000))  # 36 megapixels of one colour: tiny file, huge when decoded
    assert len(raw) < 200_000
    r = put(member, raw)
    assert r.status_code == 422 and "too large" in r.json()["detail"]
    assert member.get("/me/profile").json()["avatar_etag"] is None


def test_oversized_upload_is_refused(member):
    r = put(member, b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10))
    assert r.status_code == 413


def test_empty_body(member):
    assert put(member, b"").status_code == 400


def test_replacing_changes_the_etag_and_keeps_one_row(db, member):
    first = put(member, img("PNG", color=(255, 0, 0))).json()["avatar_etag"]
    second = put(member, img("PNG", color=(0, 0, 255))).json()["avatar_etag"]
    assert first != second
    db.expire_all()
    assert db.query(UserAvatar).filter(UserAvatar.user_id == member.user.id).count() == 1


def test_conditional_request_gets_304(member):
    s = served(member, member.user.id) if put(member, img()).status_code == 200 else None
    etag = s.headers["etag"]
    again = member.c.get(f"/api/v1/avatars/{member.user.id}", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""


def test_only_owner_and_admins_can_view(db, member, admin):
    put(member, img())
    other = make_user(db, "other@example.com")
    o = Api()
    assert o.login(other.email).status_code == 200
    assert served(o, member.user.id).status_code == 404
    assert served(admin, member.user.id).status_code == 200
    assert Api().get(f"/avatars/{member.user.id}").status_code == 401


def test_no_picture_is_404(member):
    assert served(member, member.user.id).status_code == 404


def test_remove(member):
    put(member, img())
    r = member.delete("/me/avatar")
    assert r.status_code == 200 and r.json()["avatar_etag"] is None
    assert served(member, member.user.id).status_code == 404
    assert member.get("/me/profile").json()["avatar_etag"] is None


def test_admin_can_clear_someones_picture_but_members_cannot(db, member, admin):
    put(member, img())
    victim = make_user(db, "victim@example.com")
    v = Api()
    v.login(victim.email)
    put(v, img())
    assert member.delete(f"/admin/users/{victim.id}/avatar").status_code == 403
    assert admin.delete(f"/admin/users/{victim.id}/avatar").status_code == 200
    assert served(v, victim.id).status_code == 404
    assert served(member, member.user.id).status_code == 200  # untouched
    assert admin.delete("/admin/users/9999/avatar").status_code == 404


def test_requires_csrf_token_and_session(member):
    assert put(member, img(), csrf=False).status_code in (401, 403)
    assert member.get("/me/profile").json()["avatar_etag"] is None
    anon = Api()
    assert put(anon, img()).status_code == 401


def test_uploads_are_rate_limited(member):
    for _ in range(10):
        assert put(member, img("PNG", (80, 80))).status_code == 200
    assert put(member, img("PNG", (80, 80))).status_code == 429


def test_changes_are_audited(db, member):
    put(member, img())
    member.delete("/me/avatar")
    actions = {e.action for e in db.query(AuditEvent).all()}
    assert AuditAction.AVATAR_UPDATED.value in actions and AuditAction.AVATAR_REMOVED.value in actions


def test_deleting_a_user_removes_the_picture(db, member, admin):
    put(member, img())
    assert admin.delete(f"/admin/users/{member.user.id}").status_code == 200
    db.expire_all()
    assert db.query(UserAvatar).count() == 0
