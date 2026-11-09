"""SAML 2.0 IdP (ADR 011). Responses are validated by python3-saml (xmlsec) in strict mode: an implementation
independent of the signxml code that produced them."""

import base64
import datetime as dt
import zlib
from urllib.parse import parse_qs, quote, quote_plus, urlsplit

import pytest
from lxml import etree
from onelogin.saml2.response import OneLogin_Saml2_Response
from onelogin.saml2.settings import OneLogin_Saml2_Settings

from backend.app.saml import protocol as P
from tests.conftest import Api
from tests.test_applications import assign, mkapp

SP = "https://sp.example.com/meta"
ACS = "https://sp.example.com/acs"
NS = {"md": P.NS["md"], "ds": P.NS["ds"], "saml": P.NS["saml"], "samlp": P.NS["samlp"]}


def saml_app(sa, name="Wiki SAML", **cfg):
    a = sa.post("/admin/applications", {"name": name, "sign_on_mode": "saml"})
    assert a.status_code == 201, a.text
    body = {"sp_entity_id": SP, "acs_url": ACS, **cfg}
    r = sa.put(f"/admin/applications/{a.json()['id']}/saml", body)
    assert r.status_code == 200, r.text
    return a.json()["id"], r.json()["provider"]


def idp_cert(api):
    r = api.c.get("/saml/metadata")
    assert r.status_code == 200
    doc = etree.fromstring(r.content)
    return [c.text for c in doc.iterfind(".//ds:X509Certificate", NS)]


def validate(resp_b64, cert, request_id=None, assertions_signed=True, messages_signed=True, sp=SP, acs=ACS):
    u = urlsplit(acs)
    st = OneLogin_Saml2_Settings({
        "strict": True, "debug": True,
        "sp": {"entityId": sp, "assertionConsumerService": {"url": acs, "binding": P.BINDING_POST}},
        "idp": {"entityId": P.idp_entity_id(), "singleSignOnService": {"url": P.sso_url(), "binding": P.BINDING_REDIRECT}, "x509cert": cert},
        "security": {"wantAssertionsSigned": assertions_signed, "wantMessagesSigned": messages_signed, "requestedAuthnContext": False},
    }, sp_validation_only=False)
    r = OneLogin_Saml2_Response(st, resp_b64)
    rd = {"https": "on", "http_host": u.netloc, "script_name": u.path, "server_port": 443, "get_data": {}, "post_data": {"SAMLResponse": resp_b64}}
    assert r.is_valid(rd, request_id=request_id, raise_exceptions=True)
    return r


