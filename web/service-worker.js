// 改动 CSS/JS/HTML 后把版本号 +1。activate 时会删掉所有旧版缓存
// (见下方 CACHE_NAME 过滤),所以老设备不会继续吃旧样式。
//
// v19:不只是发版 —— 有浏览器 profile 的缓存里存进了**写坏的文件**
// (改到一半时被缓存下来),结果是整页白屏、DOM 还在但一个字都不画。
// 换名 = 一次性把这些坏缓存整体丢掉,不用去教用户怎么清缓存。
const CACHE_NAME = 'shadow-ebook-v19';
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

  // API 请求:**纯网络,不缓存**(2026-10-19 改)。
  //
  // 原来这里是「网络优先 + 缓存兜底」,并且把响应 cache.put 下来。
  // 两个问题,第二个是致命的:
  //   1) /api/ 下全是**可变状态** —— 阅读进度、统计、孩子档案。
  //      缓存它们等于把「上次看到的数据」当真相,家长刚改完的东西
  //      可能几秒钟内还是旧的。
  //   2) 更要命的是实测踩到过:某个浏览器 profile 的缓存里存了一份
  //      坏掉的 /api/book/<id> 响应。点「继续读」时,请求根本没到服务器
  //      (服务端日志零记录),前端拿到 success 不为真的响应后**静默什么都不做**,
  //      表现就是「点了没反应」。用户完全无从判断是网络坏了还是应用坏了。
  //
  // 现在不缓存 API,请求要么真到服务器(拿到新鲜数据),要么 reject 让前端
  // 走 catch 分支弹错误。宁可明着报错,也不要静默地给一份陈旧数据。
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() => new Response(
        JSON.stringify({ success: false, error: 'offline' }),
        { status: 503, headers: { 'Content-Type': 'application/json' } }
      ))
    );
    return;
  }

  if (url.pathname.startsWith('/audio/')) {
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
        .catch(() => caches.match(request))
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