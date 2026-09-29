const CACHE_NAME = 'malindang-shell-v3';
const APP_SHELL = [
    '/offline.html',
    '/static/offline.js',
    '/static/malindang-logo.svg',
    '/static/health-welcome.svg',
];
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(APP_SHELL))
            .then(() => self.skipWaiting()),
    );
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.filter(key => key.startsWith('malindang-shell-') && key !== CACHE_NAME)
            .map(key => caches.delete(key)));
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);
    if (url.origin !== self.location.origin) return;

    if (event.request.mode === 'navigate') {
        event.respondWith(fetch(event.request).catch(async () => {
            const cache = await caches.open(CACHE_NAME);
            return (await cache.match('/offline.html')) || Response.error();
        }));
        return;
    }

    const isAppShellAsset = APP_SHELL.some(path => url.pathname === path);
    if (!isAppShellAsset) return;
    event.respondWith((async () => {
        const cache = await caches.open(CACHE_NAME);
        try {
            const response = await fetch(event.request);
            if (response.ok) await cache.put(event.request, response.clone());
            return response;
        } catch (error) {
            const cached = await cache.match(event.request);
            if (cached) return cached;
            throw error;
        }
    })());
});
