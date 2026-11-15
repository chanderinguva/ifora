"""SAML 2.0 messages: safe parsing of AuthnRequests, response/assertion construction, IdP metadata.

Signing and signature verification are done by signxml (we never canonicalise or hash XML ourselves). Elements are
built with lxml's tree API, never by string concatenation, so no user-controlled value can add markup.
"""

import base64
import hashlib
import hmac
import re
import secrets
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import unquote_plus

from lxml import etree
from signxml import XMLSigner, XMLVerifier, methods
from signxml.exceptions import InvalidSignature

from backend.app.config import settings
from backend.app.tenancy import issuer as tenant_issuer

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}
FMT_EMAIL = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
FMT_PERSISTENT = "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"
FMT_UNSPECIFIED = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
BINDING_POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
BINDING_REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
SIG_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
MAX_MESSAGE_BYTES = 256 * 1024
_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,254}$")
CLOCK_SKEW = timedelta(minutes=5)


class SamlError(ValueError):
    """The request cannot be honoured. The message is safe to show the user; nothing is sent to the SP."""


def q(prefix: str, tag: str) -> str:
    return "{%s}%s" % (NS[prefix], tag)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def idp_entity_id() -> str:
    if settings.TENANT_RESOLUTION == "host":  # one global entity id would be shared by every tenant
        return tenant_issuer().rstrip("/") + "/saml/idp"
    return settings.SAML_ENTITY_ID or settings.OIDC_ISSUER.rstrip("/") + "/saml/idp"


def sso_url() -> str:
    return tenant_issuer().rstrip("/") + "/saml/sso"


# ---- parsing ----------------------------------------------------------------------------------------------------

def parse_xml(raw: bytes) -> etree._Element:
    """XXE/entity-expansion safe: no DTDs, no entities, no network, comments dropped (they can split text nodes)."""
    if len(raw) > MAX_MESSAGE_BYTES:
        raise SamlError("The SAML message is too large")
    head = raw.upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise SamlError("DTDs are not allowed in SAML messages")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False,
                             remove_comments=True, remove_pis=True)
    try:
        return etree.fromstring(raw, parser)
    except etree.XMLSyntaxError:
        raise SamlError("The SAML message is not valid XML")


def inflate(data: bytes) -> bytes:
    d = zlib.decompressobj(-15)
    out = d.decompress(data, MAX_MESSAGE_BYTES + 1)  # bounded: a zip bomb cannot exceed the cap
    if len(out) > MAX_MESSAGE_BYTES or d.unconsumed_tail:
        raise SamlError("The SAML message is too large")
    return out


@dataclass
class AuthnRequest:
    id: str
    issuer: str
    acs_url: Optional[str]
    force_authn: bool
    is_passive: bool
    root: etree._Element


