#!/usr/bin/env python3
"""拍宣传素材用的真实界面照。

全部用生产实例(真数据:1 本 Magic Tree House + 新概念 2A 课程),
家长页用隔离实例(PIN 0000),不碰用户密码。
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import CDP, launch, new_tab  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shots")
os.makedirs(OUT, exist_ok=True)
BASE = "http://localhost:5002"
ISO = "http://localhost:5003"
W, H = 1440, 900


def shot(cdp, path, name, full=False, theme="light", wait=2.6):
    cdp.call("Page.navigate", {"url": f"{BASE}{path}"})
    time.sleep(wait)
    cdp.evaluate(f"localStorage.setItem('shTheme','{theme}');"
                 f"document.documentElement.setAttribute('data-theme','{theme}');'ok'")
    time.sleep(0.8)
    if full:
        m = cdp.call("Page.getLayoutMetrics")
        h = min(int(m.get("contentSize", {}).get("height", H)), 3000)
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": W, "height": h, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1.0)
    s = cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": full})
    with open(f"{OUT}/{name}.png", "wb") as f:
        f.write(base64.b64decode(s["data"]))
    if full:
        cdp.call("Emulation.clearDeviceMetricsOverride")
    print("  ✓", name)


proc = launch(port=9500, profile="/tmp/chrome-promo", width=W, height=H)
try:
    tab = new_tab(port=9500, url=f"{BASE}/")
    cdp = CDP(tab["webSocketDebuggerUrl"])
    cdp.call("Runtime.enable")
    cdp.call("Page.enable")
    cdp.call("Network.enable")
    cdp.call("Network.setCacheDisabled", {"cacheDisabled": True})

    print("拍生产页:")
    shot(cdp, "/", "shelf")
    shot(cdp, "/grammar", "grammar")
    shot(cdp, "/stats", "stats")

    # 阅读器:打开 Magic Tree House
    cdp.call("Page.navigate", {"url": f"{BASE}/"})
    time.sleep(3.0)
    cdp.evaluate("localStorage.setItem('shTheme','day');"
                 "document.documentElement.setAttribute('data-theme','light');'ok'")
    time.sleep(0.6)
    print("  打开书:", cdp.evaluate("""(()=>{
        const cards=[...document.querySelectorAll('.shelf-card, .continue-btn, .book-card')];
        const hit=cards.find(c=>(c.textContent||'').toLowerCase().includes('camelot'))
                  || cards.find(c=>(c.textContent||'').includes('圣诞'))
                  || cards[0];
        if(hit){hit.click(); return 'clicked:'+(hit.textContent||'').slice(0,30);}
        return 'no-card:'+cards.length;
    })()"""))
    time.sleep(4.0)
    s = cdp.call("Page.captureScreenshot", {"format": "png"})
    with open(f"{OUT}/reader.png", "wb") as f:
        f.write(base64.b64decode(s["data"]))
    print("  ✓ reader")

    # 逐句导航:按两次下一句,展示当前句高亮
    cdp.evaluate("""(()=>{for(let i=0;i<2;i++){const b=document.querySelector('[data-action="nextSentence"]');if(b)b.click();}})()""")
    time.sleep(1.6)
    s = cdp.call("Page.captureScreenshot", {"format": "png"})
    with open(f"{OUT}/reader-sentence.png", "wb") as f:
        f.write(base64.b64decode(s["data"]))
    print("  ✓ reader-sentence")

    # 跟读页:选 MTH 第一章
    cdp.call("Page.navigate", {"url": f"{BASE}/tutor"})
    time.sleep(3.2)
    cdp.evaluate("""(()=>{
        const items=[...document.querySelectorAll('.unit-item')];
        const mth=items.find(i=>(i.textContent||'').includes('Magic Tree House'));
        if(mth) mth.click();
        return 'mth';
    })()""")
    time.sleep(2.2)
    cdp.evaluate("""(()=>{
        const items=[...document.querySelectorAll('[data-action="selectChapter"]')];
        if(items[0]) items[0].click();
        return 'ch0';
    })()""")
    time.sleep(3.0)
    s = cdp.call("Page.captureScreenshot", {"format": "png"})
    with open(f"{OUT}/tutor-mth.png", "wb") as f:
        f.write(base64.b64decode(s["data"]))
    print("  ✓ tutor-mth")

    # 家长页(隔离实例)
    print("拍家长页(隔离实例):")
    tab2 = new_tab(port=9500, url=f"{ISO}/parent")
    c2 = CDP(tab2["webSocketDebuggerUrl"])
    c2.call("Runtime.enable")
    c2.call("Page.enable")
    c2.call("Network.enable")
    c2.call("Network.setCacheDisabled", {"cacheDisabled": True})
    c2.call("Page.navigate", {"url": f"{ISO}/parent"})
    time.sleep(3.0)
    c2.evaluate("localStorage.setItem('shTheme','day');"
                "document.documentElement.setAttribute('data-theme','light');'ok'")
    time.sleep(0.6)
    s = c2.call("Page.captureScreenshot", {"format": "png"})
    with open(f"{OUT}/parent-login.png", "wb") as f:
        f.write(base64.b64decode(s["data"]))
    print("  ✓ parent-login")
    for i, v in enumerate("0000"):
        c2.evaluate(f"(()=>{{const el=document.getElementById('pwd{i+1}');"
                    f"if(el){{el.focus();el.value='{v}';"
                    f"el.dispatchEvent(new Event('input',{{bubbles:true}}));}}}})()")
        time.sleep(0.3)
    time.sleep(3.0)
    m = c2.call("Page.getLayoutMetrics")
    h = min(int(m.get("contentSize", {}).get("height", 900)), 3000)
    c2.call("Emulation.setDeviceMetricsOverride", {
        "width": 1180, "height": h, "deviceScaleFactor": 1, "mobile": False})
    time.sleep(1.0)
    s = c2.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
    with open(f"{OUT}/parent-full.png", "wb") as f:
        f.write(base64.b64decode(s["data"]))
    print("  ✓ parent-full")

    errs = cdp.drain_events()
    bad = [e for e in errs if e.get("params", {}).get("level") == "error"]
    print("console errors:", len(bad))
    for e in bad[:5]:
        print("   ", e["params"].get("text", "")[:140])
finally:
    proc.terminate()
