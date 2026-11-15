/* FieldWise service worker — app shell only.
 *
 * Strategy:
 *   - Static shell (HTML/CSS/JS/icons/manifest): cache-first, updated in place.
 *   - Leaflet CDN assets: stale-while-revalidate.
 *   - Everything else (the API): never cached. A farm plan is personal and
 *     must be freshly computed; the last plan is kept in localStorage instead.
 */
"use strict";

const VERSION = "fieldwise-v2";
const SHELL = `${VERSION}-shell`;
const VENDOR = `${VERSION}-vendor`;

const SHELL_FILES = [
  "/app/",
  "/app/index.html",
  "/app/styles.css",
  "/app/app.js",
  "/app/manifest.webmanifest",
  "/app/icons/favicon.svg",
  "/app/icons/icon-192.png",
  "/app/icons/icon-512.png",
  "/app/icons/icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL)
      .then((cache) => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== SHELL && key !== VENDOR).map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (url.pathname.startsWith("/api/")) return;

  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response && response.ok) {
              const copy = response.clone();
              caches.open(SHELL).then((cache) => cache.put(request, copy)).catch(() => {});
            }
            return response;
          })
          .catch(() => cached || caches.match("/app/index.html"));
        return cached || network;
      })
    );
    return;
  }

  if (url.hostname === "unpkg.com") {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response && response.ok) {
              const copy = response.clone();
              caches.open(VENDOR).then((cache) => cache.put(request, copy)).catch(() => {});
            }
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});
