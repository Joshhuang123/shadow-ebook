// 改动 CSS/JS 后必须把版本号 +1,否则下面「静态资源缓存优先」会让用户继续看到旧样式。
// 这是 stale-while-revalidate: 先给缓存,后台再更新,所以同一台机器上
// 刚改完样式刷新页面可能「看起来没生效」,再刷一次才对 —— 很容易误判成改错了。
const CACHE_NAME = 'shadow-ebook-v18';
// R11: 字体从 install 预缓存里拿掉 (5 个 ttf ~ 1-2MB, 用户没开过页面也要下)
// 改成 runtime cache, 第一次访问页面时才按需缓存
const STATIC_ASSETS = [
  '/',
  '/tutor',
  '/grammar',
  '/ebook',
  '/stats',
  '/manifest.json',
  '/theme.js',
  '/sync.js',
  '/a11y.js',
  '/kid-touch.css',
  '/fonts/fonts.css',
  '/icon-48.png',
  '/icon-72.png',
  '/icon-96.png',
  '/icon-128.png',
  '/icon-144.png',
  '/icon-152.png',
  '/icon-192.png',
  '/icon-384.png',
  '/icon-512.png'
];

// 安装 Service Worker
self.addEventListener('install', (event) => {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Caching static assets');
        return cache.addAll(STATIC_ASSETS).catch(err => {
          console.log('[SW] Cache failed, continuing:', err);
        });
      })
      .then(() => {
        console.log('[SW] Skip waiting');
        return self.skipWaiting();
      })
  );
});

// 激活并清理旧缓存
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((name) => name.startsWith('shadow-') && name !== CACHE_NAME)
            .map((name) => {
              console.log('[SW] Deleting old cache:', name);
              return caches.delete(name);
            })
        );
      })
      .then(() => {
        console.log('[SW] Claiming clients');
        return self.clients.claim();
      })
  );
});

// 字体运行时缓存: 第一次请求 .ttf 时 cache.put, 后续 cache-first
function isFontRequest(url) {
  return url.pathname.startsWith('/fonts/') && url.pathname.endsWith('.ttf');
}

// 请求拦截
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 跳过非 GET 请求
  if (request.method !== 'GET') return;

  // 跳过 Chrome 扩展和其他非 HTTP 请求
  if (!url.protocol.startsWith('http')) return;

  // API 请求使用网络优先策略
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/audio/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.match(request);
        })
    );
    return;
  }

  // HTML页面使用网络优先，回退到缓存
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.match(request).then(cached => {
            return cached || caches.match('/') || new Response('Offline', { status: 503, statusText: 'Offline' });
          });
        })
    );
    return;
  }

  // 字体: cache-first (R11: 第一次访问才下载, 不再 install 时全预缓存)
  if (isFontRequest(url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // 静态资源(CSS / JS):网络优先,缓存兜底。
  //
  // 原来是缓存优先(stale-while-revalidate):先给旧缓存、后台再更新。
  // 在局域网小工具上这几乎没收益(网络本来就快),代价是**改了样式刷新
  // 页面看到的还是旧的**,很容易误判成「改错了」——这个坑踩过不止一次
  // (语法页卡片在暗色模式下一直是白底,源码是对的,就是缓存)。
  // 网络优先保留了离线兜底,又让改动立刻生效,所以换过来。
  // 字体仍然缓存优先:内容不可变,缓存命中没坏处。
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});

// 处理消息
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
  if (event.data === 'clearCache') {
    caches.delete(CACHE_NAME).then(() => {
      console.log('[SW] Cache cleared');
    });
  }
});