def authn_xml(issuer=SP, acs=None, rid="_req1", instant=None, force=False, extra=""):
    inst = (instant or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    acs_attr = f' AssertionConsumerServiceURL="{acs}"' if acs else ""
    return (f'<samlp:AuthnRequest xmlns:samlp="{P.NS["samlp"]}" xmlns:saml="{P.NS["saml"]}" ID="{rid}" Version="2.0" IssueInstant="{inst}"'
            f'{acs_attr}{" ForceAuthn=\"true\"" if force else ""}><saml:Issuer>{issuer}</saml:Issuer>{extra}</samlp:AuthnRequest>').encode()


def deflate(xml: bytes) -> str:
    c = zlib.compressobj(wbits=-15)
    return base64.b64encode(c.compress(xml) + c.flush()).decode()


def sso(api, xml, relay=None):
    params = {"SAMLRequest": deflate(xml)}
    if relay:
        params["RelayState"] = relay
    return api.c.get("/saml/sso", params=params, follow_redirects=False)


def rid_of(r):
    assert r.status_code == 303, r.text
    return parse_qs(urlsplit(r.headers["location"]).query)["request_id"][0]


def error_of(r):
    assert r.status_code == 303
    return parse_qs(urlsplit(r.headers["location"]).query).get("error", [None])[0]


# ---- metadata and configuration ---------------------------------------------------------------------------------

def test_metadata_describes_the_idp(anon):
    doc = etree.fromstring(anon.c.get("/saml/metadata").content)
    assert doc.get("entityID") == P.idp_entity_id()
    assert {e.get("Binding") for e in doc.iterfind(".//md:SingleSignOnService", NS)} == {P.BINDING_REDIRECT, P.BINDING_POST}
    assert len(idp_cert(anon)) == 1


def test_configuration_rules(super_admin, member):
    plain = mkapp(super_admin, name="Plain")
    assert super_admin.put(f"/admin/applications/{plain['id']}/saml", {"sp_entity_id": SP, "acs_url": ACS}).status_code == 409   # mode must be SAML
    aid, _ = saml_app(super_admin)
    url = f"/admin/applications/{aid}/saml"
    for bad in ({"acs_url": "http://sp.example.com/acs"}, {"acs_url": "javascript:alert(1)"}, {"attribute_mappings": [{"name": "x y", "source": "email"}]},
                {"attribute_mappings": [{"name": "a", "source": "password_hash"}]},
                {"attribute_mappings": [{"name": "a", "source": "email"}, {"name": "a", "source": "username"}]},
                {"require_signed_requests": True}, {"sp_cert": "nope"}, {"validity_seconds": 5}):
        assert super_admin.put(url, {"sp_entity_id": SP, "acs_url": ACS, **bad}).status_code == 422, bad
    other = super_admin.post("/admin/applications", {"name": "Other", "sign_on_mode": "saml"}).json()
    assert super_admin.put(f"/admin/applications/{other['id']}/saml", {"sp_entity_id": SP, "acs_url": ACS}).status_code == 409   # entity id unique
    assert super_admin.put(f"/admin/applications/{aid}", {"name": "Wiki SAML", "sign_on_mode": "bookmark", "launch_url": "https://x.example.com/"}).status_code == 409
    assert member.put(url, {"sp_entity_id": SP, "acs_url": ACS}).status_code == 403
    assert super_admin.delete(url).status_code == 200


def test_import_sp_metadata_and_rejects_dtd(super_admin):
    md = (f'<md:EntityDescriptor xmlns:md="{P.NS["md"]}" entityID="https://x.example.com/sp"><md:SPSSODescriptor AuthnRequestsSigned="true" protocolSupportEnumeration="{P.NS["samlp"]}">'
          f'<md:AssertionConsumerService Binding="{P.BINDING_POST}" Location="https://x.example.com/acs" index="0" isDefault="true"/></md:SPSSODescriptor></md:EntityDescriptor>')
    r = super_admin.post("/admin/applications/saml/import-metadata", {"xml": md})
    assert r.status_code == 200 and r.json()["sp_entity_id"] == "https://x.example.com/sp" and r.json()["acs_url"] == "https://x.example.com/acs"
    evil = '<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]>' + md
    assert super_admin.post("/admin/applications/saml/import-metadata", {"xml": evil}).status_code == 422
    assert super_admin.post("/admin/applications/saml/import-metadata", {"xml": "<a/>"}).status_code == 422


# ---- IdP-initiated ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("signing,asserted,messaged", [("both", True, True), ("assertion", True, False), ("response", False, True)])
def test_idp_initiated_response_is_valid_for_an_independent_validator(super_admin, member, signing, asserted, messaged):
    aid, _ = saml_app(super_admin, signing=signing, attribute_mappings=[{"name": "email", "source": "email"}, {"name": "groups", "source": "groups"}])
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    r = member.post(f"/saml/apps/{aid}/respond")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["acs_url"] == ACS
    resp = validate(out["saml_response"], idp_cert(member)[0], request_id=None, assertions_signed=asserted, messages_signed=messaged)
    assert resp.get_nameid() == member.user.email
    assert resp.get_attributes()["email"] == [member.user.email]


def test_unassigned_inactive_and_hidden_are_refused(super_admin, member):
    aid, _ = saml_app(super_admin)
    assert member.post(f"/saml/apps/{aid}/respond").status_code == 403                        # require_assignment defaults on
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    assert member.post(f"/saml/apps/{aid}/respond").status_code == 200
    cur = super_admin.get(f"/admin/applications/{aid}").json()
    super_admin.put(f"/admin/applications/{aid}", {"name": cur["name"], "sign_on_mode": "saml", "status": "inactive"})
    assert member.post(f"/saml/apps/{aid}/respond").status_code == 403
    super_admin.put(f"/admin/applications/{aid}", {"name": cur["name"], "sign_on_mode": "saml", "visible": False})
    assert member.post(f"/saml/apps/{aid}/respond").status_code == 404
    assert Api().post(f"/saml/apps/{aid}/respond").status_code == 401


def test_tile_launches_through_the_ui_continue_page(super_admin, member):
    aid, _ = saml_app(super_admin)
    assert member.get("/me/apps").json()["items"] == []
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    item = member.get("/me/apps").json()["items"][0]
    assert item["launchable"] is True
    assert member.post(f"/me/apps/{aid}/launch").json()["url"].endswith(f"/saml/continue?app={aid}")


def test_persistent_name_id_is_stable_and_pairwise(super_admin, member):
    a1, _ = saml_app(super_admin, name="A", name_id_format="persistent")
    a2 = super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "saml"}).json()["id"]
    super_admin.put(f"/admin/applications/{a2}/saml", {"sp_entity_id": "https://other.example.com/meta", "acs_url": "https://other.example.com/acs", "name_id_format": "persistent"})
    for a in (a1, a2):
        assign(super_admin, {"id": a}, user_id=member.user.id)
    cert = idp_cert(member)[0]
    n1 = validate(member.post(f"/saml/apps/{a1}/respond").json()["saml_response"], cert).get_nameid()
    n1b = validate(member.post(f"/saml/apps/{a1}/respond").json()["saml_response"], cert).get_nameid()
    n2 = validate(member.post(f"/saml/apps/{a2}/respond").json()["saml_response"], cert, sp="https://other.example.com/meta", acs="https://other.example.com/acs").get_nameid()
    assert n1 == n1b and n1 != n2 and member.user.email not in n1


