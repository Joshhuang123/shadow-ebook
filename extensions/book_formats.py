"""非 EPUB 格式的电子书转换器。

为什么单独一个模块
------------------
EPUB 走 `extensions/books.py` 里那条老路(那里有二十来个历史 bug 的修复,
动它风险太高,本模块一行不碰)。但家长手里的书不全是 EPUB —— PDF、TXT
占了大头,HTML/DOCX 也常见。

所以这里的职责只有一个:**把别的格式变成和 EPUB 导入一模一样的结构**,
之后分句、查词、朗读、跟读、蓝思值、封面这些全都能直接复用,不需要
为每种格式各写一套下游逻辑。

产出的 `book_data` 结构与 EPUB 导入完全一致:

    {
      "book": 标题,
      "id": ...,
      "chapters": [{"name": ..., "sentences": [...]}],
      "cover": "/data/covers/xxx.png" 或 "",
      "creator": 作者或 None,
      "publisher"/"date"/"language"/"description"/...: 尽力而为,
      "toc": [],
    }

分句/分章的判定直接复用 `extensions/books.py` 里的 `_split_sentences` /
`_is_chapter_heading` —— 两边必须一致,否则同一本书用 EPUB 导入和用 TXT
导入会得到不同的断句,孩子点词查义会时灵时不灵。
"""
import io
import logging
import os
import re
from html import unescape
from pathlib import Path

logger = logging.getLogger(__name__)

# 家庭场景里真实会用到的格式
SUPPORTED_EXTENSIONS = ('.epub', '.pdf', '.txt', '.text', '.md', '.markdown',
                        '.html', '.htm', '.docx', '.mobi', '.azw', '.azw3', '.prc')

# 一次导入允许的最大体积。EPUB 原来没有上限,这里统一收一下,
# 免得有人在局域网里传一个 500MB 的 PDF 把内存吃光。
MAX_UPLOAD_BYTES = 120 * 1024 * 1024

# 扫描版 PDF 的判定阈值:每页平均提取到的字符数低于这个值,
# 基本可以断定这本书是图片扫描的,提取出来的是空白。
_MIN_CHARS_PER_PDF_PAGE = 60


class ConversionError(Exception):
    """转换失败。message 给家长看,detail 进日志。"""


# === 文本解码 ===

