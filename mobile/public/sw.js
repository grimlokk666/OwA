/**
 * Sovereign Overwatch — caching service worker
 *
 * Local-first shell cache only. Never phones home. Never proxies SaaS CDNs.
 * Dashboard / API traffic over Tailscale is network-first (live ops data).
 */

const CACHE_VERSION = 'sovereign-overwatch-v1';
const SHELL_CACHE = `${CACHE_VERSION}-shell`;

/** App shell assets safe to precache (relative to SW scope). */
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
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

/**
 * Classify requests:
 * - same-origin shell assets → cache-first
 * - /api/* and remote dashboard hosts → network-only (live tactical data)
 * - everything else on-origin → stale-while-revalidate
 */
function isApiOrLive(url) {
  return (
    url.pathname.startsWith('/api/') ||
    url.pathname.includes('/telemetry') ||
    url.searchParams.has('live')
  );
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Never cache cross-origin Tailscale / LAN dashboard responses in the SW.
  // The WebView loads them live; offline shell stays local.
  if (url.origin !== self.location.origin) {
    return;
  }

  if (isApiOrLive(url)) {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      const cached = await cache.match(request);

      const networkPromise = fetch(request)
        .then(async (response) => {
          if (response.ok && request.method === 'GET') {
            await cache.put(request, response.clone());
          }
          return response;
        })
        .catch(() => cached);

      // Navigation: prefer network so operators get fresh shell after updates,
      // fall back to cached index for offline installability.
      if (request.mode === 'navigate') {
        try {
          return await networkPromise;
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