# ---- SP-initiated -----------------------------------------------------------------------------------------------

def test_sp_initiated_flow_is_single_use_and_in_response_to(super_admin, member, anon):
    aid, _ = saml_app(super_admin, default_relay_state="ignored-when-sp-sends-one")
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    r = sso(anon, authn_xml(acs=ACS, rid="_abc123"), relay="/deep/link")
    rid = rid_of(r)
    assert r.headers["location"].startswith("http://localhost:3000/saml/continue?")
    assert member.get(f"/saml/requests/{rid}").json()["application"] == "Wiki SAML"
    out = member.post(f"/saml/requests/{rid}/respond").json()
    assert out["relay_state"] == "/deep/link"
    validate(out["saml_response"], idp_cert(member)[0], request_id="_abc123")
    assert member.post(f"/saml/requests/{rid}/respond").status_code == 404           # replay
    assert member.get(f"/saml/requests/{rid}").status_code == 404


def test_post_binding_works_too(super_admin, member, anon):
    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    r = anon.c.post("/saml/sso", data={"SAMLRequest": base64.b64encode(authn_xml()).decode(), "RelayState": "x"}, follow_redirects=False)
    assert member.post(f"/saml/requests/{rid_of(r)}/respond").status_code == 200


def test_bad_requests_never_reach_the_sp(super_admin, anon):
    saml_app(super_admin)
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    cases = {
        "unknown issuer": authn_xml(issuer="https://nobody.example.com"),
        "other ACS": authn_xml(acs="https://evil.example.com/acs"),
        "expired": authn_xml(instant=old),
        "doctype": b'<!DOCTYPE a [<!ENTITY x "y">]>' + authn_xml(),
        "not authn request": b"<a/>",
        "bad id": authn_xml(rid="1 bad"),
    }
    for name, xml in cases.items():
        r = sso(anon, xml)
        assert r.status_code == 303 and error_of(r), name
    bomb = zlib.compressobj(wbits=-15)
    big = bomb.compress(b"<a>" + b"A" * 5_000_000 + b"</a>") + bomb.flush()
    assert error_of(anon.c.get("/saml/sso", params={"SAMLRequest": base64.b64encode(big).decode()}, follow_redirects=False))
    assert error_of(anon.c.get("/saml/sso", params={"SAMLRequest": "!!notbase64"}, follow_redirects=False))
    assert error_of(anon.c.get("/saml/sso", params={}, follow_redirects=False))
    assert error_of(sso(anon, authn_xml(), relay="x" * 600))


def test_force_authn_requires_a_fresh_sign_in(super_admin, member, anon):
    import time

    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    time.sleep(1.1)
    rid = rid_of(sso(anon, authn_xml(force=True)))
    assert member.get(f"/saml/requests/{rid}").json()["reauth_required"] is True
    r = member.post(f"/saml/requests/{rid}/respond")
    assert r.status_code == 403 and r.json()["detail"] == "reauthentication_required"
    assert member.get(f"/saml/requests/{rid}").status_code == 200                      # still usable after signing in again


# ---- signed AuthnRequests ---------------------------------------------------------------------------------------

