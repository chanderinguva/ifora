"""A software WebAuthn authenticator for tests: real P-256 keys, real attestation/assertion encoding."""

import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

RP_ID = "localhost"
ORIGIN = "http://localhost:3000"
UP, UV, AT = 0x01, 0x04, 0x40


class FakeAuthenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.counter = 0
        self.user_handle = None  # b64url string, learned at registration

    @property
    def id(self) -> str:
        return bytes_to_base64url(self.cred_id)

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def _client(self, kind, challenge, origin):
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def register(self, options, origin=ORIGIN, rp_id=RP_ID, uv=True, challenge=None):
        self.user_handle = options["user"]["id"]
        client = self._client("webauthn.create", challenge or options["challenge"], origin)
        flags = UP | AT | (UV if uv else 0)
        attested = bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + self._cose()
        auth = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + self.counter.to_bytes(4, "big") + attested
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client),
                "attestationObject": bytes_to_base64url(att),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def assertion(self, options, origin=ORIGIN, rp_id=RP_ID, uv=True, bump=True, key=None, user_handle="__own__",
                  challenge=None, counter=None):
        if counter is not None:
            self.counter = counter
        elif bump:
            self.counter += 1
        client = self._client("webauthn.get", challenge or options["challenge"], origin)
        flags = UP | (UV if uv else 0)
        auth = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + self.counter.to_bytes(4, "big")
        sig = (key or self.key).sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        handle = self.user_handle if user_handle == "__own__" else user_handle
        resp = {
            "clientDataJSON": bytes_to_base64url(client),
            "authenticatorData": bytes_to_base64url(auth),
            "signature": bytes_to_base64url(sig),
        }
        if handle:
            resp["userHandle"] = handle
        return {"id": self.id, "rawId": self.id, "type": "public-key", "response": resp, "clientExtensionResults": {}}
