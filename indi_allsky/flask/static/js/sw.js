const CACHE_NAME = 'indi-allsky-v2';
const ASSETS_TO_CACHE = [
  '/indi-allsky/',
  '/indi-allsky/static/css/dist.css',
  '/indi-allsky/static/js/jquery-3.7.1.min.js',
  '/indi-allsky/static/images/favicon_32.png',
  '/indi-allsky/static/images/favicon_128.png',
  '/indi-allsky/static/images/icon-192.png',
  '/indi-allsky/static/images/icon-512.png',
  '/indi-allsky/static/images/screenshot-desktop.png',
  '/indi-allsky/static/images/screenshot-mobile.png',
  '/indi-allsky/static/images/logo_outline_full.png'
];

// Install Event
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// Activate Event
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Fetch Event
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }

  const url = new URL(event.request.url);

  // Network-only for API calls, authentication, dynamic camera feeds, and video streams
  if (
    url.pathname.startsWith('/api') ||
    url.pathname.startsWith('/auth') ||
    url.pathname.startsWith('/actionapi') ||
    url.pathname.startsWith('/syncapi') ||
    url.pathname.includes('/image') ||
    url.pathname.includes('/video') ||
    url.pathname.includes('/stream')
  ) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      const fetchPromise = fetch(event.request)
        .then((networkResponse) => {
          if (
            networkResponse &&
            networkResponse.status === 200 &&
            networkResponse.type === 'basic'
          ) {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
          }
          return networkResponse;
        })
        .catch(() => cachedResponse);

      return cachedResponse || fetchPromise;
    })
  );
});
