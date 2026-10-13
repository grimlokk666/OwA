/**
 * Sovereign Overwatch — caching service worker
 *
 * Local-first shell cache only. Never phones home. Never proxies SaaS CDNs
 * into a permanent store. Live /api/* and map tiles stay network-first.
 */

const CACHE_VERSION = 'sovereign-overwatch-v3';
const SHELL_CACHE = `${CACHE_VERSION}-shell`;

const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './css/dashboard.css',
  './js/dashboard.js',
  './js/nav.js',
  './js/telemetry-node.js',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      await cache.addAll(PRECACHE_URLS);
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => key.startsWith('sovereign-overwatch-') && key !== SHELL_CACHE)
          .map((key) => caches.delete(key))
      );
      await self.clients.claim();
    })()
  );
});

function isLive(url) {
  return (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/tiles/') ||
    url.pathname === '/health' ||
    url.searchParams.has('live')
  );
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  if (url.origin !== self.location.origin || isLive(url)) {
    return;
  }

  event.respondWith(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      const cached = await cache.match(request);

      const networkPromise = fetch(request)
        .then(async (response) => {
          if (response.ok) {
            await cache.put(request, response.clone());
          }
          return response;
        })
        .catch(() => cached);

      if (request.mode === 'navigate') {
        try {
          return await fetch(request);
        } catch {
          return (await cache.match('./index.html')) || cached;
        }
      }

      return cached || networkPromise;
    })()
  );
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
