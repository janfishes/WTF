/* WTF Log service worker.
   Referenced by index.html since the install-prompt work, but this file never
   actually existed — the registration 404'd silently on every launch. Now it
   does the one job worth doing for a single-file app: it keeps the last good
   copy of the page itself in Cache Storage and serves it INSTANTLY on every
   open, then re-fetches the live page in the background and stores it for the
   next open (stale-while-revalidate).

   Fit with the update pill (index.html, "Update check"): the pill's fetch is
   not a navigation, so it passes straight through this worker to the network,
   sees the live BUILD_NUM, and offers the reload — exactly the flow the pill
   was designed for ("pill appears when a stale cached copy loads while a
   newer build is live"). The pill's tap handler re-fetches the page into this
   cache before reloading, so the reload can't be served the same stale copy.

   Everything that is not a navigation — tiles, NOAA/buoy fetches, the update
   check, CDN scripts — is untouched here. Tiles have their own cache in the
   page (offline map download). */

const SHELL_CACHE = 'wtf-shell-v1';
const SHELL_URL = './index.html';

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL_CACHE)
      .then((c) => c.add(new Request(SHELL_URL, { cache: 'no-store' })))
      .catch(() => {})              // offline install: cache fills on first fetch instead
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return;   // only the page itself; all else goes to the network
  e.respondWith(
    caches.open(SHELL_CACHE).then((cache) =>
      cache.match(SHELL_URL).then((cached) => {
        const refresh = fetch(e.request)
          .then((res) => {
            if (res && res.ok) cache.put(SHELL_URL, res.clone());
            return res;
          })
          .catch(() => null);
        if (cached) return cached;             // instant open; refresh lands for next time
        return refresh.then((res) => res || new Response(
          'Offline, and no saved copy of the app yet. Connect once and reopen.',
          { status: 503, headers: { 'Content-Type': 'text/plain' } }
        ));
      })
    )
  );
});
