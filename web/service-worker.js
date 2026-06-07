const CACHE_NAME = 'shadow-ebook-v11';
const STATIC_ASSETS = [
  '/',
  '/index',
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
  '/fonts/noto-serif-sc-400.ttf',
  '/fonts/noto-serif-sc-600.ttf',
  '/fonts/noto-serif-sc-700.ttf',
  '/fonts/nunito-400.ttf',
  '/fonts/nunito-600.ttf',
  '/fonts/nunito-700.ttf',
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

const MAX_CACHE_SIZE = 50;

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

// 清理过多缓存
async function cleanupCache() {
  const cache = await caches.open(CACHE_NAME);
  const keys = await cache.keys();
  if (keys.length > MAX_CACHE_SIZE) {
    // 删除最老的缓存项
    const deleteCount = keys.length - MAX_CACHE_SIZE;
    for (let i = 0; i < deleteCount; i++) {
      await cache.delete(keys[i]);
    }
  }
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

  // 静态资源使用缓存优先策略
  event.respondWith(
    caches.match(request)
      .then((cachedResponse) => {
        if (cachedResponse) {
          // 返回缓存并更新缓存
          fetch(request)
            .then((response) => {
              if (response.ok) {
                caches.open(CACHE_NAME).then((cache) => {
                  cache.put(request, response);
                });
              }
            })
            .catch(() => {});
          return cachedResponse;
        }

        return fetch(request)
          .then((response) => {
            if (response.ok) {
              const responseClone = response.clone();
              caches.open(CACHE_NAME).then((cache) => {
                cache.put(request, responseClone);
              });
            }
            return response;
          });
      })
      .catch(() => new Response('Offline', { status: 503, statusText: 'Offline' }))
  );
  
  // 定期清理缓存
  cleanupCache();
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