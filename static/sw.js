const CACHE = 'labor-aid-v51';
const SHELL = ['/', '/index.html', '/styles.css', '/app.js', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', e => {
  // cache:'reload' 绕过 HTTP 缓存安装：vendor 曾被历史 bug 的 index.html 毒化，默认缓存会把毒化副本带进每个新版本
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname === '/sw.js') return;   // SW 自身绝不缓存：否则版本升级永远不生效
  // 离线可看法条：缓存法条库 GET 接口
  if (url.pathname.startsWith('/api/laws') || url.pathname.startsWith('/api/law/')) {
    e.respondWith(caches.open(CACHE).then(async c => {
      const hit = await c.match(e.request);
      const net = fetch(e.request).then(r => { if (r.ok) c.put(e.request, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  // 壳资源网络优先：代码一改线上立刻生效，断网才回退缓存
  const NETWORK_FIRST = ['/', '/index.html', '/app.js', '/styles.css', '/manifest.webmanifest'];
  if (NETWORK_FIRST.includes(url.pathname)) {
    e.respondWith(caches.open(CACHE).then(async c => {
      try {
        const r = await fetch(e.request);
        if (r.ok) c.put(e.request, r.clone());
        return r;
      } catch (_) {
        const hit = await c.match(e.request);
        if (hit) return hit;
        throw new Error('offline');
      }
    }));
    return;
  }
  e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
});
