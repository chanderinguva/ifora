#!/usr/bin/env python3
"""Prepare a local TLS OpenBao deployment; initialize and configure without printing secrets.

Python standard library + local openssl. No customer credentials or root token
are sent anywhere except the explicitly selected loopback HTTPS endpoint.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler

REPO = Path(__file__).resolve().parents[1]


def write(path, content, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as f:
        f.write(content)


def request(url, ca, path, body=None, token=None, method="POST"):
    context = ssl.create_default_context(cafile=str(ca))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    req = Request(url.rstrip("/") + "/v1/" + path, data=json.dumps(body).encode() if body is not None else None,
                  headers=headers, method=method)
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())
    try:
        with opener.open(req, timeout=10) as r:
            return json.loads(r.read(262144)) if r.status != 204 else {}
    except (HTTPError, URLError):
        raise RuntimeError("OpenBao operation failed. Check its status, TLS certificate and operator permission; no response body was logged.") from None


def prepare(directory, environment):
    if directory == Path.home() or directory == REPO or REPO in directory.parents:
        raise RuntimeError("Choose a dedicated directory outside the repository")
    if directory.exists() and any(directory.iterdir()):
        raise RuntimeError("Preparation requires a new empty directory; existing keys were not changed")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    def openssl(*args):
        subprocess.run(["openssl", *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    openssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256", "-days", "365",
            "-subj", "/CN=Ifora " + environment + " OpenBao CA", "-keyout", str(directory / "ca.key"),
            "-out", str(directory / "ca.crt"))
    openssl("req", "-newkey", "rsa:3072", "-nodes", "-sha256", "-subj", "/CN=openbao",
            "-keyout", str(directory / "server.key"), "-out", str(directory / "server.csr"))
    write(directory / "server.ext", "subjectAltName=DNS:openbao,DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n")
    openssl("x509", "-req", "-in", str(directory / "server.csr"), "-CA", str(directory / "ca.crt"),
            "-CAkey", str(directory / "ca.key"), "-CAcreateserial", "-days", "365", "-sha256",
            "-extfile", str(directory / "server.ext"), "-out", str(directory / "server.crt"))
    for name in ("ca.crt", "server.crt", "server.key"):
        # Container readers use individual bind mounts. Host access remains blocked
        # by the enclosing 0700 directory; the CA private key is never mounted.
        (directory / name).chmod(0o644)
    (directory / "ca.key").chmod(0o600)
    write(directory / "server.hcl", 'ui = false\ndisable_mlock = true\napi_addr = "https://openbao:8200"\ncluster_addr = "https://openbao:8201"\n'
          'audit "file" "ifora-file" {\n  options {\n    file_path = "/openbao/audit/audit.log"\n  }\n}\n'
          'storage "raft" {\n  path = "/openbao/data"\n  node_id = "ifora-' + environment + '"\n}\n'
          'listener "tcp" {\n  address = "0.0.0.0:8200"\n  tls_cert_file = "/openbao/tls/server.crt"\n  tls_key_file = "/openbao/tls/server.key"\n}\n', 0o644)
    for service in ("api", "worker"):
        write(directory / (service + "-role-id"), "", 0o644)
        write(directory / (service + "-secret-id"), "", 0o644)
    write(directory / "ifora-openbao.json", json.dumps({"environment": environment, "schema": 1}))
    print("Prepared TLS configuration and empty application credential files in", directory)
    print("Keep this directory private. The CA expires in 365 days; plan certificate renewal.")


def configure(url, directory, token):
    mounts = request(url, directory / "ca.crt", "sys/mounts", token=token, method="GET")
    if "transit/" not in mounts.get("data", mounts):
        request(url, directory / "ca.crt", "sys/mounts/transit", {"type": "transit"}, token)
    request(url, directory / "ca.crt", "transit/keys/ifora-connections", {"type": "aes256-gcm96", "exportable": False, "allow_plaintext_backup": False}, token)
    auths = request(url, directory / "ca.crt", "sys/auth", token=token, method="GET")
    if "approle/" not in auths.get("data", auths):
        request(url, directory / "ca.crt", "sys/auth/approle", {"type": "approle"}, token)
    policy = 'path "transit/encrypt/ifora-connections" { capabilities = ["update"] }\npath "transit/decrypt/ifora-connections" { capabilities = ["update"] }\n'
    for service in ("api", "worker"):
        name = "ifora-" + service
        request(url, directory / "ca.crt", "sys/policies/acl/" + name, {"policy": policy}, token)
        request(url, directory / "ca.crt", "auth/approle/role/" + name,
                {"token_policies": [name], "token_ttl": "10m", "token_max_ttl": "30m", "secret_id_ttl": "720h"}, token)
        role = request(url, directory / "ca.crt", "auth/approle/role/" + name + "/role-id", token=token, method="GET")["data"]["role_id"]
        secret = request(url, directory / "ca.crt", "auth/approle/role/" + name + "/secret-id", {}, token)["data"]["secret_id"]
        for suffix, value in (("role-id", role), ("secret-id", secret)):
            # Replace atomically; readers never observe a partly written credential.
            dest = directory / (service + "-" + suffix)
            temporary = dest.with_suffix(".new")
            write(temporary, value + "\n", 0o644)
            temporary.replace(dest)
    print("Configured AES-256-GCM Transit, audit logging and separate least-privilege API/worker AppRoles.")
    print("AppRole secret IDs expire in 30 days. Rotate them before expiry and recreate application containers.")
    print("No root token was written to an application credential file.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["prepare", "init", "unseal", "configure", "status", "revoke-token"])
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--environment", choices=["dev", "demo"], default="dev")
    p.add_argument("--url", default="https://localhost:18200")
    args = p.parse_args()
    directory = args.directory.expanduser().resolve()
    u = urlsplit(args.url)
    if u.scheme != "https" or u.hostname not in ("localhost", "127.0.0.1") or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise RuntimeError("Use a loopback HTTPS URL, never a public hostname")
    if args.command == "prepare":
        prepare(directory, args.environment)
        return
    if not (directory / "ifora-openbao.json").is_file() or directory.stat().st_mode & 0o077:
        raise RuntimeError("Use the prepared private directory (mode 0700)")
    if args.command == "init":
        recovery = directory / "operator-recovery.json"
        if recovery.exists():
            raise RuntimeError("Recovery file already exists; initialization was not attempted")
        result = request(args.url, directory / "ca.crt", "sys/init", {"secret_shares": 3, "secret_threshold": 2}, method="PUT")
        write(recovery, json.dumps(result, indent=2))
        print("Initialized. Recovery material saved mode 0600:", recovery)
        print("Move recovery keys and initial root token to secure offline storage; do not mount them into Ifora.")
    elif args.command == "unseal":
        for _ in range(2):
            response = request(args.url, directory / "ca.crt", "sys/unseal", {"key": getpass.getpass("Unseal key (hidden): ")}, method="PUT")
            if not response["sealed"]:
                print("OpenBao unsealed.")
                return
        print("OpenBao is still sealed; verify the keys and inspect operator status.")
    elif args.command == "configure":
        configure(args.url, directory, getpass.getpass("Operator token (hidden): "))
    elif args.command == "revoke-token":
        request(args.url, directory / "ca.crt", "auth/token/revoke-self", {}, getpass.getpass("Operator token to revoke (hidden): "))
        print("Operator token revoked. Application AppRoles are unchanged.")
    else:
        response = request(args.url, directory / "ca.crt", "sys/seal-status", method="GET")
        print(json.dumps({k: response.get(k) for k in ("initialized", "sealed", "version")}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print("Setup failed:", e, file=sys.stderr)
        sys.exit(1)
