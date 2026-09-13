(() => {
  const LEGACY_SESSION_KEY = 'shortlistai-auth-session';
  const RESET_MINUTES = 30;

  function setMessage(id, text, ok = false) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('success', ok);
  }

  function clearLegacySessionState() {
    try {
      localStorage.removeItem(LEGACY_SESSION_KEY);
      sessionStorage.removeItem(LEGACY_SESSION_KEY);
      localStorage.removeItem('shortlistai-preview-session');
    } catch (_) {}
  }

  async function refreshServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
      const reg = await navigator.serviceWorker.getRegistration('/');
      if (reg) await reg.update();
    } catch (_) {}
  }

  async function requestJSON(path, options = {}) {
    const response = await fetch(path, {
      cache: 'no-store',
      credentials: 'same-origin',
      ...options,
      headers: {
        ...(options.body ? {'Content-Type': 'application/json'} : {}),
        ...(options.headers || {})
      }
    });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      const err = new Error(data.detail || data.message || `Request failed (${response.status})`);
      err.status = response.status;
      throw err;
    }
    return data;
  }

  async function robustPost(path, body) {
    try {
      return await requestJSON(path, {method: 'POST', body: JSON.stringify(body)});
    } catch (err) {
      const networkError = err instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(err && err.message));
      if (!networkError) throw err;
      await refreshServiceWorker();
      await new Promise(resolve => setTimeout(resolve, 350));
      const retryUrl = new URL(path, window.location.origin);
      retryUrl.searchParams.set('_retry', Date.now().toString());
      return requestJSON(retryUrl.toString(), {method: 'POST', body: JSON.stringify(body)});
    }
  }

  async function verifyCookieSession(retry = true) {
    try {
      return await requestJSON('/api/auth/session?_=' + Date.now());
    } catch (err) {
      if (retry && err.status === 401) {
        await new Promise(resolve => setTimeout(resolve, 180));
        return verifyCookieSession(false);
      }
      throw err;
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
    if (window.location.pathname !== '/' || new URLSearchParams(window.location.search).has('reset_token')) return;
    try {
      await verifyCookieSession(false);
      clearLegacySessionState();
      window.location.replace('/app?_resume=' + Date.now());
    } catch (_) {
      // Expected for signed-out visitors.
    }
  }

  function ensureFallbackForgotUI() {
    const loginForm = document.getElementById('loginForm');
    if (!loginForm || document.getElementById('forgotPassword')) return;

    const link = document.createElement('button');
    link.id = 'forgotPassword';
    link.type = 'button';
    link.textContent = 'Forgot password?';
    Object.assign(link.style, {
      display: 'block', margin: '12px auto 0', border: '0', background: 'transparent',
      color: '#ff777d', fontWeight: '800', fontSize: '12px', cursor: 'pointer'
    });
    loginForm.appendChild(link);

    const overlay = document.createElement('div');
    overlay.id = 'forgotRecoveryOverlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <div style="position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.78);display:grid;place-items:center;padding:18px">
        <div style="width:min(430px,100%);background:#0c0c0e;border:1px solid #29292e;border-radius:22px;padding:25px;color:#fff;box-shadow:0 24px 70px rgba(0,0,0,.6)">
          <div style="font-size:11px;color:#ff666c;text-transform:uppercase;letter-spacing:.12em;font-weight:900;margin-bottom:8px">Account recovery</div>
          <h2 style="margin:0 0 8px">Reset your password</h2>
          <p style="margin:0 0 18px;color:#97979f;line-height:1.5">Enter your work email. We’ll send a secure reset link valid for ${RESET_MINUTES} minutes.</p>
          <input id="fallbackForgotEmail" type="email" autocomplete="email" placeholder="you@company.com" style="width:100%;height:50px;background:#0a0a0c;border:1px solid #2e2e33;border-radius:14px;color:#fff;padding:0 14px;outline:none"/>
          <div id="fallbackForgotError" style="min-height:20px;margin:10px 0;color:#ff777d;font-size:12px;text-align:center"></div>
          <button id="fallbackForgotSend" type="button" style="width:100%;height:50px;border:0;border-radius:14px;color:#fff;font-weight:900;background:linear-gradient(135deg,#ff3b43,#c90009);cursor:pointer">Send reset link →</button>
          <button id="fallbackForgotCancel" type="button" style="width:100%;margin-top:12px;border:0;background:transparent;color:#ff777d;font-weight:800;cursor:pointer">← Back to sign in</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    link.onclick = () => {
      document.getElementById('fallbackForgotEmail').value = (document.getElementById('email')?.value || '').trim();
      overlay.hidden = false;
    };
    document.getElementById('fallbackForgotCancel').onclick = () => { overlay.hidden = true; };
    document.getElementById('fallbackForgotSend').onclick = async () => {
      const email = (document.getElementById('fallbackForgotEmail').value || '').trim();
      const msg = document.getElementById('fallbackForgotError');
      if (!/^\S+@\S+\.\S+$/.test(email)) { msg.textContent = 'Enter a valid work email.'; return; }
      try {
        msg.style.color = '#83e7aa';
        msg.textContent = 'Sending reset link…';
        const data = await robustPost('/api/auth/forgot-password', {email});
        msg.textContent = data.message || 'If an account exists for that email, a reset link has been sent.';
      } catch (err) {
        msg.style.color = '#ff777d';
        msg.textContent = err.message || 'Could not send the reset link.';
      }
    };
  }

  function wireForgotPassword() {
    ensureFallbackForgotUI();
    const forgotButton = document.getElementById('forgotPassword');
    const forgotPane = document.getElementById('forgotPane');
    const loginPane = document.getElementById('loginPane');
    const authTabs = document.getElementById('authTabs');
    const forgotEmail = document.getElementById('forgotEmail');

    if (forgotButton && forgotPane) {
      forgotButton.onclick = () => {
        if (forgotEmail) forgotEmail.value = (document.getElementById('email')?.value || '').trim();
        loginPane?.classList.add('hidden');
        document.getElementById('createPane')?.classList.add('hidden');
        document.getElementById('resetPane')?.classList.add('hidden');
        forgotPane.classList.remove('hidden');
        authTabs?.classList.add('hidden');
      };
    }

    document.querySelectorAll('.backToSignIn').forEach(btn => {
      btn.onclick = () => {
        forgotPane?.classList.add('hidden');
        document.getElementById('resetPane')?.classList.add('hidden');
        loginPane?.classList.remove('hidden');
        authTabs?.classList.remove('hidden');
        history.replaceState({}, '', location.pathname);
      };
    });

    const forgotForm = document.getElementById('forgotForm');
    if (forgotForm) {
      forgotForm.onsubmit = async event => {
        event.preventDefault();
        const email = (forgotEmail?.value || '').trim();
        if (!/^\S+@\S+\.\S+$/.test(email)) {
          setMessage('forgotError', 'Enter a valid work email.');
          return;
        }
        try {
          setMessage('forgotError', 'Sending reset link…', true);
          const data = await robustPost('/api/auth/forgot-password', {email});
          setMessage('forgotError', data.message || 'If an account exists for that email, a reset link has been sent.', true);
        } catch (err) {
          setMessage('forgotError', err.message || 'Could not send the reset link.');
        }
      };
    }

    const resetForm = document.getElementById('resetForm');
    if (resetForm) {
      resetForm.onsubmit = async event => {
        event.preventDefault();
        const token = new URLSearchParams(location.search).get('reset_token') || '';
        const password = document.getElementById('resetPassword')?.value || '';
        const confirm_password = document.getElementById('resetConfirm')?.value || '';
        if (!token) { setMessage('resetError', 'Reset link is invalid.'); return; }
        if (password !== confirm_password) { setMessage('resetError', 'Passwords do not match.'); return; }
        try {
          setMessage('resetError', 'Updating password…', true);
          const data = await robustPost('/api/auth/reset-password', {token, password, confirm_password});
          setMessage('resetError', data.message || 'Password updated.', true);
          setTimeout(() => {
            history.replaceState({}, '', location.pathname);
            document.getElementById('resetPane')?.classList.add('hidden');
            loginPane?.classList.remove('hidden');
            authTabs?.classList.remove('hidden');
            setMessage('loginError', 'Password updated. Sign in with your new password.', true);
          }, 700);
        } catch (err) {
          setMessage('resetError', err.message || 'Could not update the password.');
        }
      };
    }
  }

  function wireAuthRecovery() {
    clearLegacySessionState();
    wireForgotPassword();

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
          await robustPost('/api/auth/login', {email, password, remember});
          setMessage('loginError', 'Signed in. Opening your workspace…', true);
          await enterWorkspace();
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
          await robustPost('/api/auth/register', payload);
          setMessage('createError', 'Account created. Opening your workspace…', true);
          await enterWorkspace();
        } catch (err) {
          const networkError = err instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(String(err && err.message));
          setMessage('createError', networkError ? 'Connection interrupted. Please try again.' : (err.message || 'Account creation failed.'));
        }
      };
    }
  }

  async function start() {
    wireAuthRecovery();
    await resumeExistingSession();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
