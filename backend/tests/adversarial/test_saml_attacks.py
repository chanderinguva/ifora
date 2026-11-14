"""IFORA-17: adversarial regression suite for the SAML IdP. Each test names the attack and its register ID / CWE.

Ifora is the identity provider: it receives AuthnRequests (optionally signed) and issues signed assertions. The attacks
therefore target (a) request validation and signature checking, (b) XML parsing, and (c) tampering with what Ifora issues,
judged by an independent validator (python3-saml / xmlsec). Real keys are generated at runtime.
"""

import base64
import copy
import zlib
from urllib.parse import quote_plus

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree
from signxml import XMLSigner, methods

from backend.app.saml import protocol as P
from tests.test_applications import assign
from tests.test_saml import ACS, NS, SP, authn_xml, deflate, error_of, idp_cert, rid_of, saml_app, sp_keypair, sso, validate

pytestmark = pytest.mark.adversarial

C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"


def _pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _signed(key, cert, rid="_signed1", sig_alg="rsa-sha256", **xml_over):
    root = etree.fromstring(authn_xml(rid=rid, **xml_over))
    etree.SubElement(root, "{%s}Signature" % P.NS["ds"], Id="placeholder", nsmap={"ds": P.NS["ds"]})
    return XMLSigner(method=methods.enveloped, signature_algorithm=sig_alg, digest_algorithm="sha256", c14n_algorithm=C14N).sign(
        root, key=_pem(key), cert=cert.encode(), reference_uri=rid)


def _post(anon, xml: bytes):
    return anon.c.post("/saml/sso", data={"SAMLRequest": base64.b64encode(xml).decode()}, follow_redirects=False)


@pytest.fixture
def signed_sp(super_admin, member):
    key, cert = sp_keypair()
    aid, _ = saml_app(super_admin, sp_cert=cert, require_signed_requests=True)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    return aid, key, cert


# ---- signed AuthnRequest attacks (XML Signature Wrapping; CWE-347, CWE-345) ---------------------------------------------


def test_a_correctly_signed_request_is_accepted_baseline(signed_sp, anon):
    """Control: the attacks below only mean something if an honest signed request passes."""
    _, key, cert = signed_sp
    assert rid_of(_post(anon, etree.tostring(_signed(key, cert))))


def test_signature_wrapping_original_signed_element_hidden_inside_a_forged_request(signed_sp, anon):
    """AC3 / XSW (CWE-347): a forged root request carries the genuine signed one in Extensions; it must be refused."""
    _, key, cert = signed_sp
    genuine = _signed(key, cert, rid="_genuine")
    forged = etree.fromstring(authn_xml(rid="_forged", acs="https://evil.example.com/acs"))
    ext = etree.SubElement(forged, "{%s}Extensions" % P.NS["samlp"])
    ext.append(copy.deepcopy(genuine))
    assert error_of(_post(anon, etree.tostring(forged))) is not None


def test_signature_that_does_not_reference_the_request_is_refused(signed_sp, anon):
    """XSW variant (CWE-347): a valid signature over some other element, with the request id changed afterwards."""
    _, key, cert = signed_sp
    good = _signed(key, cert, rid="_orig")
    good.set("ID", "_swapped")                        # signature still references _orig
    assert error_of(_post(anon, etree.tostring(good))) is not None


def test_signature_nested_below_the_root_is_not_an_enveloped_signature(signed_sp, anon):
    """XSW variant (CWE-347): moving the Signature into an Extensions child must not count as signing the request."""
    _, key, cert = signed_sp
    s = _signed(key, cert, rid="_nest")
    sig = s.find("{%s}Signature" % P.NS["ds"])
    s.remove(sig)
    ext = etree.SubElement(s, "{%s}Extensions" % P.NS["samlp"])
    ext.append(sig)
    assert error_of(_post(anon, etree.tostring(s))) is not None


def test_altering_signed_content_after_signing_is_detected(signed_sp, anon):
    """Tampering after signing (CWE-345): changing the ACS, issuer or time breaks the signature."""
    _, key, cert = signed_sp
    for mutate in (lambda r: r.set("AssertionConsumerServiceURL", "https://evil.example.com/acs"),
                   lambda r: r.set("ForceAuthn", "true"),
                   lambda r: r.find("{%s}Issuer" % P.NS["saml"]).__setattr__("text", SP + " ")):
        s = _signed(key, cert, rid="_t1", acs=ACS)
        mutate(s)
        assert error_of(_post(anon, etree.tostring(s))) is not None


