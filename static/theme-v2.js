(() => {
  const sessionRaw = localStorage.getItem('shortlistai-preview-session');
  if (!sessionRaw && location.pathname === '/app') {
    location.replace('/');
    return;
  }

  const icons = {
    dashboard:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 13h6V4H4v9Zm10 7h6v-9h-6v9ZM4 20h6v-3H4v3Zm10-13h6V4h-6v3Z"/></svg>',
    talent:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M19 20v-2a6 6 0 0 0-2-4"/></svg>',
    jobs:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="18" height="14" rx="3"/><path d="M8 6V4h8v2M3 11h18M9 11v2h6v-2"/></svg>',
    candidates:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3"/><path d="M3.5 19c.7-3.2 2.6-5 5.5-5s4.8 1.8 5.5 5"/><path d="M17 8h4M19 6v4M16 14h5M16 18h4"/></svg>',
    pipeline:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 4v16M5 8h7a3 3 0 0 1 3 3v0a3 3 0 0 0 3 3h1"/><path d="m17 11 3 3-3 3"/></svg>',
    shortlist:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4L12 3Z"/><path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14Z"/></svg>'
  };

  const viewModeIcons = {
    mobile:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="6.5" y="2.5" width="11" height="19" rx="3"/><path d="M9.5 5.5h5M10 18.5h4"/></svg>',
    desktop:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="4" width="19" height="13" rx="2.8"/><path d="M8 21h8M12 17v4"/><path d="M6 8h12" opacity=".55"/></svg>'
  };

  const premiumViewStyle = document.createElement('style');
  premiumViewStyle.textContent = `
    .fr-view-switch{gap:5px!important;padding:5px!important;border-radius:18px!important;border-color:rgba(255,67,73,.28)!important;background:rgba(7,7,9,.97)!important;box-shadow:0 16px 44px rgba(0,0,0,.52),0 0 0 1px rgba(255,255,255,.025) inset!important}
    .fr-view-switch button{display:flex!important;align-items:center!important;gap:8px!important;min-height:46px!important;padding:6px 10px 6px 6px!important;border-radius:13px!important;letter-spacing:0!important;transition:transform .18s ease,background .18s ease,box-shadow .18s ease!important}
    .fr-view-switch button:hover{transform:translateY(-1px)}
    .fr-view-switch .premium-view-icon{width:34px;height:34px;display:grid;place-items:center;flex:0 0 34px;margin:0!important;border-radius:11px;background:linear-gradient(145deg,#17171a,#0d0d0f);border:1px solid rgba(255,255,255,.09);box-shadow:0 7px 18px rgba(0,0,0,.34),inset 0 1px 0 rgba(255,255,255,.05);color:#b9b9c0;transition:.18s ease}
    .fr-view-switch .premium-view-icon svg{width:20px;height:20px;stroke-width:2.05}
    .fr-view-switch .premium-view-copy{display:flex;flex-direction:column;align-items:flex-start;gap:2px;margin:0!important;line-height:1}
    .fr-view-switch .premium-view-copy strong{font-size:11px;font-weight:900;color:inherit;letter-spacing:-.1px}
    .fr-view-switch .premium-view-copy small{font-size:8px;font-weight:750;color:#777780;letter-spacing:.06em;text-transform:uppercase}
    .fr-view-switch button.active{background:linear-gradient(135deg,#ff3941,#d4000a)!important;box-shadow:0 8px 22px rgba(255,42,50,.3)!important}
    .fr-view-switch button.active .premium-view-icon{color:#fff;background:rgba(0,0,0,.18);border-color:rgba(255,255,255,.24);box-shadow:inset 0 1px 0 rgba(255,255,255,.16),0 6px 14px rgba(102,0,4,.18)}
    .fr-view-switch button.active .premium-view-copy small{color:rgba(255,255,255,.72)}
    @media(max-width:520px){.fr-view-switch button{padding-right:8px!important;gap:6px!important}.fr-view-switch .premium-view-icon{width:31px;height:31px;flex-basis:31px;border-radius:10px}.fr-view-switch .premium-view-icon svg{width:18px;height:18px}.fr-view-switch .premium-view-copy strong{font-size:10px}.fr-view-switch .premium-view-copy small{font-size:7px}}
  `;
  document.head.appendChild(premiumViewStyle);

  function upgradeViewModeIcons(){
    const control = document.getElementById('frViewModeControl');
    if (!control) return;
    control.querySelectorAll('[data-view]').forEach(button => {
      const mode = button.dataset.view;
      if (!viewModeIcons[mode] || button.dataset.premiumViewIcon === '1') return;
      const label = mode === 'mobile' ? 'Mobile' : 'Desktop';
      button.innerHTML = `<span class="premium-view-icon" aria-hidden="true">${viewModeIcons[mode]}</span><span class="premium-view-copy"><strong>${label}</strong><small>View</small></span>`;
      button.dataset.premiumViewIcon = '1';
      button.setAttribute('aria-label', `${label} View`);
    });
  }

  const viewIconObserver = new MutationObserver(() => upgradeViewModeIcons());
  viewIconObserver.observe(document.documentElement, {childList:true, subtree:true});
  upgradeViewModeIcons();
  setTimeout(upgradeViewModeIcons, 250);
  setTimeout(upgradeViewModeIcons, 900);

  const brandHtml = '<span class="brand-logo">S<small>AI</small></span><span class="brand-word">Shortlist<span class="brand-ai">AI</span></span>';
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

  if (!document.querySelector('script[data-final-review]')) {
    const script = document.createElement('script');
    script.src = '/static/final-review.js?v=1';
    script.dataset.finalReview = '1';
    script.defer = true;
    document.body.appendChild(script);
  }
})();
