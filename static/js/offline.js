/**
 * MedShare — client hors-ligne (itération 3, addendum).
 *
 *  - File d'attente IndexedDB des soumissions de formulaires marqués
 *    [data-offline] lorsque le réseau est indisponible.
 *  - Reprise automatique (« sync ») au retour du réseau, dans l'ordre
 *    chronologique. Les réponses HTTP en erreur (conflits, validations)
 *    sont CONSERVÉES, jamais supprimées.
 *  - Bandeau « Hors ligne » + badge du nombre d'actions en attente dans la
 *    topbar + horodatage de la dernière synchronisation.
 *  - Approbations hors-ligne : lors de la reprise, l'en-tête
 *    X-Offline-Sync: 1 signale au serveur qu'il s'agit d'un acte consenti
 *    hors-ligne (« à confirmer à la synchronisation »).
 */
(function () {
    'use strict';

    var DB_NAME = 'medshare-offline';
    var DB_VERSION = 2;

    /* ── IndexedDB (petite couche de promesses) ─────────────────────────── */
    function openDb() {
        return new Promise(function (resolve, reject) {
            var req = indexedDB.open(DB_NAME, DB_VERSION);
            req.onupgradeneeded = function () {
                var db = req.result;
                if (!db.objectStoreNames.contains('actions')) {
                    var store = db.createObjectStore('actions', { keyPath: 'id', autoIncrement: true });
                    store.createIndex('date', 'date');
                }
                if (!db.objectStoreNames.contains('snapshots')) {
                    db.createObjectStore('snapshots', { keyPath: 'numeroPatient' });
                }
                if (!db.objectStoreNames.contains('meta')) {
                    db.createObjectStore('meta', { keyPath: 'key' });
                }
            };
            req.onsuccess = function () { resolve(req.result); };
            req.onerror = function () { reject(req.error); };
        });
    }

    function idb(mode, fn) {
        return openDb().then(function (db) {
            return new Promise(function (resolve, reject) {
                var tx = db.transaction('actions', mode);
                var out = fn(tx.objectStore('actions'), tx);
                tx.oncomplete = function () { resolve(out); };
                tx.onerror = function () { reject(tx.error); };
                tx.onabort = function () { reject(tx.error); };
            });
        });
    }

    function getAll() {
        return idb('readonly', function (store) {
            return store.getAll();
        });
    }

    function addAction(action) {
        return idb('readwrite', function (store) {
            store.add(action);
        });
    }

    function deleteAction(id) {
        return idb('readwrite', function (store) {
            store.delete(id);
        });
    }

    function metaGet(key) {
        return openDb().then(function (db) {
            return new Promise(function (resolve) {
                var tx = db.transaction('meta', 'readonly');
                var req = tx.objectStore('meta').get(key);
                req.onsuccess = function () { resolve(req.result ? req.result.value : null); };
                req.onerror = function () { resolve(null); };
            });
        });
    }

    function metaSet(key, value) {
        return openDb().then(function (db) {
            return new Promise(function (resolve) {
                var tx = db.transaction('meta', 'readwrite');
                tx.objectStore('meta').put({ key: key, value: value });
                tx.oncomplete = resolve;
            });
        });
    }

    /* ── Snapshots DMP (lecture "fiche vitale" hors-ligne) ──────────────── */
    function captureSnapshot() {
        var el = document.getElementById('dmp-snapshot');
        if (!el) return Promise.resolve();
        var data;
        try { data = JSON.parse(el.textContent); } catch (e) { return Promise.resolve(); }
        var snapshot = { numeroPatient: data.numeroPatient, data: data, capturedAt: Date.now() };
        return openDb().then(function (db) {
            return new Promise(function (resolve) {
                var tx = db.transaction('snapshots', 'readwrite');
                tx.objectStore('snapshots').put(snapshot);
                tx.oncomplete = resolve;
            });
        });
    }

    /* ── État UI ────────────────────────────────────────────────────────── */
    var elBadge = null;
    var elBanner = null;

    function createBadge() {
        var topbar = document.getElementById('app-topbar');
        var holder = topbar ? topbar.querySelector('.flex.items-center.gap-3') : null;
        if (!holder) return null;
        var span = document.createElement('span');
        span.id = 'offline-badge';
        span.dataset.idle = '1';
        span.style.display = 'none';
        span.style.cssText = 'display:none;';
        holder.appendChild(span);
        return span;
    }

    function createBanner() {
        var b = document.createElement('div');
        b.id = 'offline-banner';
        b.style.cssText = 'display:none;position:fixed;bottom:1rem;right:1rem;z-index:60;max-width:24rem;padding:0.75rem 1rem;border-radius:0.75rem;border:1px solid;box-shadow:0 10px 15px -3px rgba(0,0,0,.2);background:#0f172a;color:#fff;font-size:14px;';
        document.body.appendChild(b);
        return b;
    }

    function refreshBadge(count) {
        if (!elBadge) elBadge = createBadge();
        if (!elBadge) return;
        if (count > 0) {
            elBadge.textContent = count + ' action' + (count > 1 ? 's' : '') + ' en attente';
            elBadge.style.cssText = 'display:inline-flex;align-items:center;gap:0.5rem;padding:0.375rem 0.75rem;border-radius:9999px;border:1px solid #fcd34d;background:#fffbeb;color:#92400e;font-size:12px;font-weight:600;';
            elBadge.dataset.idle = '0';
        } else {
            elBadge.style.cssText = 'display:none;';
            elBadge.dataset.idle = '1';
        }
    }

    function showMessage(text, type) {
        if (!elBanner) elBanner = createBanner();
        if (!elBanner) return;
        var themes = {
            ok: { border: '#34d399', bg: '#047857' },
            warn: { border: '#fbbf24', bg: '#b45309' },
            err: { border: '#f87171', bg: '#991b1b' },
        };
        var theme = themes[type] || themes.ok;
        elBanner.style.cssText = 'display:block;position:fixed;bottom:1rem;right:1rem;z-index:60;max-width:24rem;padding:0.75rem 1rem;border-radius:0.75rem;border:1px solid ' + theme.border + ';background:' + theme.bg + ';color:#fff;font-size:14px;box-shadow:0 10px 15px -3px rgba(0,0,0,.2);';
        elBanner.textContent = text;
        clearTimeout(elBanner._t);
        elBanner._t = setTimeout(function () { elBanner.style.display = 'none'; }, 6000);
    }

    function setOnlineUI() {
        var dot = document.getElementById('offline-status-dot');
        if (dot) dot.style.background = '#10b981';
        var label = document.getElementById('offline-status-label');
        if (label) label.textContent = 'Système opérationnel';
    }

    function setOfflineUI() {
        var dot = document.getElementById('offline-status-dot');
        if (dot) { dot.style.background = '#f59e0b'; dot.classList.add('animate-ping'); }
        var label = document.getElementById('offline-status-label');
        if (label) label.textContent = 'Hors ligne';
    }

    /* ── File d'attente ─────────────────────────────────────────────────── */
    function serializeForm(form) {
        var data = new FormData(form);
        return {
            url: form.getAttribute('data-offline-url') || form.action || window.location.pathname,
            method: (form.method || 'POST').toUpperCase(),
            body: data,
            csrf: (data.get('csrfmiddlewaretoken') || ''),
            date: Date.now(),
        };
    }

    function queueSubmit(form) {
        var action = serializeForm(form);
        return addAction(action).then(function () {
            return getAll();
        }).then(function (all) {
            refreshBadge(all.length);
            showMessage('Action enregistrée localement. Synchronisation automatique au retour du réseau.', 'ok');
        });
    }

    function syncAll() {
        return getAll().then(function (actions) {
            if (!actions.length) {
                metaSet('lastSync', Date.now());
                if (elBadge) { elBadge.style.cssText = 'display:none;'; elBadge.dataset.idle = '1'; }
                return;
            }
            var ordered = actions.sort(function (a, b) { return a.date - b.date; });
            return ordered.reduce(function (chain, action) {
                return chain.then(function () {
                    return fetch(action.url, {
                        method: action.method,
                        credentials: 'same-origin',
                        headers: { 'X-Offline-Sync': '1' },
                        body: action.body,   // FormData inclut le CSRF
                    }).then(function (res) {
                        if (res.ok) {
                            return deleteAction(action.id);
                        }
                        // Conflit / refus serveur : on CONSERVE l'action et on
                        // le signale visuellement (décision conservée).
                        showMessage('Une action en attente a été refusée par le serveur et est conservée pour révision.', 'err');
                        return Promise.resolve(true);
                    });
                });
            }, Promise.resolve()).then(function () {
                metaSet('lastSync', Date.now());
            });
        }).then(function () {
            return getAll().then(function (remaining) {
                refreshBadge(remaining.length);
                setOnlineUI();
            });
        }).catch(function () {
            setOfflineUI();
        });
    }

    /* ── Interception des formulaires offline ───────────────────────────── */
    function bindForms() {
        var forms = document.querySelectorAll('form[data-offline]');
        Array.prototype.forEach.call(forms, function (form) {
            form.addEventListener('submit', function (ev) {
                if (navigator.onLine) return; // soumission réseau normale
                ev.preventDefault();
                queueSubmit(form).catch(function () {
                    showMessage('Impossible d\'enregistrer l\'action localement (IndexedDB indisponible).', 'err');
                });
            });
        });
    }

    /* ── Enregistrement Service Worker + écouteurs ──────────────────────── */
    function registerSW() {
        if (!('serviceWorker' in navigator)) return;
        window.addEventListener('load', function () {
            navigator.serviceWorker.register('/static/service-worker.js')
                .catch(function () { /* silencieux */ });
            navigator.serviceWorker.addEventListener('message', function (ev) {
                if (ev.data && ev.data.type === 'MEDSHARE_LAST_ONLINE') {
                    metaSet('lastSync', ev.data.timestamp);
                }
            });
        });
    }

    function updateLastSyncUI() {
        metaGet('lastSync').then(function (ts) {
            if (!ts) return;
            var el = document.getElementById('offline-last-sync');
            if (el) {
                var d = new Date(ts);
                el.textContent = 'Dernière synchronisation : ' +
                    d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) +
                    ' · ' + d.toLocaleDateString('fr-FR');
            }
        });
    }

    function boot() {
        if (!window.indexedDB) return;
        registerSW();

        if (navigator.onLine === false) {
            setOfflineUI();
            getAll().then(function (all) { refreshBadge(all.length); });
        } else {
            syncAll();
        }
        updateLastSyncUI();
        captureSnapshot().catch(function () { /* silencieux */ });

        window.addEventListener('online', syncAll);
        window.addEventListener('offline', function () {
            setOfflineUI();
            showMessage('Connexion perdue. Les actions seront mises en attente.', 'warn');
        });

        document.addEventListener('DOMContentLoaded', bindForms);
        if (document.readyState === 'interactive' || document.readyState === 'complete') bindForms();
    }

    boot();
})();