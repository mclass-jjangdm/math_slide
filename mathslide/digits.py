"""아주 작은 숫자 인식기(템플릿 매칭). 스캔본에서 '문제 번호'인지 확인하고 번호 값을 읽는 데 쓴다.
PyMuPDF에 내장된 글꼴(Helvetica·Times)로 0~9를 그려 견본을 만든다 → 외부 파일/OCR 불필요.
"""
import numpy as np
import pymupdf
from PIL import Image

GW, GH = 14, 20
_TEMPL = None


def _vec(img_bool):
    """불리언 이미지(잉크=True) → 잉크 외곽 상자로 잘라 GWxGH로 줄인 뒤 정규화한 벡터. 실패 시 None."""
    ys, xs = np.where(img_bool)
    if len(ys) < 6:
        return None
    crop = img_bool[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
    im = Image.fromarray(crop).resize((GW, GH), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = a - a.mean()
    n = np.linalg.norm(a)
    return None if n < 1e-6 else (a / n).ravel()


def _templates():
    global _TEMPL
    if _TEMPL is not None:
        return _TEMPL
    T = {str(d): [] for d in range(10)}
    for font in ("helv", "hebo", "tiro", "tibo"):
        doc = pymupdf.open()
        page = doc.new_page(width=800, height=200)
        for d in range(10):
            page.insert_text((20 + d * 75, 150), str(d), fontname=font, fontsize=110)
        pix = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY, alpha=False)
        g = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width) < 128
        for d in range(10):
            cell = g[:, 10 + d * 75: 10 + (d + 1) * 75]
            v = _vec(cell)
            if v is not None:
                T[str(d)].append(v)
    _TEMPL = T
    return T


def _classify(glyph):
    v = _vec(glyph)
    if v is None:
        return None, 0.0
    best, bs = None, -1.0
    for d, vs in _templates().items():
        for t in vs:
            s = float(v @ t)
            if s > bs:
                best, bs = d, s
    return best, bs


def read_number(ink, xs, ys, xe, ye):
    """ink[ys:ye, xs:xe] 영역을 1~4자리 숫자로 읽어 (문자열, 점수)를 돌려준다. 못 읽으면 ('', 0)."""
    reg = ink[ys:ye, xs:xe]
    h, w = reg.shape
    if h < 8 or w < 4:
        return "", 0.0
    best = ("", 0.0)
    for n in range(1, 5):
        if w > 1.1 * h * n or w < 0.28 * h * n:
            continue
        # 같은 폭으로 n등분 (숫자는 자릿폭이 거의 같다)
        edges = np.linspace(0, w, n + 1).astype(int)
        digs, scores = "", []
        for i in range(n):
            d, s = _classify(reg[:, edges[i]:edges[i + 1]])
            if d is None:
                digs = ""
                break
            digs += d
            scores.append(s)
        if not digs:
            continue
        sc = float(np.mean(scores)) * (0.85 + 0.15 * min(scores) / max(np.mean(scores), 1e-6))
        if sc > best[1]:
            best = (digs, sc)
    return best
