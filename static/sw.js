const CACHE = 'shortlistai-v5';
const APP_SHELL = [
  '/static/manifest.webmanifest',
  '/static/icons/icon-192-v3.png',
  '/static/icons/icon-512-v3.png'
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
        .then(response => response)
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