def decode_text(raw: bytes) -> str:
    """按常见编码依次尝试解码,返回第一个成功的。

    家里的 TXT 编码很杂:UTF-8 / UTF-8-BOM / UTF-16 / GBK(中文 Windows
    存的)/ Big5(繁体)/ CP1252(西文)。全试一遍总比给用户报
    「乱码」强。
    """
    for enc in ('utf-8-sig', 'utf-8', 'utf-16', 'gb18030', 'big5',
                'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # latin-1 不会失败,理论上到不了这里;真到了就强制替换兜底
    return raw.decode('utf-8', errors='replace')


# === HTML → 纯文本 ===

_SCRIPT_RE = re.compile(r'<(script|style)[^>]*>.*?</\1>', re.I | re.S)
_TAG_RE = re.compile(r'<[^>]+>')
_BLOCK_RE = re.compile(r'</\s*(p|div|br|li|h[1-6]|tr)\s*>|<\s*br\s*/?>', re.I)


def html_to_text(html: str) -> str:
    """HTML → 纯文本。保留段落/换行结构(换行后面还要断句)。"""
    if not html:
        return ''
    s = _SCRIPT_RE.sub(' ', html)
    # 块级标签结束 → 换行,否则一整篇会挤成一行
    s = _BLOCK_RE.sub('\n', s)
    s = _TAG_RE.sub(' ', s)
    s = unescape(s)
    s = re.sub(r'[ \t ]+', ' ', s)
    s = re.sub(r'\n\s*\n\s*\n+', '\n\n', s)
    return s.strip()


# ============================================================
# DRM 检测
# ============================================================
# 「为什么我的书导不进来」的第一答案不是格式,是加密。
# 图书馆借的书(OverDrive/Libby)、Kindle 买的大多带 DRM,
# 文件结构合法、扩展名也是 .epub,但正文是加密的 —— 任何自建阅读器
# 都读不了。家长看到的是「导入失败」,完全不知道为什么。
#
# 所以这里要**提前**识别出来,并告诉他该去哪拿一份没加密的。

# EPUB 里的加密标记。字体嵌入混淆(font obfuscation)也用
# encryption.xml,但它不是 DRM —— 别把它误判成 DRM,否则一大半
# 正常的 EPUB 会被冤枉。真正的 DRM 都带下面的 URI。
_DRM_ALGORITHMS = (
    'http://ns.adobe.com/pdf/enc#',      # Adobe ADEPT
    'http://ns.adobe.com/adept',
    'http://www.w3.org/2001/04/xmlenc#',   # 通用 XML 加密
    'http://readium.org/2014/01/lcp',     # Readium LCP
    'http://www.idpf.org/2016/encryption#',
)

# ACSM(OverDrive / Libby 借书用的就是它)
_ACSM_MARKER = 'META-INF/sinf.xml'
# 旧版 DRM
_RIGHTS_MARKER = 'META-INF/rights.xml'
# Readium LCP 许可
_LCP_MARKER = 'META-INF/license.lcpl'


class DrmError(ConversionError):
    """这本书带加密保护(DRM),导不进自建阅读器。"""


def detect_epub_drm(names, read=None):
    """EPUB 是不是带 DRM。names = zip 里的文件名列表。

    read(name) -> bytes 可选,用来读 encryption.xml 的内容。
    """
    name_set = {n.lower() for n in names}
    if _ACSM_MARKER.lower() in name_set:
        return 'acsm'
    if _RIGHTS_MARKER.lower() in name_set:
        return 'rights'
    enc = 'meta-inf/encryption.xml'
    if enc in name_set and read is not None:
        try:
            xml = read('META-INF/encryption.xml')
        except Exception:
            xml = b''
        text = xml.decode('utf-8', errors='ignore') if isinstance(xml, bytes) else str(xml)
        for algo in _DRM_ALGORITHMS:
            if algo in text:
                return 'adept'
    if _LCP_MARKER.lower() in name_set:
        return 'lcp'
    return None


def detect_mobi_drm(raw: bytes) -> bool:
    """MOBI/AZW3 的 EXTH 里有没有 DRM 记录。

    MOBI 头:偏移 60 是 'EXTH',之后 4 字节长度、4 字节条数,
    然后每条记录是 4 字节类型 + 4 字节长度 + 数据。
    类型 0x01 = DRM,值 1 = 无 DRM,2/3 = 有。
    """
    if len(raw) < 80 or raw[60:64] != b'EXTH':
        return False
    try:
        import struct
        count = struct.unpack('>I', raw[68:72])[0]
        pos = 72
        for _ in range(min(count, 200)):
            if pos + 8 > len(raw):
                break
            rtype, rlen = struct.unpack('>II', raw[pos:pos + 8])
            data = raw[pos + 8:pos + 8 + rlen]
            if rtype == 0x01 and len(data) >= 4:
                value = struct.unpack('>I', data[:4])[0]
                return value >= 2
            pos += 8 + rlen
    except Exception:
        return False
    return False


def _drm_message(kind: str) -> str:
    return ('这本书带加密保护(DRM) —— 从图书馆借的书、Kindle 买的多半是这种。'
            '它们只能在原来的 app 里读,导不进这里。\n'
            '想放进来,得先拿到一份没加密的:'
            'Standard Ebooks / Project Gutenberg / Internet Archive 上有免费的,'
            '亚马逊 2026 年起也支持下载部分 Kindle 书的「无 DRM EPUB」。')


# === 各格式 → 纯文本 ===

def pdf_to_text(raw: bytes, progress=None) -> str:
    """PDF → 纯文本(逐页提取)。

    扫描版 PDF(整本书是图片)提不出字,这里明确报错而不是让家长拿到
    一本空书还以为是程序坏了。
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise ConversionError('服务器缺少 PDF 解析组件,无法导入 PDF') from e

    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as e:
        raise ConversionError('这个 PDF 打不开,可能已损坏或被加密') from e

    if getattr(reader, 'is_encrypted', False):
        # 有些 PDF 只是设了空口令,pypdf 能解
        try:
            reader.decrypt('')
        except Exception:
            raise ConversionError('这个 PDF 有密码,需要先去掉密码再导入')

    total = len(reader.pages)
    if total == 0:
        raise ConversionError('这个 PDF 里没有页面')

    pages = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or '')
        except Exception as e:
            logger.warning('PDF 第 %d 页提取失败: %s', i + 1, e)
            pages.append('')
        if progress:
            progress(i + 1, total)

    text = '\n\n'.join(pages)
    stripped = ''.join(text.split())
    if len(stripped) < _MIN_CHARS_PER_PDF_PAGE * total * 0.5:
        raise ConversionError(
            '这个 PDF 里几乎提取不到文字,多半是扫描版(整页是图片)。'
            '需要先做 OCR 转成文字版,再导入')
    return text


def mobi_to_text(raw: bytes, progress=None) -> str:
    """MOBI / AZW3 → 纯文本。

    Kindle 生态的遗留格式。**只支持没加密的** —— 带 DRM 的 AZW3
    是亚马逊的加密体系,技术上解不开,也没有合法的绕法。

    依赖 `mobi` 包(自带 kindleunpack)。没装就明确报缺组件,
    不静默失败。
    """
    try:
        import mobi
    except ImportError as e:  # pragma: no cover
        raise ConversionError('服务器缺少 MOBI 解析组件,无法导入 MOBI/AZW3') from e

    if detect_mobi_drm(raw):
        raise DrmError(_drm_message('mobi'))

    tmp = None
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix='.mobi')
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
        tempdir, outfile = mobi.extract(tmp)
        try:
            with open(outfile, 'rb') as f:
                html = f.read()
        except OSError:
            # 新版 mobi 可能直接返回文本
            html = outfile if isinstance(outfile, bytes) else b''
    except DrmError:
        raise
    except Exception as e:
        raise ConversionError(f'这个 MOBI/AZW3 解不开: {type(e).__name__}') from e
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass

    if progress:
        progress(1, 1)
    text = html_to_text(html.decode('utf-8', errors='ignore'))
    if not text.strip():
        raise ConversionError('这个 MOBI/AZW3 里没读到文字')
    return text


def docx_to_text(raw: bytes, progress=None) -> str:
    """DOCX → 纯文本。段落保留换行。"""
    try:
        import docx  # python-docx
    except ImportError as e:  # pragma: no cover
        raise ConversionError('服务器缺少 DOCX 解析组件,无法导入 DOCX') from e
    try:
        document = docx.Document(io.BytesIO(raw))
    except Exception as e:
        raise ConversionError('这个 DOCX 打不开,可能不是真的 Word 文件') from e
    paras = [p.text for p in document.paragraphs]
    if progress:
        progress(len(paras), len(paras))
    return '\n\n'.join(paras)


# === 纯文本 → 章节 + 句子 ===

# 章节标题的两种写法:英文的 Chapter N / 中文��第 N 章
_CHAPTER_HEADING_RE = re.compile(
    r'^\s*(?:'
    r'(?:chapter|part|prologue|epilogue|book|act|scene)\s+([0-9]+|[ivxlcdm]+)\b'
    r'|第\s*([0-9一二三四五六七八九十百千零两]+)\s*[章回节篇部卷]'
    r')\s*[:：.、]?\s*(.*)$',
    re.I,
)

# 纯文本里常见的噪声:页码、页眉页脚、版权行
_PAGE_NOISE_RE = re.compile(r'^\s*(?:[-–—•·*]?\s*(?:\d{1,4}|[ivxlcdm]{1,6})\s*[-–—•·*]?)\s*$', re.I)
_COPYRIGHT_RE = re.compile(r'(?i)(copyright|all rights reserved|版权所有|未经许可|扫码|关注公众号|加入书架)')


def _is_heading_line(line: str) -> bool:
    """判断一行像不像章节标题。"""
    line = line.strip()
    if not line:
        return False
    if len(line) > 70:
        return False
    if _CHAPTER_HEADING_RE.match(line):
        return True
    # 短行 + 没有句末标点 + 标题化(首字母大写或中文)→ 可能是标题
    if len(line.split()) <= 12 and not re.search(r'[.!?。！？,，;；]$', line):
        # 至少有两个词,或中文
        if len(line) > 2 and (re.search(r'[一-鿿]', line) or len(line.split()) >= 2):
            return True
    return False


_EN_HEAD_PREFIX_RE = re.compile(
    r'^\s*((?:chapter|part|prologue|epilogue|book|act|scene)\s+[0-9ivxlcdm]+)', re.I)


def _clean_heading(line: str, fallback: str) -> str:
    """把标题行整理成干净的章节名。

    英文书保留英文写法("Chapter 3 - A Royal Invitation"),
    中文书写成"第三章 · 春天" —— 别把「第一章」改成「第 一 章」,
    中文书名里带空格的章节号看着像排版事故。
    """
    line = line.strip()
    m = _CHAPTER_HEADING_RE.match(line)
    if m:
        tail = (m.group(3) or '').strip(' -—:：.、')
        if m.group(1):                      # 英文 Chapter N
            em = _EN_HEAD_PREFIX_RE.match(line)
            base = em.group(1) if em else f'Chapter {m.group(1)}'
            if tail and tail.lower() not in base.lower():
                return f'{base} · {tail}'
            return base
        if m.group(2):                      # 中文 第 N 章
            return f'第{m.group(2)}章' + (f' · {tail}' if tail else '')
    return line or fallback


def text_to_chapters(text: str, book_title: str, from_books=None) -> list:
    """纯文本 → [{name, sentences}]。

    优先用「Chapter N / 第 N 章」这种明确的标题;找不到就退而求其次,
    把短行当标题;一个标题都找不到,按每 40 句切一块(Part 1/2/3),
    至少保证孩子有「一章一章往下读」的感觉。
    """
    from extensions.books import (  # 延迟 import 避免循环
        _split_sentences, _is_chapter_heading, _normalize_ligatures,
    )

    # 归一化:去掉页眉页脚噪声行
    lines = []
    for raw_line in text.splitlines():
        line = _normalize_ligatures(raw_line.strip())
        if not line:
            lines.append('')
            continue
        if _PAGE_NOISE_RE.match(line):
            continue
        if _COPYRIGHT_RE.search(line) and len(line) < 60:
            continue
        lines.append(line)

    # 按空行分段(段落)
    blocks = []
    cur = []
    for line in lines:
        if line:
            cur.append(line)
        elif cur:
            blocks.append(' '.join(cur))
            cur = []
    if cur:
        blocks.append(' '.join(cur))

    chapters = []
    current_name = book_title
    current_sents = []
    para_buf = []

    def flush_para():
        """把攒下来的行变成一个段落,切句后并入当前章。"""
        nonlocal para_buf
        if not para_buf:
            return
        block = ' '.join(para_buf)
        para_buf = []
        sents = _split_sentences(block)
        if sents:
            current_sents.extend(sents)

    def close_chapter():
        """结束当前章(有句子才收)。"""
        nonlocal current_name, current_sents
        if current_sents:
            chapters.append({'name': current_name, 'sentences': current_sents})
        current_sents = []

    # 逐行走,而不是先合并成段 —— 「Chapter 1」这种标题行和它下面的正文
    # 之间通常没有空行,先合并就分不开了。
    for line in lines:
        if not line:
            flush_para()
            continue
        if _is_heading_line(line):
            flush_para()
            close_chapter()
            current_name = _clean_heading(line, f'第 {len(chapters) + 1} 章')
            continue
        para_buf.append(line)
    flush_para()
    close_chapter()

    # 一个标题都没找到 → 按固定句数切块
    if len(chapters) <= 1 and len(chapters[0]['sentences'] if chapters else []) > 60:
        flat = chapters[0]['sentences'] if chapters else []
        chapters = []
        chunk = 40
        for i in range(0, len(flat), chunk):
            chapters.append({
                'name': f'第 {i // chunk + 1} 部分',
                'sentences': flat[i:i + chunk],
            })

    # 过滤太碎的章(少于 3 句的合并进上一章)
    merged = []
    for ch in chapters:
        sents = [s for s in ch.get('sentences', []) if s and len(s.strip()) > 3]
        if not sents:
            continue
        if merged and len(sents) < 3:
            merged[-1]['sentences'].extend(sents)
        else:
            merged.append({'name': ch['name'], 'sentences': sents})
    return merged


# === 占位封面 ===
# TXT / PDF / DOCX 没有封面图。书架上如果一排都是空白方块,很难看。
# 用 PIL 造一张:一个按书名哈希出来的低饱和底色 + 标题文字 + 一道书脊。

_PALETTE = [
    ((184, 106, 78), (206, 142, 112)),
    ((107, 138, 82), (138, 165, 116)),
    ((122, 139, 159), (156, 170, 186)),
    ((154, 120, 96), (183, 152, 130)),
    ((140, 116, 148), (168, 147, 174)),
    ((176, 138, 84), (204, 172, 126)),
]

_CJK_FONT_CANDIDATES = (
    '/System/Library/Fonts/Supplemental/Songti.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/usr/share/fonts/truetype/arphic/uming.ttc',
    'C:/Windows/Fonts/simsun.ttc',
)


def make_cover(book_title: str, author: str = '', out_dir: Path = None,
               book_id: str = '') -> str:
    """生成一张占位封面,返回 web 路径(失败返回 '')。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.info('没有 PIL,跳过占位封面')
        return ''

    if out_dir is None:
        from extensions.books import COVERS_DIR
        out_dir = COVERS_DIR
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    W, H = 600, 900
    seed = sum(ord(c) for c in (book_id or book_title))
    base, light = _PALETTE[seed % len(_PALETTE)]

    img = Image.new('RGB', (W, H), base)
    draw = ImageDraw.Draw(img)
    # 竖向渐变:从浅到深,做出「布面」的感觉
    for y in range(H):
        t = y / H
        c = tuple(int(light[i] + (base[i] - light[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=c)
    # 左侧书脊
    draw.rectangle([0, 0, 26, H], fill=tuple(int(c * 0.72) for c in base))
    draw.line([(26, 0), (26, H)], fill=tuple(min(255, int(c * 1.25)) for c in base))

    def load(size):
        for path in _CJK_FONT_CANDIDATES:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        try:
            return ImageFont.load_default(size)
        except TypeError:      # 老版本 Pillow 不支持 size 参数
            return ImageFont.load_default()

    title = (book_title or '').strip()
    if len(title) > 26:
        title = title[:24] + '…'
    font = load(46)
    small = load(26)

    # 标题竖排或横排?横排两行更稳
    words = title.split()
    lines = []
    if len(words) <= 12:
        lines = [title]
    else:
        # 中文按字断,英文按词断
        if re.search(r'[一-鿿]', title):
            mid = (len(title) + 1) // 2
            lines = [title[:mid], title[mid:]]
        else:
            lines = [' '.join(words[:len(words) // 2]), ' '.join(words[len(words) // 2:])]

    y = H // 2 - len(lines) * 32
    for ln in lines:
        try:
            bbox = draw.textbbox((0, 0), ln, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(ln) * 40
        draw.text(((W - w) / 2, y), ln, font=font, fill=(250, 246, 238))
        y += 58

    if author:
        draw.text((54, H - 120), author[:30], font=small, fill=(245, 238, 228))

    name = f'{book_id or "cover"}.png'
    path = out_dir / name
    try:
        img.save(path, 'PNG')
    except Exception as e:
        logger.warning('占位封面写盘失败: %s', e)
        return ''
    return f'/data/covers/{name}'


# === 总入口 ===

def convert(raw: bytes, filename: str, progress=None) -> dict:
    """把任意支持格式的字节流转成 book_data。

    progress(done, total) 用来给前端报「正在转换第 3/12 页」。
    """
    from extensions.books import _sanitize_book_id

    ext = Path(filename or '').suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ConversionError(
            f'不支持的格式 {ext or "(无后缀)"}。'
            f'目前支持:{"、".join(SUPPORTED_EXTENSIONS)}')

    if len(raw) > MAX_UPLOAD_BYTES:
        raise ConversionError(
            f'文件太大({len(raw) / 1048576:.0f}MB),上限 {MAX_UPLOAD_BYTES // 1048576}MB')

    title = Path(filename or '').stem.replace('_', ' ').strip() or '未命名'

    if ext == '.pdf':
        text = pdf_to_text(raw, progress)
    elif ext in ('.mobi', '.azw', '.azw3', '.prc'):
        text = mobi_to_text(raw, progress)
    elif ext == '.docx':
        text = docx_to_text(raw, progress)
    elif ext in ('.html', '.htm'):
        text = html_to_text(decode_text(raw))
        if progress:
            progress(1, 1)
    else:   # .txt / .text / .md / .markdown
        text = decode_text(raw)
        if progress:
            progress(1, 1)

    if not text.strip():
        raise ConversionError('这个文件里没读到任何文字')

    chapters = text_to_chapters(text, title)
    if not chapters:
        raise ConversionError('没能从文件里切出任何句子 —— 可能不是文本内容')

    book_id = _sanitize_book_id(title)
    cover = make_cover(title, '', book_id=book_id)

    total_sentences = sum(len(c['sentences']) for c in chapters)
    logger.info('转换 %s → %d 章 / %d 句', filename, len(chapters), total_sentences)

    return {
        'book': title,
        'id': book_id,
        'chapters': chapters,
        'cover': cover,
        'creator': None,
        'publisher': None,
        'date': None,
        'year': None,
        'language': None,
        'description': f'由 {ext} 文件自动转换',
        'identifier': None,
        'subjects': [],
        'rights': None,
        'toc': [],
        'source_format': ext,
        'total_sentences': total_sentences,
    }