def sp_keypair():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(65537, 2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sp")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=30)).sign(key, hashes.SHA256()))
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


def test_signed_requests_post_binding(super_admin, member, anon):
    from signxml import XMLSigner, methods
    from cryptography.hazmat.primitives import serialization

    key, cert = sp_keypair()
    aid, _ = saml_app(super_admin, sp_cert=cert, require_signed_requests=True)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    post = lambda xml: anon.c.post("/saml/sso", data={"SAMLRequest": base64.b64encode(xml).decode()}, follow_redirects=False)  # noqa: E731
    assert error_of(post(authn_xml())) == "signature"
    kpem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    root = etree.fromstring(authn_xml(rid="_signed1"))
    etree.SubElement(root, "{%s}Signature" % P.NS["ds"], Id="placeholder", nsmap={"ds": P.NS["ds"]})
    signed = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                       c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(root, key=kpem, cert=cert.encode(), reference_uri="_signed1")
    good = etree.tostring(signed)
    assert rid_of(post(good))
    tampered = good.replace(b'AssertionConsumerServiceURL', b'X') if b"AssertionConsumerServiceURL" in good else good.replace(b"<saml:Issuer", b" <saml:Issuer", 1)
    tampered = tampered.replace(SP.encode(), b"https://sp.example.com/meta ")  # change signed content
    assert error_of(post(tampered)) is not None
    other_key, other_cert = sp_keypair()
    root2 = etree.fromstring(authn_xml(rid="_signed2"))
    etree.SubElement(root2, "{%s}Signature" % P.NS["ds"], Id="placeholder", nsmap={"ds": P.NS["ds"]})
    forged = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                       c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(
        root2, key=other_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
        cert=other_cert.encode(), reference_uri="_signed2")
    assert error_of(post(etree.tostring(forged))) is not None                          # signed by someone else


def test_signed_requests_redirect_binding(super_admin, anon):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    key, cert = sp_keypair()
    saml_app(super_admin, sp_cert=cert, require_signed_requests=True)
    req = quote_plus(deflate(authn_xml()))
    alg = quote_plus(P.SIG_RSA_SHA256)
    signed_part = f"SAMLRequest={req}&SigAlg={alg}"
    sig = quote_plus(base64.b64encode(key.sign(signed_part.encode(), padding.PKCS1v15(), hashes.SHA256())).decode())
    assert rid_of(anon.c.get(f"/saml/sso?{signed_part}&Signature={sig}", follow_redirects=False))
    bad = quote_plus(base64.b64encode(b"x" * 256).decode())
    assert error_of(anon.c.get(f"/saml/sso?{signed_part}&Signature={bad}", follow_redirects=False))
    assert error_of(anon.c.get(f"/saml/sso?SAMLRequest={req}", follow_redirects=False))      # unsigned


# ---- key rotation -----------------------------------------------------------------------------------------------

def test_key_rotation_publishes_both_and_signs_with_the_new_one(super_admin, admin, member):
    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    old = idp_cert(member)[0]
    assert admin.post("/admin/applications/saml/rotate-key").status_code == 403
    assert super_admin.post("/admin/applications/saml/rotate-key").status_code == 200
    certs = idp_cert(member)
    assert len(certs) == 2 and certs[0] != old and old in certs
    out = member.post(f"/saml/apps/{aid}/respond").json()["saml_response"]
    validate(out, certs[0])                                                              # signed by the new key
    with pytest.raises(Exception):
        validate(out, old)                                                               # and not by the old one


def test_expression_can_read_the_users_names(db, super_admin, member):
    aid, _ = saml_app(super_admin, attribute_mappings=[{"name": "shout", "source": "expr:String.toUpperCase(user.firstName)"},
                                                       {"name": "who", "source": "expr:String.join(\" \", user.firstName, user.lastName)"}])
    pv = super_admin.get(f"/admin/applications/{aid}/saml/preview?user_id={member.user.id}").json()
    got = {a["name"]: a["values"] for a in pv["attributes"]}
    assert got["shout"] == [member.user.first_name.upper()]
    assert got["who"] == [f"{member.user.first_name} {member.user.last_name}"]


def test_error_redirects_carry_a_fixed_code_not_free_text(anon):
    r = anon.c.get("/saml/sso", params={"SAMLRequest": "!!notbase64"}, follow_redirects=False)
    assert error_of(r) == "invalid_request"


def test_a_signed_request_we_cannot_verify_is_refused(super_admin, member, anon):
    from signxml import XMLSigner, methods
    from cryptography.hazmat.primitives import serialization

    key, cert = sp_keypair()
    aid, _ = saml_app(super_admin)                       # no certificate registered, signing not required
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    root = etree.fromstring(authn_xml(rid="_nocert"))
    etree.SubElement(root, "{%s}Signature" % P.NS["ds"], Id="placeholder", nsmap={"ds": P.NS["ds"]})
    kpem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    signed = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                       c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(root, key=kpem, cert=cert.encode(), reference_uri="_nocert")
    r = anon.c.post("/saml/sso", data={"SAMLRequest": base64.b64encode(etree.tostring(signed)).decode()}, follow_redirects=False)
    assert error_of(r) == "signature"
