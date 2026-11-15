"""IFORA-25: SAML signing certificate lifecycle: validity, expiry reporting, staged rotation, audit."""

import datetime as dt

import pytest
from cryptography import x509
from sqlalchemy import select

from backend.app.audit.model import AuditAction, AuditEvent
from backend.app.config import settings
from backend.app.saml import keys
from backend.app.saml.models import SamlSigningKey
from tests.test_applications import assign
from tests.test_saml import idp_cert, saml_app, validate

BASE = "/admin/applications/saml"


def test_new_certificates_use_the_configured_validity_and_report_days_to_expiry(db, super_admin, monkeypatch):
    monkeypatch.setattr(settings, "SAML_CERT_VALIDITY_DAYS", 400)
    row = keys.rotate(db)
    db.commit()
    cert = x509.load_pem_x509_certificate(row.cert_pem.encode())
    life = cert.not_valid_after_utc - cert.not_valid_before_utc
    assert dt.timedelta(days=399) < life <= dt.timedelta(days=400, minutes=10)
    listing = super_admin.get(f"{BASE}/keys").json()
    top = listing["keys"][0]
    assert top["status"] == "active" and 398 <= top["days_to_expiry"] <= 400 and top["expiring_soon"] is False
    assert listing["validity_days"] == 400
    assert not any("PRIVATE" in str(v) for k in listing["keys"] for v in k.values())  # fingerprints only


def test_the_default_validity_is_two_years():
    assert settings.SAML_CERT_VALIDITY_DAYS == 730


def test_a_certificate_close_to_expiry_is_flagged(db, super_admin):
    row = keys.active(db)
    row.not_after = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)
    db.commit()
    top = super_admin.get(f"{BASE}/keys").json()["keys"][0]
    assert top["expiring_soon"] is True and top["days_to_expiry"] <= 10


def test_a_staged_certificate_is_published_before_it_signs(db, super_admin, admin, member):
    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    active_cert = idp_cert(member)[0]
    assert admin.post(f"{BASE}/stage-key").status_code == 403  # super administrators only
    r = super_admin.post(f"{BASE}/stage-key")
    assert r.status_code == 200 and r.json()["days_to_expiry"] > 700
    certs = idp_cert(member)
    assert len(certs) == 2 and certs[0] == active_cert and certs[1] != active_cert  # the staged one is published, after the active one
    out = member.post(f"/saml/apps/{aid}/respond").json()["saml_response"]
    validate(out, active_cert)  # still signed by the active key
    with pytest.raises(Exception):
        validate(out, certs[1])
    listing = super_admin.get("/admin/applications/saml/keys").json()["keys"]
    assert [k["status"] for k in listing] == ["active", "next"]
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == AuditAction.SAML_KEY_STAGED)).one()
    assert event.event_metadata["fingerprint"] == r.json()["fingerprint"]


def test_staging_again_replaces_the_staged_certificate(db, super_admin, member):
    first = super_admin.post(f"{BASE}/stage-key").json()["fingerprint"]
    second = super_admin.post(f"{BASE}/stage-key").json()["fingerprint"]
    assert first != second
    assert [k["status"] for k in super_admin.get("/admin/applications/saml/keys").json()["keys"]] == ["active", "next"]
    assert len(idp_cert(member)) == 2


def test_promote_switches_signing_and_keeps_the_old_certificate_published(db, super_admin, admin, member):
    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    old = idp_cert(member)[0]
    staged = super_admin.post(f"{BASE}/stage-key").json()
    assert admin.post(f"{BASE}/promote-key").status_code == 403
    r = super_admin.post(f"{BASE}/promote-key")
    assert r.status_code == 200 and r.json()["fingerprint"] == staged["fingerprint"]
    certs = idp_cert(member)
    assert len(certs) == 2 and certs[0] != old and old in certs  # overlap: both published, the new one first
    out = member.post(f"/saml/apps/{aid}/respond").json()["saml_response"]
    validate(out, certs[0])
    with pytest.raises(Exception):
        validate(out, old)
    assert [k["status"] for k in super_admin.get("/admin/applications/saml/keys").json()["keys"]] == ["active", "retired"]
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == AuditAction.SAML_KEY_PROMOTED)).one()
    assert event.event_metadata["fingerprint"] == staged["fingerprint"]


def test_promoting_with_nothing_staged_is_a_clean_409(db, super_admin):
    keys.active(db)
    db.commit()
    r = super_admin.post(f"{BASE}/promote-key")
    assert r.status_code == 409
    assert [k["status"] for k in super_admin.get("/admin/applications/saml/keys").json()["keys"]] == ["active"]  # nothing changed


def test_immediate_rotation_is_still_audited_and_publishes_both(db, super_admin, member):
    old = idp_cert(member)[0]
    r = super_admin.post(f"{BASE}/rotate-key")
    assert r.status_code == 200
    assert len(idp_cert(member)) == 2 and old in idp_cert(member)
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == AuditAction.SAML_KEY_ROTATED)).one()
    assert event.event_metadata["fingerprint"] == r.json()["fingerprint"]


def test_an_expired_retired_certificate_is_no_longer_published(db, super_admin, member):
    old = idp_cert(member)[0]
    super_admin.post(f"{BASE}/rotate-key")
    assert len(idp_cert(member)) == 2
    retired = db.scalars(select(SamlSigningKey).where(SamlSigningKey.status == "retired")).one()
    retired.not_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    db.commit()
    certs = idp_cert(member)
    assert len(certs) == 1 and old not in certs


def test_key_endpoints_need_an_administrator(anon, member):
    assert anon.c.get("/admin/applications/saml/keys").status_code in (401, 403, 404)
    assert member.get("/admin/applications/saml/keys").status_code in (401, 403, 404)
    assert member.post(f"{BASE}/stage-key").status_code in (401, 403, 404)
