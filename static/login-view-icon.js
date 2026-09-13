(() => {
  'use strict';

  const KEY = 'shortlistai-login-view';
  const mq = window.matchMedia('(max-width:900px)');
  const iconDesktop = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>';
  const iconMobile = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M10 5h4M11 19h2"/></svg>';

  function storedMode() {
    try {
      return localStorage.getItem(KEY) || 'mobile';
    } catch (_) {
      return 'mobile';
    }
  }

  function setStoredMode(value) {
    try {
      localStorage.setItem(KEY, value);
    } catch (_) {
      // View preference is optional and must never affect authentication.
    }
  }

  function placeButton(btn) {
    if (!mq.matches) {
      btn.style.display = 'none';
      return;
    }
    btn.style.display = 'inline-flex';
    const vv = window.visualViewport;
    const width = vv ? vv.width : window.innerWidth;
    const offset = vv ? vv.offsetLeft : 0;
    const buttonWidth = Math.max(118, Math.ceil(btn.getBoundingClientRect().width || 118));
    btn.style.left = `${Math.max(10, offset + width - buttonWidth - 12)}px`;
    btn.style.right = 'auto';
  }

  function render() {
    const btn = document.getElementById('viewToggle');
    if (!btn) return;

    const desktop = mq.matches && storedMode() === 'desktop';
    document.body.classList.toggle('force-desktop', desktop);
    btn.hidden = false;
    btn.setAttribute('aria-label', desktop ? 'Switch to Mobile View' : 'Switch to Desktop View');
    btn.setAttribute('title', desktop ? 'Switch to Mobile View' : 'Switch to Desktop View');
    btn.innerHTML = `${desktop ? iconMobile : iconDesktop}<span>${desktop ? 'Mobile View' : 'Desktop View'}</span>`;
    Object.assign(btn.style, {
      position: 'fixed',
      top: 'calc(env(safe-area-inset-top, 0px) + 12px)',
      zIndex: '9999',
      alignItems: 'center',
      gap: '7px',
      minHeight: '40px',
      padding: '9px 12px',
      borderRadius: '999px',
      border: '1px solid rgba(255,48,56,.55)',
      background: 'rgba(9,9,10,.96)',
      color: '#fff',
      boxShadow: '0 10px 30px rgba(0,0,0,.42)',
      backdropFilter: 'blur(12px)',
      fontSize: '11px',
      fontWeight: '850',
      whiteSpace: 'nowrap'
    });
    const svg = btn.querySelector('svg');
    if (svg) Object.assign(svg.style, {width:'17px',height:'17px',fill:'none',stroke:'currentColor',strokeWidth:'1.8'});
    placeButton(btn);
  }

  function toggle() {
    const desktop = mq.matches && storedMode() === 'desktop';
    setStoredMode(desktop ? 'mobile' : 'desktop');
    render();
    window.scrollTo({top: 0, left: 0, behavior: 'smooth'});
  }

  function start() {
    const btn = document.getElementById('viewToggle');
    if (!btn) return;
    btn.onclick = toggle;
    render();
    window.addEventListener('resize', render, {passive:true});
    mq.addEventListener?.('change', render);
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', () => placeButton(btn), {passive:true});
      window.visualViewport.addEventListener('scroll', () => placeButton(btn), {passive:true});
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once:true});
  } else {
    start();
  }
})();
