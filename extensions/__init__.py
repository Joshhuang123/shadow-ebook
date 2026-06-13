"""
extensions/ — 每个模块是一个域(books / tts / auth / parent_data / courses / pwa / db),
通过 register_routes(app) 把自己的路由挂到 Flask app 上。

keel Rule 4: 显式 ownership。每个模块顶部都有"Owns / Does NOT own"声明。
"""