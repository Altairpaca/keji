/* 客迹 Service Worker：缓存应用壳与离线错误页（ADR-014）。
 *
 * 只缓存 GET 的应用壳（/static/ 资源、manifest、导航页）与离线错误页，
 * 不缓存任何编辑类数据：离线时仅保证「壳」可用，写操作一律走网络。
 */
const CACHE_NAME = "keji-shell-v1";
const SHELL_URLS = ["/", "/offline/", "/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; // 不拦截写操作（ADR-014）
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // 静态资源与 manifest：cache-first，后台更新缓存
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.json") {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() => cached);
        return cached || network;
      }),
    );
    return;
  }

  // 导航请求：network-first，离线时回退到缓存的离线错误页
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() =>
          caches.match("/offline/").then((hit) => hit || caches.match(request)),
        ),
    );
  }
});