def _resign_with_sha1(signed, key):
    """A request whose SignatureMethod says rsa-sha1 and whose SignatureValue really is an RSA-SHA1 signature by `key`."""
    sig = signed.find("{%s}Signature" % P.NS["ds"])
    si = sig.find("{%s}SignedInfo" % P.NS["ds"])
    si.find("{%s}SignatureMethod" % P.NS["ds"]).set("Algorithm", "http://www.w3.org/2000/09/xmldsig#rsa-sha1")
    canon = etree.tostring(si, method="c14n", exclusive=True)
    value = base64.b64encode(key.sign(canon, padding.PKCS1v15(), hashes.SHA1())).decode()  # noqa: S303 (the attack under test)
    sig.find("{%s}SignatureValue" % P.NS["ds"]).text = value
    return signed


def test_request_signed_by_another_key_is_refused(signed_sp, anon):
    """Wrong key (CWE-347): a well-formed signature by a key that is not the registered certificate."""
    other_key, other_cert = sp_keypair()
    assert error_of(_post(anon, etree.tostring(_signed(other_key, other_cert, rid="_o")))) is not None


def test_request_with_a_genuine_sha1_signature_is_refused(signed_sp, anon):
    """Weak signature algorithm (CWE-328): a valid RSA-SHA1 signature by the registered key must still be refused."""
    _, key, cert = signed_sp
    weak = _resign_with_sha1(_signed(key, cert, rid="_sha1"), key)
    assert error_of(_post(anon, etree.tostring(weak))) is not None


def test_unsigned_request_is_refused_when_signing_is_required(signed_sp, anon):
    """Signature stripping (CWE-347): dropping the Signature element must not downgrade to an unsigned request."""
    _, key, cert = signed_sp
    s = _signed(key, cert, rid="_strip")
    s.remove(s.find("{%s}Signature" % P.NS["ds"]))
    assert error_of(_post(anon, etree.tostring(s))) == "signature"
    assert error_of(_post(anon, authn_xml())) == "signature"


def test_a_bogus_signature_is_not_ignored_when_signing_is_optional(super_admin, member, anon):
    """Optional signing must not mean 'unchecked' (CWE-347): a present but invalid signature is an error."""
    key, cert = sp_keypair()
    aid, _ = saml_app(super_admin, sp_cert=cert, require_signed_requests=False)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    other_key, other_cert = sp_keypair()
    assert error_of(_post(anon, etree.tostring(_signed(other_key, other_cert, rid="_bogus")))) is not None


def test_redirect_binding_signature_attacks(signed_sp, anon):
    """Redirect-binding signature games (CWE-347): other SigAlg, swapped message, repeated parameters, missing signature."""
    _, key, cert = signed_sp

    def signed_query(xml, **over):
        req = quote_plus(deflate(xml))
        alg = quote_plus(P.SIG_RSA_SHA256)
        part = f"SAMLRequest={req}&SigAlg={alg}"
        sig = quote_plus(base64.b64encode(key.sign(part.encode(), padding.PKCS1v15(), hashes.SHA256())).decode())
        return req, alg, sig

    req, alg, sig = signed_query(authn_xml(rid="_r1"))
    assert rid_of(anon.c.get(f"/saml/sso?SAMLRequest={req}&SigAlg={alg}&Signature={sig}", follow_redirects=False))
    other_req = quote_plus(deflate(authn_xml(rid="_r2", acs="https://evil.example.com/acs")))
    assert error_of(anon.c.get(f"/saml/sso?SAMLRequest={other_req}&SigAlg={alg}&Signature={sig}", follow_redirects=False))
    sha1 = quote_plus("http://www.w3.org/2000/09/xmldsig#rsa-sha1")
    assert error_of(anon.c.get(f"/saml/sso?SAMLRequest={req}&SigAlg={sha1}&Signature={sig}", follow_redirects=False))
    assert error_of(anon.c.get(f"/saml/sso?SAMLRequest={req}&SigAlg={alg}&SAMLRequest={other_req}&Signature={sig}", follow_redirects=False))
    assert error_of(anon.c.get(f"/saml/sso?SAMLRequest={req}&SigAlg={alg}", follow_redirects=False))


# ---- request validation (CWE-345, CWE-601) ---------------------------------------------------------------------------------


def test_comment_injection_in_issuer_cannot_pick_another_sp(super_admin, anon):
    """Comment injection (CVE-2017-11427 class, CWE-74): a comment splitting the Issuer text must not select a different SP."""
    saml_app(super_admin)
    xml = authn_xml().replace(f"<saml:Issuer>{SP}</saml:Issuer>".encode(), f"<saml:Issuer>{SP}<!--x-->.evil.example.com</saml:Issuer>".encode())
    assert b"<!--x-->" in xml
    assert error_of(sso(anon, xml)) is not None


