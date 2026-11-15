"""IFORA-25: SAML IdP interoperability matrix, judged by two independent validators.

Responses are built by the IdP code with its real, database-held signing key (nothing about crypto is mocked), then handed to:

1. python3-saml in strict mode (libxmlsec1, a C implementation: `validate` in test_saml.py), and
2. `second_validator` below: signxml's XMLVerifier plus our own checks of the *signed* element (a different code path from
   libxmlsec1; it is the same library that signs, so it is independent in verification logic, not in authorship).

A response is only "interoperable" when both accept it; an attack is only "defended" when both refuse it.
`saml_matrix.py` ties each row of the matrix to the tests here; `scripts/saml_matrix.py` writes the document from a real run.
"""

import base64
import copy
import datetime as dt

import pytest
from lxml import etree
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from signxml import XMLVerifier

from backend.app.saml import keys
from backend.app.saml import protocol as P
from backend.app.saml.routes import ACR_PPT
from tests import saml_matrix as M
from tests.test_saml import ACS, SP, idp_cert, saml_app, validate
from tests.test_applications import assign
from tests.test_tenancy import tenant_b  # noqa: F401  (fixture)

SAML = "{%s}" % P.NS["saml"]
SAMLP = "{%s}" % P.NS["samlp"]
OTHER_ACS = "https://sp.example.com/other-acs"
EMAIL = "alice@example.com"
FORMATS = {"email": P.FMT_EMAIL, "persistent": P.FMT_PERSISTENT, "unspecified": P.FMT_UNSPECIFIED}
SIGNING = {"both": (True, True), "assertion": (True, False), "response": (False, True)}  # (assertion signed, response signed)


def now():
    return dt.datetime.now(dt.timezone.utc)


def issue(db, signing="both", fmt=P.FMT_EMAIL, *, at=None, audience=SP, acs=ACS, irt=None, validity=300, name_id=EMAIL):
    """A response exactly as the IdP builds it, signed with the tenant's active key. Returns (xml bytes, certificate PEM)."""
    key_pem, cert_pem = keys.private_and_cert(keys.active(db))
    sign_assertion, sign_response = SIGNING[signing]
    xml = P.build_response(
        sp_entity_id=SP, acs_url=acs, audience=audience, name_id=name_id, name_id_format=fmt, in_response_to=irt,
        attributes=[("email", [EMAIL]), ("groups", ["eng", "ops"])], auth_time=at or now(), authn_context=ACR_PPT, validity=validity,
        sign_assertion=sign_assertion, sign_response=sign_response, key_pem=key_pem, cert_pem=cert_pem, now=at)
    return xml, cert_pem.decode()


def b64(xml: bytes) -> str:
    return base64.b64encode(xml).decode()


class Refused(Exception):
    pass


