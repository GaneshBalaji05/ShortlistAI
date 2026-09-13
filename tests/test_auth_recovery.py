import os
import tempfile
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException
from starlette.requests import Request

import auth_runtime


def endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, 'path', None) == path and method in getattr(route, 'methods', set()):
            return route.endpoint
    raise AssertionError(f'Missing route {method} {path}')


def request():
    return Request({
        'type': 'http',
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'https',
        'path': '/api/auth/forgot-password',
        'raw_path': b'/api/auth/forgot-password',
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 12345),
        'server': ('testserver', 443),
        'root_path': '',
    })


def run():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    previous_db = auth_runtime.DB_PATH
    previous_public = os.environ.get('SHORTLISTAI_PUBLIC_URL')
    original_sender = auth_runtime._send_reset_email
    sent = []

    try:
        auth_runtime.DB_PATH = path
        os.environ['SHORTLISTAI_PUBLIC_URL'] = 'https://shortlistai.example'
        auth_runtime._send_reset_email = lambda recipient, reset_url: sent.append((recipient, reset_url)) or True

        app = FastAPI()
        auth_runtime.install_auth_routes(app)
        register = endpoint(app, '/api/auth/register', 'POST')
        login = endpoint(app, '/api/auth/login', 'POST')
        forgot = endpoint(app, '/api/auth/forgot-password', 'POST')
        reset = endpoint(app, '/api/auth/reset-password', 'POST')
        session = endpoint(app, '/api/auth/session', 'POST')

        created = register(auth_runtime.RegisterIn(
            full_name='Recovery User',
            email='recovery@example.com',
            password='OldPass123',
            confirm_password='OldPass123',
            workspace_name='Recovery Workspace',
        ))
        assert created['ok'] is True
        original_token = created['token']

        response = forgot(auth_runtime.ForgotPasswordIn(email='recovery@example.com'), request())
        assert response['ok'] is True
        assert len(sent) == 1
        assert sent[0][0] == 'recovery@example.com'
        reset_url = sent[0][1]
        token = parse_qs(urlparse(reset_url).query)['reset_token'][0]
        assert token

        changed = reset(auth_runtime.ResetPasswordIn(
            token=token,
            password='NewPass456',
            confirm_password='NewPass456',
        ))
        assert changed['ok'] is True

        try:
            session(auth_runtime.TokenIn(token=original_token))
            raise AssertionError('Password reset must revoke existing sessions')
        except HTTPException as exc:
            assert exc.status_code == 401

        try:
            login(auth_runtime.LoginIn(email='recovery@example.com', password='OldPass123', remember=True))
            raise AssertionError('Old password must not work after reset')
        except HTTPException as exc:
            assert exc.status_code == 401

        logged = login(auth_runtime.LoginIn(email='recovery@example.com', password='NewPass456', remember=True))
        assert logged['ok'] is True
        assert logged['user']['email'] == 'recovery@example.com'

        try:
            reset(auth_runtime.ResetPasswordIn(
                token=token,
                password='Another789',
                confirm_password='Another789',
            ))
            raise AssertionError('Reset token must be one-time use')
        except HTTPException as exc:
            assert exc.status_code == 400

        sent.clear()
        missing = forgot(auth_runtime.ForgotPasswordIn(email='nobody@example.com'), request())
        assert missing['ok'] is True
        assert sent == [], 'Unknown accounts must not generate email'

        print('Auth recovery tests passed')
    finally:
        auth_runtime._send_reset_email = original_sender
        auth_runtime.DB_PATH = previous_db
        if previous_public is None:
            os.environ.pop('SHORTLISTAI_PUBLIC_URL', None)
        else:
            os.environ['SHORTLISTAI_PUBLIC_URL'] = previous_public
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == '__main__':
    run()