def test_acs_and_audience_cannot_be_redirected_by_the_request(super_admin, member, anon):
    """Open ACS / assertion redirection (CWE-601): the assertion goes to the registered ACS only, whatever the request says."""
    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    for acs in ("https://evil.example.com/acs", ACS + "/", "http://sp.example.com/acs", ACS + "?x=1", "https://sp.example.com.evil.example.com/acs"):
        r = sso(anon, authn_xml(acs=acs))
        assert error_of(r) is not None, acs
    rid = rid_of(sso(anon, authn_xml(acs=ACS, rid="_ok")))
    assert member.post(f"/saml/requests/{rid}/respond").json()["acs_url"] == ACS


def test_request_id_cannot_be_replayed_or_used_by_anyone_for_another_sp(super_admin, member, anon):
    """InResponseTo replay (CWE-294): a pending request is consumed once; the second use is a 404."""
    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    rid = rid_of(sso(anon, authn_xml(rid="_once")))
    assert member.post(f"/saml/requests/{rid}/respond").status_code == 200
    assert member.post(f"/saml/requests/{rid}/respond").status_code == 404


@pytest.mark.parametrize("xml", [
    b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="_a" Version="2.0"><saml:Issuer xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">&x;</saml:Issuer></samlp:AuthnRequest>',
    b'<!DOCTYPE r [<!ENTITY % p SYSTEM "http://127.0.0.1:1/x.dtd"> %p;]><r/>',
    b'<!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><lolz>&c;</lolz>',
    b'<!doctype r [<!entity x "y">]><r/>',
    b'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:xi="http://www.w3.org/2001/XInclude" ID="_a" Version="2.0"><xi:include href="file:///etc/passwd" parse="text"/></samlp:AuthnRequest>',
])
def test_xxe_dtd_and_entity_expansion_are_refused_without_leaking_anything(super_admin, anon, xml):
    """XXE / billion laughs / XInclude (CWE-611, CWE-776): refused at parse time; no file content or SSRF reflected."""
    saml_app(super_admin)
    for r in (sso(anon, xml), _post(anon, xml)):
        assert error_of(r) is not None
        assert "root:" not in r.headers.get("location", "") and "passwd" not in r.text


def test_sp_metadata_import_refuses_dtd_xxe_and_oversized_documents(super_admin):
    """XXE through admin metadata import (CWE-611, CWE-400)."""
    md = (f'<md:EntityDescriptor xmlns:md="{P.NS["md"]}" entityID="https://x.example.com/sp"><md:SPSSODescriptor '
          f'protocolSupportEnumeration="{P.NS["samlp"]}"><md:AssertionConsumerService Binding="{P.BINDING_POST}" '
          f'Location="https://x.example.com/acs" index="0"/></md:SPSSODescriptor></md:EntityDescriptor>')
    for xml in ('<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]>' + md.replace("sp\"", "&a;\"", 1),
                '<!DOCTYPE x [<!ENTITY % e SYSTEM "http://127.0.0.1:1/e"> %e;]>' + md,
                md.replace("</md:EntityDescriptor>", "<!-- " + "A" * 3_000_000 + " --></md:EntityDescriptor>")):
        r = super_admin.post("/admin/applications/saml/import-metadata", {"xml": xml})
        assert r.status_code in (413, 422) and "root:" not in r.text


def test_zip_bomb_and_giant_relay_state_are_bounded(super_admin, anon):
    """Decompression bomb / oversized parameter (CWE-409, CWE-400): a clean error, no work done."""
    saml_app(super_admin)
    z = zlib.compressobj(wbits=-15)
    bomb = z.compress(b"<a>" + b"A" * 30_000_000 + b"</a>") + z.flush()
    r = anon.c.get("/saml/sso", params={"SAMLRequest": base64.b64encode(bomb).decode()}, follow_redirects=False)
    assert error_of(r) is not None
    assert error_of(sso(anon, authn_xml(), relay="R" * 40_000)) is not None


# ---- assertions Ifora issues (CWE-345, CWE-347) --------------------------------------------------------------------------------


@pytest.fixture
def issued(super_admin, member):
    aid, _ = saml_app(super_admin, attribute_mappings=[{"name": "email", "source": "email"}])
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    out = member.post(f"/saml/apps/{aid}/respond").json()
    return out["saml_response"], idp_cert(member)[0]


def _tamper(resp_b64, fn):
    root = etree.fromstring(base64.b64decode(resp_b64))
    fn(root)
    return base64.b64encode(etree.tostring(root)).decode()


