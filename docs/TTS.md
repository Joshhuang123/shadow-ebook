# 朗读语音 (TTS Provider)

> 一句话:朗读用什么声音,**由家长在页面上决定**,不是一个写死的常量。

## 为什么要有这层

原来只有一条路:`edge-tts`(微软 Edge 的免费接口)。它是「免费但要联网」
的上游,一旦断网、被限流、或者对方改了接口,整条朗读链路就哑了 ——
而且是**静默**哑的:跟读页点「听标准发音」会退回平板自带的声音,
听感上「好像还能用」,家长根本发现不了服务端已经挂了。

> ⚠️ **edge-tts 必须 >= 7.3.1**。7.2.8 会被微软上游直接 403:
> 它的防滥用 token(`Sec-MS-GEC`)算法变了,旧版算出来的值对不上。
> 症状是 `WSServerHandshakeError: 403` —— 看起来像「微软挂了」,
> 其实只是版本旧了。2026-10-19 升到 7.3.1 就恢复。

自用工具更不能被上游卡住:换引擎应该是一个设置项,而不是改环境变量重启。

## 四种来源

在 **家长页 → 「朗读声音」** 里切换。

| provider | 做什么 | 要联网吗 | 典型场景 |
|---|---|---|---|
| `edge` | 微软 Edge TTS(神经音色) | 要 | **默认**。音色最自然,免费 |
| `macos_say` | macOS 自带 `say` 命令 | 不要 | 离线兜底:免费、可调语速,音质比微软差一档 |
| `openai_compatible` | 接你自己的服务 | 本地服务不需要 | 自己的云 key、局域网里的本地模型 |
| `device` | 服务端完全不合成,平板用自己的声音念 | 不要 | 完全离线、零延迟、不消耗额度 |

### 微软的语速微调

`edge` 多一个「语速微调」字段(`-30%` ~ `+30%`,默认 `+0%`)。
神经音色本来就比机械音慢,对刚开始学的孩子再降 10% 更跟得上。
**它会进缓存指纹** —— 改了语速,旧音频立刻作废重生成,
不会出现「设置改了但读出来还是原来那个语速」。

### 微软这条线会重试

实测(edge-tts 7.3.1,2026-10-19)微软那边单句合成要 3~5 秒,冷启动能到 12 秒,
并发超过 4 就开始回 503 限流。所以 `_synthesize_edge` 会对
**瞬时错误**(503 / 超时 / 连接断开)重试一次,不会一次失败就退回平板机械音
—— 那等于「微软音色时好时坏」。

孩子点按钮那条路超时仍然是 20 秒(等太久不如给个能听的),
预生成那条路放宽到 45 秒(后台活,没人等)。

`macos_say` 走系统 `say`,再转成 mp3(有 ffmpeg 用 ffmpeg,没有退回 afconvert 出 m4a)。
系统音色里 `Samantha`(美式女声)、`Alex`、`Daniel` 比默认音色自然得多,
在家长页填系统音色的名字即可,语速用 `say_rate`(词/分钟,默认 160 左右比较自然)。

`device` 是真正意义上的「本地 TTS」:**服务器一个音频都不生成**,
连预生成都会跳过,`/api/tts` 直接回 409 + `use_device_voice`,
前端据此走浏览器的 `speechSynthesis`;同时会优先挑
Siri / Premium / Enhanced / Natural 这类高质量系统音色,语速放慢到 0.85。

## 孩子端到底走哪条路

阅读器点「读一句」时,按这个顺序找:

```
浏览器 IndexedDB 缓存  →  服务端合成(带 provider 指纹的音频缓存)  →  设备语音
```

**这条链路的顺序是这一轮改动的核心。**
原来阅读器的「读一句」**根本不调服务端**,直接用 `speechSynthesis` ——
所以家长在家长页里精心挑了引擎、音色、语速,孩子那边一点变化都没有,
永远是平板的机械音。现在服务端引擎终于接上了。

服务端合成时,顶栏那个音色下拉会隐藏(音色由家长页统一管),
避免两处设置打架。

## 接自己的服务

只要求一件事:**实现 OpenAI 的 `POST {base_url}/audio/speech`**。

