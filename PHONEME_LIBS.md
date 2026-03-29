# 音素分析库推荐

## 1. **CMU Pronouncing Dictionary (cmudict)**
```
GitHub: https://github.com/cmusphinx/cmudict
安装: pip install cmusphinx-fragment 不需要，直接下载 dict 文件
```

## 2. **pronouncing** - CMU Pronouncing Dictionary 的 Python 封装
```
PyPI: https://pypi.org/project/pronouncing/
GitHub: https://github.com/aparrish/pronouncing
安装: pip install pronouncing
功能:
  - 单词 -> 音素 (phonemes)
  - 音素 -> 押韵词
  - 音标 (ARPAbet -> IPA)
```

## 3. **Phonemizer** - 多语言音素转换
```
GitHub: https://github.com/bootphon/phonemizer
PyPI: https://pypi.org/project/phonemizer/
安装: pip install phonemizer
功能:
  - 文本 -> 音素/IPA
  - 支持多种语言 (英语, 法语, 德语等)
  - 带重音/语调
```

## 4. **PyCMU Dict** - CMU Dict 的 Python 接口
```
安装: pip install pycmudict
功能: 访问 CMU 音素词典
```

## 5. **eaflow** - 音素级别的语音流分析
```
GitHub: https://github.com/asrchampion/eaflow
功能: 音素级别的语音流分析、对齐
```

## 6. **Montreal Forced Aligner** (更高级)
```
GitHub: https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner
功能:
  - 音频-文本强制对齐
  - 音素级别的时间戳
  - 基于 Kaldi
```

## 7. **Parselmouth-Praat** - 语音分析
```
PyPI: https://pypi.org/project/parselmouth/
GitHub: https://github.com/YannickJadoul/Parselmouth-Praat
功能:
  - Praat 语音分析 Python 接口
  - 音高、时长、共振峰分析
```

## 推荐方案

### 简单方案 (立即可用)
```bash
pip install pronouncing phonemizer
```

### 高级方案 (更准确)
```bash
# Montreal Forced Aligner (需要安装依赖)
git clone https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner
cd Montreal-Forced-Aligner
# 按文档安装 Kaldi 和其他依赖
```

## 集成到 Shadow Learning

```python
# 示例: 使用 pronouncing 做音素对比
import pronouncing

# 获取单词的音素列表
phones = pronouncing.phones_for_word("creativity")
# ['K', 'R', 'IY1', 'EY1', 'T', 'IH1', 'V', 'IH0', 'T', 'IY0']

# 获取音素的描述
def get_phoneme_tip(phoneme):
    tips = {
        'IY': "长 'ee' 音，像 'see'",
        'EY': "长 'ay' 音，像 'say'",
        'K': "清辅音 'k'，像 'kite'",
        'R': "卷舌 'r' 音",
        'TH': "舌尖咬舌 'th' 音，像 'the'",
    }
    return tips.get(phoneme, f"练习音素 {phoneme}")
```

## 实用资源

- **CMU Dict 文件**: https://github.com/cmusphinx/cmudict/blob/master/cmudict.dict
- **ARPAbet 到 IPA 对照表**: https://en.wikipedia.org/wiki/ARPABET
- **音素发音指南**: 每个音素都有对应的发音口型视频
