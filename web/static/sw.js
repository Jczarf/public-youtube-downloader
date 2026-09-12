// Transitional cleanup worker.
//
// The downloader does not need an offline cache, and retaining executable
// application code in a persistent Service Worker increases rollback and
// supply-chain blast radius. Existing installations may still have the old
// worker registered, so this shim clears its cache and unregisters itself.

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter(key => key.startsWith("mediaflow-"))
        .map(key => caches.delete(key)),
    );
    await self.registration.unregister();
    await self.clients.claim();
  })());
});