def second_validator(xml, cert_pem, *, audience=SP, acs=ACS, request_id=None, at=None, signed="any", skew=300):
    """Accept or refuse a response using only what a verified signature covers.

    Every claim is read from the element whose signature verified (never from the unverified document), the document must
    hold exactly one assertion, and issuer, destination, recipient, audience, InResponseTo and the time window are checked.
    Returns {"name_id": ..., "attributes": {...}}; raises Refused otherwise.
    """
    at = at or now()
    root = P.parse_xml(xml)  # the IdP's own hardened parser (no DTDs, entities or network)
    if len(root.findall(f".//{SAML}Assertion")) != 1 or len(root.findall(f"{SAML}Assertion")) != 1:
        raise Refused("the response must contain exactly one assertion, directly under the response")
    verifier = XMLVerifier()

    def verified(elem):
        try:
            return verifier.verify(elem, x509_cert=cert_pem, expect_references=1).signed_xml
        except Exception as e:  # every verification failure (bad digest, bad signature, malformed) means "not signed by us"
            raise Refused(f"signature: {type(e).__name__}") from None

    resp_sig = root.find("{http://www.w3.org/2000/09/xmldsig#}Signature") is not None
    asrt = root.find(f"{SAML}Assertion")
    asrt_sig = asrt.find("{http://www.w3.org/2000/09/xmldsig#}Signature") is not None
    if signed == "assertion" and not asrt_sig or signed == "response" and not resp_sig or signed == "both" and not (asrt_sig and resp_sig):
        raise Refused("the required signature is missing")
    if not (resp_sig or asrt_sig):
        raise Refused("unsigned")
    if resp_sig:
        root = verified(root)
        asrt = root.find(f"{SAML}Assertion")
        if asrt is None:
            raise Refused("the signed response holds no assertion")
        if root.get("Destination") != acs:
            raise Refused("destination")
        if request_id is not None and root.get("InResponseTo") != request_id:
            raise Refused("InResponseTo (response)")
        if root.find(f"{SAML}Issuer").text != P.idp_entity_id():
            raise Refused("issuer (response)")
    if asrt_sig:
        asrt = verified(asrt)
    if asrt.find(f"{SAML}Issuer").text != P.idp_entity_id():
        raise Refused("issuer")
    cond = asrt.find(f"{SAML}Conditions")
    lo = dt.datetime.strptime(cond.get("NotBefore"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    hi = dt.datetime.strptime(cond.get("NotOnOrAfter"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    if at + dt.timedelta(seconds=skew) < lo or at - dt.timedelta(seconds=skew) >= hi:
        raise Refused("time window")
    auds = [a.text for a in cond.iter(f"{SAML}Audience")]
    if auds != [audience]:
        raise Refused("audience")
    scd = asrt.find(f"{SAML}Subject/{SAML}SubjectConfirmation/{SAML}SubjectConfirmationData")
    if scd.get("Recipient") != acs:
        raise Refused("recipient")
    if request_id is not None and scd.get("InResponseTo") != request_id:
        raise Refused("InResponseTo")
    attrs = {a.get("Name"): [v.text for v in a] for a in asrt.iter(f"{SAML}Attribute")}
    return {"name_id": asrt.find(f"{SAML}Subject/{SAML}NameID").text, "attributes": attrs}


def both_accept(xml, cert, *, signing="both", **kw):
    """Run the two validators with matching expectations; returns (python3-saml response, second validator result)."""
    asserted, messaged = SIGNING[signing]
    sp, acs, rid, at = kw.get("audience", SP), kw.get("acs", ACS), kw.get("request_id"), kw.get("at")
    r1 = validate(b64(xml), cert, request_id=rid, assertions_signed=asserted, messages_signed=messaged, sp=sp, acs=acs)
    r2 = second_validator(xml, cert, audience=sp, acs=acs, request_id=rid, at=at, signed="assertion" if asserted and not messaged else "response" if messaged and not asserted else "both")
    return r1, r2


def both_refuse(xml, cert, *, signing="both", **kw):
    asserted, messaged = SIGNING[signing]
    sp, acs, rid, at = kw.get("audience", SP), kw.get("acs", ACS), kw.get("request_id"), kw.get("at")
    with pytest.raises(Exception):
        validate(b64(xml), cert, request_id=rid, assertions_signed=asserted, messages_signed=messaged, sp=sp, acs=acs)
    with pytest.raises(Refused):
        second_validator(xml, cert, audience=sp, acs=acs, request_id=rid, at=at, signed="assertion" if asserted and not messaged else "response" if messaged and not asserted else "both")


# --- the matrix describes tests that exist ---------------------------------------------------------------------------


def test_every_test_the_saml_matrix_names_exists():
    import ast
    from pathlib import Path

    here = Path(__file__).resolve().parent
    missing = []
    for row in M.ROWS:
        assert row.tests, f"{row.id} names no test"
        for ref in row.tests:
            path, _, name = ref.partition("::")
            f = here / path
            names = {n.name for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))} if f.exists() else set()
            if name not in names:
                missing.append(ref)
    assert not missing, missing
    ids = [r.id for r in M.ROWS]
    assert len(ids) == len(set(ids))


# --- AC1: signature location x NameID format, both validators accept ----------------------------------------------------


@pytest.mark.parametrize("fmt_name", sorted(FORMATS))
@pytest.mark.parametrize("signing", sorted(SIGNING))
def test_idp_initiated_response_is_accepted_by_both_validators(db, signing, fmt_name):
    xml, cert = issue(db, signing, FORMATS[fmt_name])
    r1, r2 = both_accept(xml, cert, signing=signing)
    assert r1.get_nameid() == r2["name_id"] == EMAIL
    assert r1.get_nameid_format() == FORMATS[fmt_name]
    assert r1.get_attributes()["groups"] == r2["attributes"]["groups"] == ["eng", "ops"]


def test_sp_initiated_in_response_to_is_checked_by_both_validators(db):
    xml, cert = issue(db, irt="_req-1")
    both_accept(xml, cert, request_id="_req-1")
    both_refuse(xml, cert, request_id="_req-2")  # a response for another request (replay against a new AuthnRequest)


def test_the_published_metadata_matches_what_signs(db, super_admin, member):
    saml_app(super_admin)
    xml = member.c.get("/saml/metadata").content
    parsed = OneLogin_Saml2_IdPMetadataParser.parse(xml.decode())["idp"]
    assert parsed["entityId"] == P.idp_entity_id()
    assert parsed["singleSignOnService"]["url"] == P.sso_url()
    cert_in_metadata = idp_cert(member)[0]
    assert "".join(parsed["x509cert"].split()) == cert_in_metadata
    xml, pem = issue(db)
    assert "".join(pem.strip().splitlines()[1:-1]) == cert_in_metadata
    both_accept(xml, cert_in_metadata)  # the bare base64 from the metadata is all an SP needs to pin


def test_end_to_end_response_over_http_is_accepted_by_both_validators(super_admin, member):
    aid, _ = saml_app(super_admin, attribute_mappings=[{"name": "email", "source": "email"}])
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    out = member.post(f"/saml/apps/{aid}/respond").json()
    xml = base64.b64decode(out["saml_response"])
    cert = idp_cert(member)[0]
    r1, r2 = both_accept(xml, cert)
    assert r1.get_nameid() == r2["name_id"] == member.user.email


# --- AC2: tampering and signature wrapping are refused ------------------------------------------------------------------


@pytest.mark.parametrize("signing", sorted(SIGNING))
def test_a_tampered_assertion_is_refused_by_both_validators(db, signing):
    xml, cert = issue(db, signing)
    root = etree.fromstring(xml)
    root.find(f".//{SAML}NameID").text = "admin@example.com"
    both_refuse(etree.tostring(root), cert, signing=signing)


def test_a_tampered_attribute_value_is_refused(db):
    xml, cert = issue(db, "assertion")
    root = etree.fromstring(xml)
    next(root.iter(f"{SAML}AttributeValue")).text = "root"
    both_refuse(etree.tostring(root), cert, signing="assertion")


def _wrapped(xml, evil_name_id="admin@example.com"):
    """Classic signature wrapping: the genuine signed assertion is hidden inside Extensions and an unsigned forged one sits
    where the SP expects the assertion. The embedded signature still verifies; only careful consumers notice."""
    root = etree.fromstring(xml)
    genuine = root.find(f"{SAML}Assertion")
    forged = copy.deepcopy(genuine)
    sig = forged.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
    forged.remove(sig)
    forged.find(f".//{SAML}NameID").text = evil_name_id
    ext = etree.Element(f"{SAMLP}Extensions")
    root.replace(genuine, forged)
    root.append(ext)
    ext.append(genuine)
    return etree.tostring(root), genuine


def test_a_wrapped_signature_is_refused_by_both_validators(db):
    xml, cert = issue(db, "assertion")
    wrapped, genuine = _wrapped(xml)
    # control: the relocated genuine assertion still carries a valid signature, so this really is a wrapping attack
    XMLVerifier().verify(copy.deepcopy(genuine), x509_cert=cert, expect_references=1)
    both_refuse(wrapped, cert, signing="assertion")


def test_a_second_assertion_beside_the_signed_one_is_refused(db):
    xml, cert = issue(db, "assertion")
    root = etree.fromstring(xml)
    extra = copy.deepcopy(root.find(f"{SAML}Assertion"))
    extra.remove(extra.find("{http://www.w3.org/2000/09/xmldsig#}Signature"))
    extra.find(f".//{SAML}NameID").text = "admin@example.com"
    root.insert(0, extra)
    both_refuse(etree.tostring(root), cert, signing="assertion")


def test_an_unsigned_response_is_refused(db):
    key_pem, cert_pem = keys.private_and_cert(keys.active(db))
    xml = P.build_response(sp_entity_id=SP, acs_url=ACS, audience=SP, name_id=EMAIL, name_id_format=P.FMT_EMAIL, in_response_to=None,
                           attributes=[], auth_time=now(), authn_context=ACR_PPT, validity=300, sign_assertion=False, sign_response=False,
                           key_pem=key_pem, cert_pem=cert_pem)
    both_refuse(xml, cert_pem.decode())


def test_a_response_signed_by_another_key_is_refused(db, super_admin):
    xml, old_cert = issue(db)
    assert super_admin.post("/admin/applications/saml/rotate-key").status_code == 200
    both_accept(xml, old_cert)  # the old key still verifies what it signed
    new_cert = keys.private_and_cert(keys.active(db))[1].decode()
    both_refuse(xml, new_cert)  # but not under the new certificate an SP now pins


def test_signing_policy_mismatch_is_refused(db):
    xml, cert = issue(db, "response")
    with pytest.raises(Exception):
        validate(b64(xml), cert, assertions_signed=True, messages_signed=True)  # the SP requires a signed assertion
    with pytest.raises(Refused):
        second_validator(xml, cert, signed="assertion")


# --- time, audience, destination ----------------------------------------------------------------------------------------


def test_an_expired_assertion_is_refused(db):
    xml, cert = issue(db, at=now() - dt.timedelta(seconds=1000))  # lifetime ended ~700 s ago, past any clock drift
    both_refuse(xml, cert)


def test_an_assertion_that_is_not_yet_valid_is_refused(db):
    xml, cert = issue(db, at=now() + dt.timedelta(seconds=1000))
    both_refuse(xml, cert)


def test_modest_clock_skew_is_tolerated(db):
    xml, cert = issue(db, at=now() + dt.timedelta(seconds=20))  # IdP clock 20 s ahead: NotBefore is backdated by 30 s
    both_accept(xml, cert)


def test_a_wrong_audience_is_refused(db):
    xml, cert = issue(db, audience="https://other-sp.example.com/meta")
    both_refuse(xml, cert)


def test_a_wrong_destination_is_refused(db):
    xml, cert = issue(db, acs=OTHER_ACS)  # addressed to a different ACS than the SP that is validating
    both_refuse(xml, cert)


# --- AC6: tenant isolation of SAML apps ---------------------------------------------------------------------------------


def test_another_tenants_saml_app_does_not_exist_for_this_tenant(db, super_admin, member, anon, tenant_b):
    import uuid

    from backend.app.applications.models import Application
    from backend.app.saml.models import SamlProvider
    from tests.test_saml import authn_xml, sso
    from tests.test_tenancy import b_session

    s = b_session(tenant_b)
    app_b = Application(public_id=str(uuid.uuid4()), name="b-saml", sign_on_mode="saml")
    s.add(app_b)
    s.flush()
    s.add(SamlProvider(application_id=app_b.id, sp_entity_id="https://b-sp.example.com/meta", acs_url="https://b-sp.example.com/acs"))
    s.commit()
    bid = app_b.id
    s.close()

    assert member.post(f"/saml/apps/{bid}/respond").status_code == 404
    assert super_admin.get(f"/admin/applications/{bid}/saml").status_code == 404
    assert super_admin.put(f"/admin/applications/{bid}/saml", {"sp_entity_id": "https://x.example.com/m", "acs_url": "https://x.example.com/a"}).status_code == 404
    # B's SP entity id is unknown to A: the SP-initiated request is refused without ever naming B's ACS
    r = sso(anon, authn_xml(issuer="https://b-sp.example.com/meta", acs="https://b-sp.example.com/acs"))
    assert r.status_code == 303 and "b-sp.example.com" not in r.headers["location"]
    assert "error=" in r.headers["location"]