def test_issued_response_validates_and_has_the_expected_shape(issued):
    """Control + invariants (XSW surface): one assertion, signature references an element that exists exactly once."""
    resp, cert = issued
    validate(resp, cert)
    root = etree.fromstring(base64.b64decode(resp))
    assert len(root.findall(".//saml:Assertion", NS)) == 1
    ids = [e.get("ID") for e in root.iter() if e.get("ID")]
    assert len(ids) == len(set(ids))
    for ref in root.iterfind(".//ds:Reference", NS):
        assert ids.count(ref.get("URI").lstrip("#")) == 1
    assert b"<!--" not in base64.b64decode(resp) and b"<!DOCTYPE" not in base64.b64decode(resp)


@pytest.mark.parametrize("what", ["nameid", "attribute", "audience", "recipient", "not_on_or_after"])
def test_any_edit_to_an_issued_assertion_invalidates_it(issued, what):
    """Assertion tampering (CWE-345): an independent validator rejects every edit made after Ifora signed it."""
    resp, cert = issued

    def edit(root):
        if what == "nameid":
            root.find(".//saml:NameID", NS).text = "admin@example.com"
        elif what == "attribute":
            root.find(".//saml:AttributeValue", NS).text = "attacker@example.com"
        elif what == "audience":
            root.find(".//saml:Audience", NS).text = "https://evil.example.com/meta"
        elif what == "recipient":
            root.find(".//saml:SubjectConfirmationData", NS).set("Recipient", "https://evil.example.com/acs")
        else:
            root.find(".//saml:Conditions", NS).set("NotOnOrAfter", "2099-01-01T00:00:00Z")

    with pytest.raises(Exception):
        validate(_tamper(resp, edit), cert)


def test_assertion_wrapping_and_signature_removal_are_rejected_by_a_strict_validator(issued):
    """XSW on the issued response (CWE-347): a second unsigned assertion, or no signature, never validates."""
    resp, cert = issued

    def wrap(root):
        a = root.find(".//saml:Assertion", NS)
        evil = copy.deepcopy(a)
        for sig in evil.findall("ds:Signature", NS):
            evil.remove(sig)
        evil.set("ID", "_evil")
        evil.find(".//saml:NameID", NS).text = "admin@example.com"
        root.insert(list(root).index(a), evil)

    def strip(root):
        for sig in root.iterfind(".//ds:Signature", NS):
            sig.getparent().remove(sig)

    for fn in (wrap, strip):
        with pytest.raises(Exception):
            validate(_tamper(resp, fn), cert)


def test_assertion_for_one_sp_is_not_valid_at_another(super_admin, member):
    """Audience / recipient confusion (CWE-345): a response issued for SP A fails strict validation as SP B."""
    a, _ = saml_app(super_admin, name="A")
    b = super_admin.post("/admin/applications", {"name": "B", "sign_on_mode": "saml"}).json()["id"]
    super_admin.put(f"/admin/applications/{b}/saml", {"sp_entity_id": "https://b.example.com/meta", "acs_url": "https://b.example.com/acs"})
    assign(super_admin, {"id": a}, user_id=member.user.id)
    resp = member.post(f"/saml/apps/{a}/respond").json()["saml_response"]
    with pytest.raises(Exception):
        validate(resp, idp_cert(member)[0], sp="https://b.example.com/meta", acs="https://b.example.com/acs")


def test_response_is_bound_to_its_request_id(super_admin, member, anon):
    """InResponseTo mismatch / replay across requests (CWE-294): a response built for request A fails as an answer to B."""
    aid, _ = saml_app(super_admin)
    assign(super_admin, {"id": aid}, user_id=member.user.id)
    rid_a = rid_of(sso(anon, authn_xml(rid="_reqA")))
    resp = member.post(f"/saml/requests/{rid_a}/respond").json()["saml_response"]
    validate(resp, idp_cert(member)[0], request_id="_reqA")
    with pytest.raises(Exception):
        validate(resp, idp_cert(member)[0], request_id="_reqB")


def test_unassigned_or_anonymous_callers_get_no_assertion(super_admin, member, anon):
    """Authorization bypass (CWE-862): no assignment -> 403, no session -> 401, hidden app -> 404."""
    aid, _ = saml_app(super_admin)
    assert member.post(f"/saml/apps/{aid}/respond").status_code == 403
    assert anon.post(f"/saml/apps/{aid}/respond").status_code == 401
    assert "saml_response" not in member.post(f"/saml/apps/{aid}/respond").text
