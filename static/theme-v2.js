(() => {
  const sessionRaw = localStorage.getItem('shortlistai-preview-session');
  if (!sessionRaw && location.pathname === '/app') {
    location.replace('/');
    return;
  }

  const icons = {
    dashboard:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 13h6V4H4v9Zm10 7h6v-9h-6v9ZM4 20h6v-3H4v3Zm10-13h6V4h-6v3Z"/></svg>',
    jobs:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="18" height="14" rx="3"/><path d="M8 6V4h8v2M3 11h18M9 11v2h6v-2"/></svg>',
    candidates:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3"/><path d="M3.5 19c.7-3.2 2.6-5 5.5-5s4.8 1.8 5.5 5"/><path d="M17 8h4M19 6v4M16 14h5M16 18h4"/></svg>',
    pipeline:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 4v16M5 8h7a3 3 0 0 1 3 3v0a3 3 0 0 0 3 3h1"/><path d="m17 11 3 3-3 3"/></svg>',
    shortlist:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4L12 3Z"/><path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14Z"/></svg>'
  };

  const brandHtml = '<span class="brand-logo">S<small>AI</small></span><span>Shortlist<span>AI</span></span>';
  document.querySelectorAll('.brand').forEach(brand => { brand.innerHTML = brandHtml; });

  document.querySelectorAll('.nav button').forEach(button => {
    const id = button.dataset.tab;
    if (!id || !icons[id] || button.querySelector('.nav-icon')) return;
    const icon = document.createElement('span');
    icon.className = 'nav-icon';
    icon.innerHTML = icons[id];
    button.prepend(icon);
  });

  const side = document.querySelector('.side');
  if (side && !side.querySelector('.sidebar-account')) {
    let email = 'Preview user';
    try { email = JSON.parse(sessionRaw || '{}').email || email; } catch (_) {}
    const name = email.split('@')[0].replace(/[._-]+/g,' ').replace(/\b\w/g,m=>m.toUpperCase());
    const footer = document.createElement('div');
    footer.className = 'sidebar-account';
    footer.innerHTML = `<div class="account-row"><div class="avatar">${(name[0] || 'S').toUpperCase()}</div><div class="account-copy"><b>${escapeHtml(name)}</b><small>Recruiter workspace</small></div><button class="signout" type="button" aria-label="Sign out">↗</button></div>`;
    side.appendChild(footer);
    footer.querySelector('.signout').onclick = () => { localStorage.removeItem('shortlistai-preview-session'); location.href='/'; };
  }

  function escapeHtml(value){
    return String(value || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  }
})();
