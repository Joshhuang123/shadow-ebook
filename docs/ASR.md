# ASR:跟读怎么把声音变成文字 (2026-10-21)

跟读链路:录音 → 转写 → 词级差异 → 音素归因 → 家长/孩子的反馈。
转写这一步用的是 **faster-whisper**,不是官方 `openai-whisper`。
这篇记的是**为什么这么选、体积账怎么算、在国内怎么装**。

## 为什么不用官方 whisper

用户的原话:「我怕 whisper 太大了」。

官方 `openai-whisper` 依赖 **PyTorch**。torch 装下来就是 2.5GB 上下,
而实际用到的只是几个语音识别模型 —— 贵的是运行时,不是模型。

`faster-whisper` 用 **CTranslate2** 做推理,不需要 torch:

| 方案 | 依赖体积 | 模型(base) | 合计 |
|---|---|---|---|
| 官方 openai-whisper | +2.5GB(torch) | 145MB | **~2.65GB** |
| **faster-whisper(现在用的)** | **+211MB** | 141MB | **~350MB** |

实测(2026-10,macOS arm64):

```
venv:  87MB → 298MB   (+211MB)
模型:  ~/.cache/shadow-whisper/base/  141MB
磁盘:  装完还剩 26GB
```

`speed`:模型加载 1.2s,短句转写 0.8~4.9s(CPU,无 GPU)。

精度对短句完全够用:

| 实际音频 | 转写结果 |
|---|---|
| "I want three ships." | `I want three ships.` ✓ |
| "What are you doing?" | `What are you doing?` ✓ |
| "The little prince saw a fish." | `The little Prince saw a fish.`(首词大写,见下) |

## 剪枝做到哪一步

1. **换掉 torch** —— 最大的那刀,砍掉 2.5GB。
2. **int8 量化**(`WHISPER_COMPUTE=int8`)—— 模型和内存都省,短句精度影响很小。
3. **beam=1**(贪心解码)—— 短句不需要束搜索。
4. **模型选 base**(141MB)—— 孩子的句子很短,base 够用。
   要更小:`WHISPER_MODEL=tiny`(75MB),再小准确率掉得快。
5. **VAD 裁静音**(`vad_filter=True`)—— 孩子录音前后总有静默,先切掉再识别,
   既快又不容易在噪声上猜词。

砍不到更小的原因:模型权重本身是必须的,base 已经是「够用且小」的点。
再小(`tiny`)会让「fish / wish」这种关键差别识别不出来 ——
而这恰好是音素层要抓的东西。

## 在国内怎么装

**PyPI 直连只有 93KB/s**,换镜像:

```bash
cd ~/shadow-learning
venv/bin/pip install -q -i https://mirrors.aliyun.com/pypi/simple/ faster-whisper
```

**模型在 HuggingFace 上,直连 30KB/s**(141MB 要下一个多小时)。
用 `hf-mirror.com` + 并行分块下载,实测 89 秒下完:

```bash
URL="https://hf-mirror.com/Systran/faster-whisper-base/resolve/main/model.bin"
FINAL=$(curl -sL -o /dev/null -m 25 -w '%{url_effective}' "$URL")
python3 scripts/pardl.py "$FINAL" ~/.cache/shadow-whisper/base/model.bin 145217532 16
```

`scripts/pardl.py` 是 16 路并行分块下载器,**必须逐块校验大小** ——
裸 bash 并行会少 7MB(最后一块没落全),表现是加载时报「model.bin 损坏」。

下完的目录结构(faster-whisper 要的是 CTranslate2 格式):

```
~/.cache/shadow-whisper/base/
├── config.json
├── model.bin        (145,217,532 B)
├── tokenizer.json
└── vocabulary.txt
```

服务会**优先用这个本地目录**,不联网。

## ⚠️ av 必须钉在 15.1.0