```jsonc
// 请求
POST http://192.168.1.10:8000/v1/audio/speech
Authorization: Bearer <api_key>     // 本地服务可以不带
Content-Type: application/json

{
  "model": "tts-1",
  "input": "This is a sentence.",
  "voice": "alloy",
  "response_format": "mp3",          // mp3/opus/aac/flac/wav/pcm
  "speed": 1.0                       // 不等于 1.0 时才发
}
```

响应就是音频字节流,`Content-Type` 随便(我们不校验)。

这个形状是 OpenAI 定的,**大量本地推理服务直接照抄**:

- Piper:用它的 OpenAI 兼容外壳,或自己写个十行的转发
- GPT-SoVITS / CosyVoice:它们的服务端一般已提供 `/v1/audio/speech`
- 任何云 TTS 网关(OpenAI、Azure 转发、one-api 类聚合)
- 甚至另一台机器上的 `edge-tts` 包装服务

之所以不为每个服务各写一个适配器,是因为这一类接口形状高度一致;
真遇到形状不同的,加一个分支的成本也就十几行(见 `_synthesize_openai_compat`)。

### 填表提示

- **服务地址**填到 `/v1` 这一层即可,程序自己拼 `/audio/speech`
- **API Key** 本地服务一般留空。**留空 = 不修改**已保存的密钥,
  想清空要点「清除已保存的」—— 否则家长每次改模型名都得重输一遍长密钥
- **音色**填服务支持的名字,微软那边是 `en-US-AriaNeural` 这种

改完先点 **「试听一句」**:它用**表单里还没保存的草稿**直接合成并播放,
不用先保存再试。失败会给出可读原因 —— 「连不上这个服务」「服务拒绝了密钥」
「这个地址没有 /audio/speech 接口」—— 而不是把一个 socket 异常丢给你。

## 换引擎之后会发生什么

- **旧音频变成孤儿**:缓存文件名里带 provider 指纹,所以旧音频永远不会被命中,
  但文件还占着磁盘。预生成过的书能有几百 MB 到几个 GB。
  换引擎之后在家长页点一次 **「清空音频缓存」** 即可。
- **不会自动全量预生成**:保存设置不会偷偷跑几千条合成。要整本预生成,
  去跟读页点「预下载音频」—— 这也是刻意的:自动触发会立刻把家里的
  TTS 服务打满,连按两次保存还会起两个线程互相踩状态。
- **设备侧要刷新页面**:孩子端在页面加载时读一次「服务端要不要合成」,
  不做实时推送。

## 安全边界

- 密钥**只存在服务器的 SQLite 里**(`parent_section['tts']`),
  任何接口都不会返回它本体,只回 `has_api_key` 布尔值
- 写设置 / 试听 / 清缓存都需要家长 PIN(`require_parent_auth`)
- 读设置是公开的,但只返回 `{provider, voice, server_synthesis}` ——
  孩子端只需要知道「该不该调 `/api/tts`」

## 代码位置

| 文件 | 负责 |
|---|---|
| `extensions/tts_providers.py` | provider 抽象、设置读写、缓存指纹、错误翻译 |
| `extensions/tts.py` | `/api/tts`、`/api/tts/settings`、`/api/tts/test`、`/api/tts/cache`、`/api/tts/pregenerate`、缓存 LRU |
| `web/js/index.js` | 阅读器播放链:IndexedDB → 服务端 → 设备语音 |
| `web/parent.html` / `web/js/parent.js` | 配置卡 + 试听 |
| `tests/test_tts_providers.py` | 21 条守护(缓存隔离、密钥不外泄、错误映射、鉴权) |

## 加一个新 provider

1. 在 `tts_providers.PROVIDERS` 里加名字
2. 写 `_synthesize_xxx(text, voice, settings) -> bytes`,在 `synthesize()` 里加分支
3. 错误一律抛 `TTSError(message, detail, http_status=..., retry_after=...)`
   —— `message` 给家长看,`detail` 只进日志
4. 家长页的下拉框加一项
5. 补一条测试:换 provider 之后缓存指纹必须变

## 相关环境变量

只有默认音色可覆盖(换 provider 时不再生效):

```bash
DEFAULT_TTS_VOICE=en-US-JennyNeural
```

另外预生成的并发数可以调(微软上游并发超过 4 会 503 限流):

```bash
SHADOW_TTS_PREGEN_CONCURRENCY=3
```
