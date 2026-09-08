/**
 * MedShare Service Worker — mode hors-ligne (itération 3, addendum).
 *
 * Stratégie :
 *  - Pré-cache de la coquille au moment de l'installation.
 *  - Navigations : network-first, repli sur la page mise en cache lors de la
 *    dernière visite (lecture hors-ligne des DMP, dossiers, etc.), puis sur '/'.
 *  - Statiques (CSS/JS/images/fonts) : cache-first + mise à jour en arrière-plan
 *    (stale-while-revalidate) pour un démarrage déterministe.
 *  - Les POST ne sont PAS interceptés ici : la file d'attente IndexedDB est
 *    gérée dans static/js/offline.js.
 */
const CACHE_SHELL = 'medshare-shell-v3';
const PRECACHE_URLS = [
    '/',
    '/static/css/tailwind.css',
    '/static/css/fonts.css',
    '/static/css/style.css',
    '/static/manifest.json',
    '/static/js/offline.js',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_SHELL)
            .then((cache) => Promise.all(
                // addAll échoue si une seule URL manque : on tolère les 404
                // ponctuels pour ne pas bloquer l'installation.
                PRECACHE_URLS.map((url) =>
                    fetch(url)
                        .then((res) => { if (res.ok) cache.put(url, res); })
                        .catch(() => {}))
            ))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys.filter((k) => k !== CACHE_SHELL)
                    .map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;

    // Dossier de navigation / pages HTML
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    const clone = response.clone();
                    caches.open(CACHE_SHELL).then((cache) => cache.put(request, clone));
                    markLastOnline();
                    return response;
                })
                .catch(async () => {
                    const cached = await caches.match(request);
                    if (cached) return cached;
                    const root = await caches.match('/');
                    return root || Response.error();
                })
        );
        return;
    }

    // Statiques : cache d'abord, rafraîchi en arrière-plan
    if (request.url.includes('/static/') || request.url.includes('/media/')) {
        event.respondWith(
            caches.match(request).then((cached) => {
                const fallback = fetch(request).then((response) => {
                    const clone = response.clone();
                    caches.open(CACHE_SHELL).then((cache) => cache.put(request, clone));
                    return response;
                }).catch(() => cached || Response.error());
                return cached || fallback;
            })
        );
        return;
    }

    // Autres GET : réseau d'abord, cache en secours
    event.respondWith(
        fetch(request)
            .then((response) => {
                if (response && response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_SHELL).then((cache) => cache.put(request, clone));
                }
                return response;
            })
            .catch(() => caches.match(request))
    );
});

function markLastOnline() {
    self.clients.matchAll({ includeUncontrolled: true }).then((clients) => {
        clients.forEach((client) => {
            client.postMessage({ type: 'MEDSHARE_LAST_ONLINE', timestamp: Date.now() });
        });
    });
}