faster-whisper 1.2.1 声明 `av>=11`,但**没有上限**。而它内部调用
`av.open(..., metadata_errors=...)`,这个参数在 **av>=16 被移除了**。

```
TypeError: open() got an unexpected keyword argument 'metadata_errors'
```

装 av 16/17/19 全都炸;av 14.x 又没有 cp312 轮子(装不上)。
**15.1.0 是唯一能用的版本**,所以 `requirements-dev.txt` 里钉死。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `WHISPER_BACKEND` | `auto` | `faster` / `openai` / `auto`(有 faster 用 faster) |
| `WHISPER_MODEL` | `base` | `tiny` / `base` / `small` / `medium` / `large` |
| `WHISPER_COMPUTE` | `int8` | 量化类型,CPU 上够用 |
| `WHISPER_BEAM` | `1` | 束搜索宽度,短句用贪心 |
| `WHISPER_CACHE_DIR` | `~/.cache/shadow-whisper` | 模型放哪(可指向外置盘) |

## 没装会怎样

不装 faster-whisper,服务照常起:跟读接口返回 **503**,
前端降级成「只有转写没有 AI 点评」的静态反馈。
不会崩,只是少了「读得很准,继续保持」这种话。

装了但模型加载失败(缓存损坏、av 版本不对)→ 也是 503,
**不是 500**(`_load_asr` 把所有加载异常都包成 `RuntimeError`)。

## 一个反直觉的坑:漏读不能算到音素头上

whisper 自己会**归一化**句子:音频里 "The little prince saw a fish."
被转写成 "little Prince saw a fish." —— 开头的 "The" 没了,还把 "prince" 首字母大写了。

所以**漏读**不是孩子漏读,是模型改写了句子。
如果按「原句有、转写没有」去归因音素,就会把 "the" 里的 /DH/ 和
"little" 里的 /AH/ 冤枉成「孩子这两个音不稳」。

因此:**漏读一律不归因到音素**(`extensions/phonemes.py` 里专门处理)。
读错的音要归因,漏掉的词不归因 —— 除非孩子真的是发音不到位导致模型没听出来,
但那个我们判断不了,宁可不指。

相关:大写这件事同理 —— whisper 会给句首单词加首字母大写,
比对前要小写归一,否则 "Prince" 和 "prince" 会被当成两个词。

## 接口

`POST /api/recording/feedback` —— `audio`(文件)+ `sentence`(原句)

```json
{
  "success": true,
  "transcript": "The wish is here.",
  "similarity": 0.94,
  "errors": [{"got": "wish", "expected": "fish", "tip": ""}],
  "feedback": null,
  "ai_unavailable": true,
  "phoneme_tips": [{
    "word": "fish", "heard": "wish", "precise": true,
    "phonemes": [{"id": "phoneme:F", "label": "F",
                  "hint": "上齿轻咬下唇,气从缝里挤出来(像 fish)", "vowel": false}]
  }]
}
```

`ai_unavailable: true` 表示 LLM 没配(或者调用失败)——
**转写、差异、音素提示照常返回**,前端用静态文案兜底。

静态兜底不是「随机夸奖」—— 那是**事实**:
「把 earthy 读成 early」「『early』里的 /L/ 还不稳（舌尖顶住上齿龈…）」。
早先这里直接显示「很棒!继续保持!🎉」,孩子读错了却被表扬,那是骗人。

LLM 配好后这一项才是完整的鼓励 + 建议。支持的厂商见 README
(`deepseek` / `minimax` / `moonshot`,不设 `LLM_PROVIDER` 时按环境里
配了谁的 key 自动挑)。

## 相关文件

- `extensions/feedback.py` —— ASR 懒加载(`_ASR` / `_FasterWhisperAdapter` / `_load_asr`)、跟读路由
- `extensions/phonemes.py` —— 音素归因与掌握度
- `docs/KG.md` —— 音素层的图谱接法
- `tests/test_feedback.py` —— 适配层契约、锁、错误包装
