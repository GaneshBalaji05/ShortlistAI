(() => {
  const SESSION_KEY = 'shortlistai-auth-session';

  function setMessage(id, text, ok = false) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('success', ok);
  }

  async function refreshServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
      const reg = await navigator.serviceWorker.getRegistration('/');
      if (reg) await reg.update();
    } catch (_) {}
  }

  async function robustPost(path, body) {
    const attempt = async (retry = false) => {
      const target = new URL(path, window.location.origin);
      if (retry) target.searchParams.set('_retry', Date.now().toString());
      const response = await fetch(target.toString(), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
        cache: 'no-store',
        credentials: 'same-origin',
        redirect: 'follow'
      });
      let data = {};
      try { data = await response.json(); } catch (_) {}
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      return data;
    };

    try {
      return await attempt(false);
    } catch (err) {
      const networkError = err instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(err && err.message));
      if (!networkError) throw err;
      await refreshServiceWorker();
      await new Promise(resolve => setTimeout(resolve, 350));
      return attempt(true);
    }
  }

  function saveSession(data, remember = true) {
    const value = JSON.stringify({token: data.token, user: data.user, workspace: data.workspace, ts: Date.now()});
    (remember ? localStorage : sessionStorage).setItem(SESSION_KEY, value);
    localStorage.removeItem('shortlistai-preview-session');
  }

  function wireAuthRecovery() {
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
      loginForm.onsubmit = async event => {
        event.preventDefault();
        const email = (document.getElementById('email')?.value || '').trim();
        const password = document.getElementById('password')?.value || '';
        const remember = !!document.getElementById('remember')?.checked;
        if (!/^\S+@\S+\.\S+$/.test(email)) {
          setMessage('loginError', 'Enter a valid work email.');
          return;
        }
        try {
          setMessage('loginError', 'Signing in…', true);
          const data = await robustPost('/api/auth/login', {email, password, remember});
          saveSession(data, remember);
          window.location.replace('/app');
        } catch (err) {
          const networkError = err instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(err && err.message));
          setMessage('loginError', networkError ? 'Connection interrupted. Please tap Sign in again.' : (err.message || 'Sign in failed.'));
        }
      };
    }

    const createForm = document.getElementById('createForm');
    if (createForm) {
      createForm.onsubmit = async event => {
        event.preventDefault();
        const payload = {
          full_name: (document.getElementById('fullName')?.value || '').trim(),
          email: (document.getElementById('workEmail')?.value || '').trim(),
          workspace_name: (document.getElementById('workspaceName')?.value || '').trim(),
          password: document.getElementById('newPassword')?.value || '',
          confirm_password: document.getElementById('confirmPassword')?.value || ''
        };
        if (payload.password !== payload.confirm_password) {
          setMessage('createError', 'Passwords do not match.');
          return;
        }
        try {
          setMessage('createError', 'Creating your workspace…', true);
          const data = await robustPost('/api/auth/register', payload);
          saveSession(data, true);
          setMessage('createError', 'Account created. Opening your workspace…', true);
          setTimeout(() => window.location.replace('/app'), 250);
        } catch (err) {
          const networkError = err instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(err && err.message));
          setMessage('createError', networkError ? 'Connection interrupted. Please try again.' : (err.message || 'Account creation failed.'));
        }
      };
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wireAuthRecovery, {once: true});
  else wireAuthRecovery();
})();
