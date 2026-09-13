(() => {
  'use strict';

  const LEGACY_SESSION_KEY = 'shortlistai-auth-session';
  const RESET_MINUTES = 30;

  const byId = id => document.getElementById(id);

  function setMessage(id, text, ok = false) {
    const el = byId(id);
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('success', !!ok);
  }

  function clearLegacySessionState() {
    try {
      localStorage.removeItem(LEGACY_SESSION_KEY);
      sessionStorage.removeItem(LEGACY_SESSION_KEY);
      localStorage.removeItem('shortlistai-preview-session');
    } catch (_) {
      // Storage may be blocked. HttpOnly cookies remain the auth source of truth.
    }
  }

  function setMode(mode) {
    const panes = {
      login: 'loginPane',
      create: 'createPane',
      forgot: 'forgotPane',
      reset: 'resetPane'
    };
    Object.values(panes).forEach(id => byId(id)?.classList.add('hidden'));
    byId(panes[mode] || panes.login)?.classList.remove('hidden');

    const standard = mode === 'login' || mode === 'create';
    byId('authTabs')?.classList.toggle('hidden', !standard);
    byId('signInTab')?.classList.toggle('active', mode === 'login');
    byId('createTab')?.classList.toggle('active', mode === 'create');

    const titles = {
      login: 'Sign in',
      create: 'Create account',
      forgot: 'Forgot password',
      reset: 'Reset password'
    };
    document.title = `${titles[mode] || titles.login} · ShortlistAI`;
  }

  async function requestJSON(path, options = {}) {
    const response = await fetch(path, {
      cache: 'no-store',
      credentials: 'same-origin',
      redirect: 'follow',
      ...options,
      headers: {
        ...(options.body ? {'Content-Type': 'application/json'} : {}),
        ...(options.headers || {})
      }
    });

    let data = {};
    try {
      data = await response.json();
    } catch (_) {
      // Some redirects/error responses have no JSON body.
    }

    if (!response.ok) {
      const error = new Error(data.detail || data.message || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function updateServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.register('/static/sw.js?v=10', {scope: '/'});
      await registration.update();
    } catch (_) {
      // Authentication must not depend on service-worker availability.
    }
  }

  async function robustPost(path, body) {
    const attempt = retry => {
      const target = new URL(path, window.location.origin);
      if (retry) target.searchParams.set('_retry', Date.now().toString());
      return requestJSON(target.toString(), {
        method: 'POST',
        body: JSON.stringify(body)
      });
    };

    try {
      return await attempt(false);
    } catch (error) {
      const networkError = error instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(error?.message || ''));
      if (!networkError) throw error;
      await updateServiceWorker();
      await new Promise(resolve => setTimeout(resolve, 250));
      return attempt(true);
    }
  }

  async function verifyCookieSession(retry = true) {
    try {
      return await requestJSON(`/api/auth/session?_=${Date.now()}`);
    } catch (error) {
      if (retry && error.status === 401) {
        await new Promise(resolve => setTimeout(resolve, 180));
        return verifyCookieSession(false);
      }
      throw error;
    }
  }

  async function enterWorkspace() {
    clearLegacySessionState();
    await verifyCookieSession();
    const target = new URL('/app', window.location.origin);
    target.searchParams.set('_auth', Date.now().toString());
    window.location.replace(target.toString());
  }

  async function resumeExistingSession() {
    if (window.location.pathname !== '/') return;
    if (new URLSearchParams(window.location.search).has('reset_token')) return;
    try {
      await verifyCookieSession(false);
      clearLegacySessionState();
      window.location.replace(`/app?_resume=${Date.now()}`);
    } catch (_) {
      // A 401 is expected for signed-out visitors.
    }
  }

  function wirePresentation() {
    window.addEventListener('pointermove', event => {
      document.documentElement.style.setProperty('--mx', `${(event.clientX / window.innerWidth) * 100}%`);
      document.documentElement.style.setProperty('--my', `${(event.clientY / window.innerHeight) * 100}%`);
    }, {passive: true});

    byId('signInTab')?.addEventListener('click', () => setMode('login'));
    byId('createTab')?.addEventListener('click', () => setMode('create'));

    byId('forgotPassword')?.addEventListener('click', () => {
      const forgotEmail = byId('forgotEmail');
      if (forgotEmail) forgotEmail.value = (byId('email')?.value || '').trim();
      setMode('forgot');
    });

    document.querySelectorAll('.backToSignIn').forEach(button => {
      button.addEventListener('click', () => {
        history.replaceState({}, '', location.pathname);
        setMode('login');
      });
    });

    byId('fillDemo')?.addEventListener('click', () => {
      const email = byId('email');
      const password = byId('password');
      if (email) email.value = 'demo@shortlist.ai';
      if (password) password.value = 'shortlist123';
      setMessage('loginError', 'Demo access ready.', true);
    });
  }

  function wireAuthentication() {
    const loginForm = byId('loginForm');
    if (loginForm) {
      loginForm.addEventListener('submit', async event => {
        event.preventDefault();
        const email = (byId('email')?.value || '').trim();
        const password = byId('password')?.value || '';
        const remember = !!byId('remember')?.checked;

        if (!/^\S+@\S+\.\S+$/.test(email)) {
          setMessage('loginError', 'Enter a valid work email.');
          return;
        }

        try {
          setMessage('loginError', 'Signing in…', true);
          await robustPost('/api/auth/login', {email, password, remember});
          setMessage('loginError', 'Signed in. Opening your workspace…', true);
          await enterWorkspace();
        } catch (error) {
          const networkError = error instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(error?.message || ''));
          setMessage(
            'loginError',
            networkError ? 'Connection interrupted. Please tap Sign in again.' : (error.message || 'Sign in failed.')
          );
        }
      });
    }

    const createForm = byId('createForm');
    if (createForm) {
      createForm.addEventListener('submit', async event => {
        event.preventDefault();
        const payload = {
          full_name: (byId('fullName')?.value || '').trim(),
          email: (byId('workEmail')?.value || '').trim(),
          workspace_name: (byId('workspaceName')?.value || '').trim(),
          password: byId('newPassword')?.value || '',
          confirm_password: byId('confirmPassword')?.value || ''
        };

        if (payload.password !== payload.confirm_password) {
          setMessage('createError', 'Passwords do not match.');
          return;
        }

        try {
          setMessage('createError', 'Creating your workspace…', true);
          await robustPost('/api/auth/register', payload);
          setMessage('createError', 'Account created. Opening your workspace…', true);
          await enterWorkspace();
        } catch (error) {
          const networkError = error instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(error?.message || ''));
          setMessage(
            'createError',
            networkError ? 'Connection interrupted. Please try again.' : (error.message || 'Account creation failed.')
          );
        }
      });
    }

    const forgotForm = byId('forgotForm');
    if (forgotForm) {
      forgotForm.addEventListener('submit', async event => {
        event.preventDefault();
        const email = (byId('forgotEmail')?.value || '').trim();
        if (!/^\S+@\S+\.\S+$/.test(email)) {
          setMessage('forgotError', 'Enter a valid work email.');
          return;
        }
        try {
          setMessage('forgotError', 'Sending reset link…', true);
          const data = await robustPost('/api/auth/forgot-password', {email});
          setMessage('forgotError', data.message || `If an account exists for that email, a reset link valid for ${RESET_MINUTES} minutes has been sent.`, true);
        } catch (error) {
          setMessage('forgotError', error.message || 'Could not send the reset link.');
        }
      });
    }

    const resetForm = byId('resetForm');
    if (resetForm) {
      resetForm.addEventListener('submit', async event => {
        event.preventDefault();
        const token = new URLSearchParams(location.search).get('reset_token') || '';
        const password = byId('resetPassword')?.value || '';
        const confirm_password = byId('resetConfirm')?.value || '';

        if (!token) {
          setMessage('resetError', 'Reset link is invalid.');
          return;
        }
        if (password !== confirm_password) {
          setMessage('resetError', 'Passwords do not match.');
          return;
        }

        try {
          setMessage('resetError', 'Updating password…', true);
          const data = await robustPost('/api/auth/reset-password', {token, password, confirm_password});
          setMessage('resetError', data.message || 'Password updated.', true);
          setTimeout(() => {
            history.replaceState({}, '', location.pathname);
            setMode('login');
            setMessage('loginError', 'Password updated. Sign in with your new password.', true);
          }, 700);
        } catch (error) {
          setMessage('resetError', error.message || 'Could not update the password.');
        }
      });
    }
  }

  async function start() {
    clearLegacySessionState();
    wirePresentation();
    wireAuthentication();

    const resetToken = new URLSearchParams(location.search).get('reset_token') || '';
    setMode(resetToken ? 'reset' : 'login');

    window.__shortlistAIAuthReady = true;
    updateServiceWorker();
    await resumeExistingSession();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once: true});
  } else {
    start();
  }
})();
