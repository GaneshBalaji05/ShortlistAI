import os
import tempfile
from fastapi import FastAPI, HTTPException

import auth_runtime


def endpoint(app, path, method):
    for route in app.routes:
        if getattr(route, 'path', None) == path and method in getattr(route, 'methods', set()):
            return route.endpoint
    raise AssertionError(f'Missing route {method} {path}')


def run():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        auth_runtime.DB_PATH = path
        app = FastAPI()
        auth_runtime.install_auth_routes(app)
        register = endpoint(app, '/api/auth/register', 'POST')
        login = endpoint(app, '/api/auth/login', 'POST')
        session = endpoint(app, '/api/auth/session', 'POST')
        logout = endpoint(app, '/api/auth/logout', 'POST')

        created = register(auth_runtime.RegisterIn(
            full_name='Ganesh Balaji',
            email='ganesh@example.com',
            password='Secure123',
            confirm_password='Secure123',
            workspace_name='Thinkinfinity',
        ))
        assert created['ok'] is True
        assert created['user']['role'] == 'Workspace Admin'
        assert created['user']['email'] == 'ganesh@example.com'
        assert created['token']

        con = auth_runtime._connect()
        row = con.execute('SELECT password_hash,password_salt FROM users WHERE email=?', ('ganesh@example.com',)).fetchone()
        con.close()
        assert row['password_hash'] != 'Secure123'
        assert len(row['password_hash']) >= 64
        assert row['password_salt']

        try:
            register(auth_runtime.RegisterIn(
                full_name='Ganesh Again', email='GANESH@example.com', password='Secure123',
                confirm_password='Secure123', workspace_name='Duplicate'
            ))
            raise AssertionError('Duplicate email should fail')
        except HTTPException as exc:
            assert exc.status_code == 409

        try:
            register(auth_runtime.RegisterIn(
                full_name='Weak User', email='weak@example.com', password='password',
                confirm_password='password', workspace_name='Weak Workspace'
            ))
            raise AssertionError('Weak password should fail')
        except HTTPException as exc:
            assert exc.status_code == 400

        logged = login(auth_runtime.LoginIn(email='ganesh@example.com', password='Secure123', remember=True))
        assert logged['ok'] is True
        check = session(auth_runtime.TokenIn(token=logged['token']))
        assert check['user']['email'] == 'ganesh@example.com'
        assert check['workspace'] == 'Thinkinfinity'

        logout(auth_runtime.TokenIn(token=logged['token']))
        try:
            session(auth_runtime.TokenIn(token=logged['token']))
            raise AssertionError('Logged-out token should fail')
        except HTTPException as exc:
            assert exc.status_code == 401

        demo = login(auth_runtime.LoginIn(email='demo@shortlist.ai', password='shortlist123', remember=True))
        assert demo.get('demo') is True

        print('Create Account tests passed')
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


if __name__ == '__main__':
    run()
