const CACHE = 'shortlistai-v7';
const APP_SHELL = [
  '/static/manifest.webmanifest',
  '/static/icons/icon-192-v3.png',
  '/static/icons/icon-512-v3.png',
  '/static/login-view-icon.js?v=1'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

async function injectLoginViewIcon(response) {
  if (!response || !response.ok) return response;
  const type = response.headers.get('content-type') || '';
  if (!type.includes('text/html')) return response;
  let html = await response.text();
  if (!html.includes('/static/login-view-icon.js')) {
    html = html.replace('</body>', '<script src="/static/login-view-icon.js?v=1"></script>\n</body>');
  }
  const headers = new Headers(response.headers);
  headers.delete('content-length');
  headers.set('Cache-Control', 'no-store');
  return new Response(html, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache live ATS/API data.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/analyze') || url.pathname.startsWith('/export')) {
    return;
  }

  // Always prefer the latest page for app navigation.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request, { cache: 'no-store' })
        .then(response => url.pathname === '/' ? injectLoginViewIcon(response) : response)
        .catch(() => caches.match('/') || new Response('ShortlistAI is temporarily offline.', { status: 503 }))
    );
    return;
  }

  // Static assets: network first, cached fallback.
  event.respondWith(
    fetch(request)
      .then(response => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then(cache => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
