#!/usr/bin/env python3
"""Isolated PR review; never loads the checkout's .env or deployed configuration."""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'ifora-pr138-review'
DIRECTORY = Path.home() / 'ifora-local' / PROJECT
ENV_FILE = DIRECTORY / 'review.env'
KEYS = ('SECRET_KEY', 'ADMIN_SECRET_KEY', 'MFA_ENCRYPTION_KEY',
        'RECIPE_ENCRYPTION_KEY', 'OIDC_KEY_ENCRYPTION_KEY', 'SWA_ENCRYPTION_KEY')


def environment_file():
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    DIRECTORY.chmod(0o700)
    if ENV_FILE.is_symlink():
        raise SystemExit('Refusing a symlink for review credentials')
    if not ENV_FILE.exists():
        values = {'POSTGRES_PASSWORD': secrets.token_hex(24)}
        values.update({key: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() for key in KEYS})
        with os.fdopen(os.open(ENV_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as f:
            f.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    ENV_FILE.chmod(0o600)
    return dict(line.split('=', 1) for line in ENV_FILE.read_text().splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['up', 'stop', 'destroy', 'status', 'bootstrap'])
    parser.add_argument('--email')
    parser.add_argument('--purge-keys', action='store_true', help='With destroy: remove the private review environment file too')
    parser.add_argument('--confirm', help='For destroy: type the review project name')
    args = parser.parse_args()
    values = environment_file()
    # Prevent ambient COMPOSE_FILE, project names, or application secrets overriding the review env.
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'HOME', 'USER', 'TMPDIR', 'DOCKER_HOST', 'DOCKER_CONTEXT',
                      'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'SSH_AUTH_SOCK'}}
    cmd = ['docker', 'compose', '--project-name', PROJECT, '--env-file', str(ENV_FILE), '-f', str(ROOT / 'docker/docker-compose.review.yml')]
    if args.command == 'bootstrap':
        if not args.email:
            parser.error('bootstrap requires --email')
        password = getpass.getpass('New review admin password (hidden): ')
        if password != getpass.getpass('Confirm password: '):
            raise SystemExit('Passwords differ')
        payload = dict(email=args.email, password=password, first_name='Review', last_name='Admin',
                       secret_key=values['ADMIN_SECRET_KEY'])
        request = urllib.request.Request('http://localhost:8300/api/v1/admin/bootstrap',
                                         json.dumps(payload).encode(), {'Content-Type': 'application/json'})
        # No proxy or redirect forwarding of bootstrap credentials.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *unused):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=30):
            print('Review admin created. Sign in and enroll MFA at http://localhost:3300/login')
        return
    if args.command == 'destroy' and args.confirm != PROJECT:
        parser.error(f'destroy requires --confirm {PROJECT}; deletes review data only')
    options = {'up': ['up', '-d', '--build', '--wait', '--wait-timeout', '180'],
               'stop': ['stop'], 'status': ['ps'], 'destroy': ['down', '--volumes', '--remove-orphans']}
    subprocess.run(cmd + options[args.command], env=env, check=True)
    if args.command == 'up':
        print('Review UI: http://localhost:3300/login — bootstrap a fresh review administrator next.')
    if args.command == 'destroy':
        if args.purge_keys:
            ENV_FILE.unlink()
            print('Review volumes and private review keys removed.')
        else:
            print('Review volumes removed. Private review keys retained; use --purge-keys to delete them.')


if __name__ == '__main__':
    main()