def parse_authn_request(raw: bytes, now: Optional[datetime] = None) -> AuthnRequest:
    now = now or datetime.now(timezone.utc)
    root = parse_xml(raw)
    if root.tag != q("samlp", "AuthnRequest"):
        raise SamlError("Expected a SAML AuthnRequest")
    if root.get("Version") != "2.0":
        raise SamlError("Only SAML 2.0 is supported")
    rid = root.get("ID") or ""
    if not _ID.match(rid):
        raise SamlError("The request has no valid ID")
    issuer = root.find(q("saml", "Issuer"))
    if issuer is None or not (issuer.text or "").strip():
        raise SamlError("The request has no Issuer")
    dest = root.get("Destination")
    if dest and dest != sso_url():
        raise SamlError("The request is addressed to a different identity provider")
    inst = root.get("IssueInstant")
    if inst:
        try:
            t = datetime.strptime(inst[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            raise SamlError("Invalid IssueInstant")
        if t < now - timedelta(minutes=10) or t > now + CLOCK_SKEW:
            raise SamlError("The request has expired or its clock is wrong")
    return AuthnRequest(id=rid, issuer=issuer.text.strip(), acs_url=root.get("AssertionConsumerServiceURL"),
                        force_authn=(root.get("ForceAuthn") or "").lower() in ("true", "1"),
                        is_passive=(root.get("IsPassive") or "").lower() in ("true", "1"), root=root)


def verify_post_signature(root: etree._Element, cert_pem: str) -> None:
    try:
        res = XMLVerifier().verify(root, x509_cert=cert_pem, expect_references=1)
    except InvalidSignature:
        raise SamlError("The request signature is not valid")
    except Exception:  # signxml raises several types for malformed signatures; all mean "not verified"
        raise SamlError("The request signature could not be verified")
    signed = res[0] if isinstance(res, list) else res
    rid = root.get("ID")
    sig = root.find(q("ds", "Signature"))
    # The signature must be the request's own enveloped signature and cover exactly this element (no wrapping).
    if not rid or sig is None or signed.signed_xml.get("ID") != rid or signed.signed_xml.tag != root.tag:
        raise SamlError("The request signature does not cover the request")


def verify_redirect_signature(raw_query: str, cert_pem: str) -> None:
    """HTTP-Redirect binding: the signature is over the URL-encoded query string exactly as sent (SAML Bindings 3.4.4.1)."""
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature as CryptoInvalid
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    parts = {}
    for seg in raw_query.split("&"):
        k, _, v = seg.partition("=")
        if k in parts:
            raise SamlError("Repeated parameter")
        parts[k] = v
    if "Signature" not in parts or "SigAlg" not in parts or unquote_plus(parts["SigAlg"]) != SIG_RSA_SHA256:
        raise SamlError("Only rsa-sha256 signed requests are accepted")
    signed = "&".join(f"{k}={parts[k]}" for k in ("SAMLRequest", "RelayState", "SigAlg") if k in parts)
    try:
        pub = x509.load_pem_x509_certificate(cert_pem.encode()).public_key()
        if not isinstance(pub, rsa.RSAPublicKey):
            raise SamlError("The registered certificate is not an RSA certificate")
        pub.verify(base64.b64decode(unquote_plus(parts["Signature"])), signed.encode(), padding.PKCS1v15(), hashes.SHA256())
    except (CryptoInvalid, ValueError):
        raise SamlError("The request signature is not valid")


def is_signed(root: etree._Element) -> bool:
    return root.find(q("ds", "Signature")) is not None


# ---- responses --------------------------------------------------------------------------------------------------

def new_id() -> str:
    return "_" + secrets.token_hex(20)


def persistent_name_id(sp_entity_id: str, user_id: int) -> str:
    """Pairwise: different per SP, so two SPs cannot correlate a user; stable over time."""
    mac = hmac.new(settings.SECRET_KEY.encode(), f"saml-persistent|{sp_entity_id}|{user_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def _sig_placeholder(parent: etree._Element) -> None:
    etree.SubElement(parent, q("ds", "Signature"), Id="placeholder", nsmap={"ds": NS["ds"]})


def build_response(*, sp_entity_id: str, acs_url: str, audience: str, name_id: str, name_id_format: str, in_response_to: Optional[str],
                   attributes: List[tuple], auth_time: datetime, authn_context: str, validity: int, sign_assertion: bool,
                   sign_response: bool, key_pem: bytes, cert_pem: bytes, now: Optional[datetime] = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    issuer = idp_entity_id()
    rid, aid = new_id(), new_id()
    nsmap = {"samlp": NS["samlp"], "saml": NS["saml"]}
    resp = etree.Element(q("samlp", "Response"), nsmap=nsmap, ID=rid, Version="2.0", IssueInstant=iso(now), Destination=acs_url)
    if in_response_to:
        resp.set("InResponseTo", in_response_to)
    etree.SubElement(resp, q("saml", "Issuer")).text = issuer
    if sign_response:
        _sig_placeholder(resp)
    status = etree.SubElement(resp, q("samlp", "Status"))
    etree.SubElement(status, q("samlp", "StatusCode"), Value="urn:oasis:names:tc:SAML:2.0:status:Success")

    a = etree.SubElement(resp, q("saml", "Assertion"), ID=aid, Version="2.0", IssueInstant=iso(now))
    etree.SubElement(a, q("saml", "Issuer")).text = issuer
    if sign_assertion:
        _sig_placeholder(a)
    subj = etree.SubElement(a, q("saml", "Subject"))
    nid = etree.SubElement(subj, q("saml", "NameID"), Format=name_id_format)
    nid.text = name_id
    if name_id_format == FMT_PERSISTENT:
        nid.set("SPNameQualifier", sp_entity_id)
    sc = etree.SubElement(subj, q("saml", "SubjectConfirmation"), Method="urn:oasis:names:tc:SAML:2.0:cm:bearer")
    scd = etree.SubElement(sc, q("saml", "SubjectConfirmationData"), NotOnOrAfter=iso(now + timedelta(seconds=validity)), Recipient=acs_url)
    if in_response_to:
        scd.set("InResponseTo", in_response_to)
    cond = etree.SubElement(a, q("saml", "Conditions"), NotBefore=iso(now - timedelta(seconds=30)), NotOnOrAfter=iso(now + timedelta(seconds=validity)))
    etree.SubElement(etree.SubElement(cond, q("saml", "AudienceRestriction")), q("saml", "Audience")).text = audience
    authn = etree.SubElement(a, q("saml", "AuthnStatement"), AuthnInstant=iso(auth_time), SessionIndex=new_id())
    etree.SubElement(etree.SubElement(authn, q("saml", "AuthnContext")), q("saml", "AuthnContextClassRef")).text = authn_context
    stmt = etree.SubElement(a, q("saml", "AttributeStatement"))
    for name, values in attributes:
        at = etree.SubElement(stmt, q("saml", "Attribute"), Name=name, NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:basic")
        for v in values:
            etree.SubElement(at, q("saml", "AttributeValue")).text = v

    signer = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                       c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
    if sign_assertion:
        resp.replace(a, signer.sign(a, key=key_pem, cert=cert_pem, reference_uri=aid))
    out = signer.sign(resp, key=key_pem, cert=cert_pem, reference_uri=rid) if sign_response else resp
    return etree.tostring(out)


# ---- metadata ---------------------------------------------------------------------------------------------------

def idp_metadata(certs: List[str]) -> bytes:
    root = etree.Element(q("md", "EntityDescriptor"), nsmap={"md": NS["md"], "ds": NS["ds"]}, entityID=idp_entity_id())
    idp = etree.SubElement(root, q("md", "IDPSSODescriptor"), WantAuthnRequestsSigned="false", protocolSupportEnumeration=NS["samlp"])
    for cert in certs:
        kd = etree.SubElement(idp, q("md", "KeyDescriptor"), use="signing")
        etree.SubElement(etree.SubElement(etree.SubElement(kd, q("ds", "KeyInfo")), q("ds", "X509Data")), q("ds", "X509Certificate")).text = cert
    etree.SubElement(idp, q("md", "NameIDFormat")).text = FMT_EMAIL
    etree.SubElement(idp, q("md", "NameIDFormat")).text = FMT_PERSISTENT
    for binding in (BINDING_REDIRECT, BINDING_POST):
        etree.SubElement(idp, q("md", "SingleSignOnService"), Binding=binding, Location=sso_url())
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def parse_sp_metadata(raw: bytes) -> dict:
    """Pull entityID, the HTTP-POST ACS and the signing certificate out of SP metadata (nothing is fetched)."""
    root = parse_xml(raw)
    if root.tag == q("md", "EntitiesDescriptor"):
        kids = root.findall(q("md", "EntityDescriptor"))
        if len(kids) != 1:
            raise SamlError("The metadata must describe exactly one service provider")
        root = kids[0]
    if root.tag != q("md", "EntityDescriptor") or not root.get("entityID"):
        raise SamlError("Expected SAML EntityDescriptor metadata")
    sp = root.find(q("md", "SPSSODescriptor"))
    if sp is None:
        raise SamlError("The metadata has no SPSSODescriptor")
    acs = [e for e in sp.findall(q("md", "AssertionConsumerService")) if e.get("Binding") == BINDING_POST and e.get("Location")]
    if not acs:
        raise SamlError("The metadata has no HTTP-POST AssertionConsumerService")
    default = next((e for e in acs if e.get("isDefault") == "true"), acs[0])
    cert = None
    for kd in sp.findall(q("md", "KeyDescriptor")):
        if kd.get("use") in (None, "signing"):
            c = kd.find(".//" + q("ds", "X509Certificate"))
            if c is not None and c.text:
                b = "".join(c.text.split())
                cert = "-----BEGIN CERTIFICATE-----\n" + "\n".join(b[i:i + 64] for i in range(0, len(b), 64)) + "\n-----END CERTIFICATE-----\n"
                break
    return {"sp_entity_id": root.get("entityID"), "acs_url": default.get("Location"), "sp_cert": cert,
            "wants_signed_requests": (sp.get("AuthnRequestsSigned") or "").lower() == "true"}
