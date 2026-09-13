const CACHE = 'shortlistai-v10';
const APP_SHELL = [
  '/static/manifest.webmanifest',
  '/static/icons/icon-192-v3.png',
  '/static/icons/icon-512-v3.png',
  '/static/login-view-icon.js?v=4',
  '/static/login-controller.js?v=1'
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

  // Authentication, ATS data and live actions must always reach the server.
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/analyze') ||
    url.pathname.startsWith('/export')
  ) {
    return;
  }

  // Documents are always network-only. Authentication must never depend on a
  // cached login/app document or HTML mutation performed by the service worker.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request, {cache: 'no-store', credentials: 'same-origin'})
        .catch(() => new Response('ShortlistAI is temporarily offline.', {
          status: 503,
          headers: {'Content-Type': 'text/plain; charset=utf-8'}
        }))
    );
    return;
  }

  // Versioned static assets are network-first with a same-version cache fallback.
  event.respondWith(
    fetch(request, {cache: 'no-cache', credentials: 'same-origin'})
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
