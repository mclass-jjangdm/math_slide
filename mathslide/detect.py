"""PDF 페이지에서 '문제 번호'를 찾아 문제 영역(사각형)으로 나눈다.

원리
  1) 글자 하나짜리 숫자 줄(예: 658)을 모두 모은다.
  2) (글자크기, 글꼴)이 같은 숫자들을 한 묶음으로 보고, 본문보다 크고 개수가 가장 많은 묶음을
     '문제 번호 스타일'로 판단한다.  (페이지 번호·머리말은 제외)
  3) 페이지마다 번호의 x좌표로 단(column)을 나누고, 번호 위치부터 같은 단의 다음 번호 직전까지를
     한 문제로 본다.
  4) 영역 안의 실제 내용물만 남기도록 여백을 잘라 낸다.
스캔본(텍스트 없음)이면 빈 목록을 돌려주므로, 화면에서 직접 상자를 그리면 된다.
"""
import re
import statistics
from collections import defaultdict

import pymupdf

NUM_RE = re.compile(r"\d{1,4}")
FOOTER_Y = 0.94   # 이 아래는 쪽번호 영역
HEADER_Y = 0.02


def _all_spans(page):
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                yield ln, sp


def find_number_style(doc):
    sizes, cands = [], []
    for pn, page in enumerate(doc):
        H = page.rect.height
        for ln, sp in _all_spans(page):
            t = sp["text"].strip()
            if not t:
                continue
            sizes.extend([sp["size"]] * len(t))
            line_text = "".join(s["text"] for s in ln["spans"]).strip()
            if NUM_RE.fullmatch(t) and line_text == t:
                y0 = sp["bbox"][1]
                if HEADER_Y * H < y0 < FOOTER_Y * H:
                    cands.append((pn, t, sp))
    if not sizes or not cands:
        return None
    body = statistics.median(sizes)
    groups = defaultdict(list)
    for c in cands:
        groups[(round(c[2]["size"]), c[2]["font"])].append(c)
    best, best_score = None, 0
    for key, items in groups.items():
        if key[0] < body * 1.25 or len(items) < 2:
            continue
        # 페이지당 평균 개수가 적당하고 개수가 많은 묶음 우선
        if len(items) > best_score:
            best, best_score = key, len(items)
    return best


def _trim(page, rect, pad=5.0, dpi=60):
    """rect 안의 실제 내용(글줄·그림·작은 도형)만 감싸는 사각형.
    영역 밖으로 삐져나가는 큰 배경 상자·테두리는 내용으로 치지 않는다."""
    boxes = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 1:
            boxes.append(pymupdf.Rect(b["bbox"]))
            continue
        for ln in b.get("lines", []):
            if "".join(s["text"] for s in ln["spans"]).strip():
                boxes.append(pymupdf.Rect(ln["bbox"]))
    for d in page.get_drawings():
        r = pymupdf.Rect(d["rect"])
        if r.is_empty and r.width < 0.01 and r.height < 0.01:
            continue
        if (r.x0 < rect.x0 - 3 or r.y0 < rect.y0 - 3 or r.x1 > rect.x1 + 3 or r.y1 > rect.y1 + 3):
            continue
        fill = d.get("fill")
        if fill and min(fill) > 0.97 and not d.get("color"):
            continue  # 흰색 채우기
        boxes.append(r)
    u = None
    for r in boxes:
        c = pymupdf.Rect(r)
        if c.x0 > page.rect.width - 40 or c.x1 < 40:
            continue  # 가장자리 인덱스 탭 등
        if not c.intersects(rect) or (c.y0 + c.y1) / 2 < rect.y0 or (c.y0 + c.y1) / 2 > rect.y1:
            continue
        c.intersect(rect)
        u = c if u is None else (u | c)
    if u is not None:
        out = pymupdf.Rect(u.x0 - pad, u.y0 - pad, u.x1 + pad, u.y1 + pad)
        out.intersect(rect)
        return out
    return _trim_pixels(page, rect, pad, dpi)


def _trim_pixels(page, rect, pad=5.0, dpi=60):
    pix = page.get_pixmap(dpi=dpi, clip=rect, colorspace=pymupdf.csGRAY, alpha=False)
    w, h, buf = pix.width, pix.height, pix.samples
    if w == 0 or h == 0:
        return rect
    xs0, ys0, xs1, ys1 = w, h, -1, -1
    for y in range(h):
        row = buf[y * w:(y + 1) * w]
        if min(row) < 235:
            xs = [i for i, v in enumerate(row) if v < 235]
            ys0 = min(ys0, y)
            ys1 = max(ys1, y)
            xs0 = min(xs0, xs[0])
            xs1 = max(xs1, xs[-1])
    if ys1 < 0:
        return rect
    k = 72.0 / dpi
    r = pymupdf.Rect(rect.x0 + xs0 * k - pad, rect.y0 + ys0 * k - pad,
                     rect.x0 + (xs1 + 1) * k + pad, rect.y0 + (ys1 + 1) * k + pad)
    r.intersect(rect)
    return r


MARK_RE = re.compile(r"^\s*(?:추가|문제|예제|유제|연습|실전|Q)\s*\.?\s*(\d{1,4})\s*[.)]")


def find_markers(doc):
    """'추가 1.' '문제 3)' 처럼 글머리 낱말이 붙은 문제 표지를 찾는다. {쪽: [(번호, 줄bbox)]}"""
    out = {}
    for pn, page in enumerate(doc):
        H = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                t = "".join(s["text"] for s in ln["spans"])
                m = MARK_RE.match(t)
                if m and HEADER_Y * H < ln["bbox"][1] < FOOTER_Y * H:
                    out.setdefault(pn, []).append((m.group(1), ln["bbox"]))
    return out


def find_big_numbers(doc, style):
    out = {}
    for pn, page in enumerate(doc):
        H = page.rect.height
        for ln, sp in _all_spans(page):
            t = sp["text"].strip()
            line_text = "".join(s["text"] for s in ln["spans"]).strip()
            if (NUM_RE.fullmatch(t) and line_text == t
                    and (round(sp["size"]), sp["font"]) == style
                    and HEADER_Y * H < sp["bbox"][1] < FOOTER_Y * H):
                out.setdefault(pn, []).append((t, sp["bbox"]))
    return out


def detect(doc):
    """문제 표지를 찾는 방법을 차례로 시도한다: 큰 번호 글자 / '추가 1.' 같은 글머리 / (스캔본) 이미지 분석."""
    style = find_number_style(doc)
    big = find_big_numbers(doc, style) if style else {}
    marks = find_markers(doc)
    n_big, n_mark = sum(map(len, big.values())), sum(map(len, marks.values()))
    if n_mark >= 2 and n_mark > n_big:
        per_page = marks
    elif n_big >= 1:
        per_page = big
    else:
        import detect_scan  # 글자 정보가 없으면 이미지 분석(스캔본)으로 넘어간다
        return detect_scan.detect_scanned(doc)
    problems = []
    for pn, page in enumerate(doc):
        W, H = page.rect.width, page.rect.height
        nums = per_page.get(pn, [])
        if not nums:
            continue
        # 단 나누기: x0가 비슷한 번호끼리 묶는다
        nums.sort(key=lambda n: n[1][0])
        cols = []
        for n in nums:
            if cols and abs(n[1][0] - cols[-1][0][1][0]) < 60:
                cols[-1].append(n)
            else:
                cols.append([n])
        for ci, col in enumerate(cols):
            xl = min(n[1][0] for n in col)
            left = max(0, xl - 22) if ci == 0 else xl - 12
            if ci + 1 < len(cols):
                right = min(n[1][0] for n in cols[ci + 1]) - 12
            else:
                right = W - 18
            col.sort(key=lambda n: n[1][1])
            for i, (t, bb) in enumerate(col):
                top = bb[1] - 8
                bottom = (col[i + 1][1][1] - 8) if i + 1 < len(col) else FOOTER_Y * H
                region = pymupdf.Rect(left, max(0, top), right, bottom)
                rect = _trim(page, region)
                problems.append({
                    "page": pn, "label": t, "col": ci,
                    "rect": [round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1)],
                    "on": True, "answer": None,
                    "mask": bool(answer_rects(page, rect)),   # 문제 안에 '(정답 : …)'이 인쇄돼 있으면 수업 화면에서 가린다
                })
    return problems


SUB_RE = re.compile(r"^\s*[\(（](\d{1,2})[\)）]")


def _sub_num(text):
    """줄 맨 앞의 소문항 번호: ⑴⑵…⒇ 또는 (1) (2) …  없으면 None."""
    t = text.lstrip()
    if not t:
        return None
    if 0x2474 <= ord(t[0]) <= 0x2487:
        return ord(t[0]) - 0x2473
    m = SUB_RE.match(t)
    return int(m.group(1)) if m else None


def split_subitems(page, rect, parent_label=""):
    """한 문제 영역 안의 소문항 (1)(2)…(n)을 각각 별도 문제로 나눈다. 두 단에 걸쳐 있어도 된다."""
    rect = pymupdf.Rect(rect)
    area = pymupdf.Rect(rect.x0 - 3, rect.y0 - 12, rect.x1 + 3, rect.y1 + 3)
    marks = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            bb = pymupdf.Rect(ln["bbox"])
            if not area.contains(pymupdf.Point(bb.x0 + 1, (bb.y0 + bb.y1) / 2)):
                continue
            n = _sub_num("".join(s["text"] for s in ln["spans"]))
            if n is not None:
                marks.append((n, bb))
    if len(marks) < 2:
        return []
    # 단 나누기
    marks.sort(key=lambda m: m[1].x0)
    cols = []
    for m in marks:
        if cols and abs(m[1].x0 - cols[-1][0][1].x0) < 30:
            cols[-1].append(m)
        else:
            cols.append([m])
    for c in cols:
        c.sort(key=lambda m: m[1].y0)
    ordered = [m for c in cols for m in c]
    # 1부터 (또는 처음 번호부터) 1씩 늘어나는 열만 인정한다
    seq = [ordered[0]]
    for m in ordered[1:]:
        if m[0] == seq[-1][0] + 1:
            seq.append(m)
    if len(seq) < 2:
        return []
    out = []
    for ci, col in enumerate(cols):
        col = [m for m in col if any(m is s for s in seq)]
        if not col:
            continue
        left = min(m[1].x0 for m in col) - 4
        nxt = [min(m[1].x0 for m in c2) for c2 in cols[ci + 1:] if c2]
        right = (nxt[0] - 8) if nxt else rect.x1 + 3
        for i, (n, bb) in enumerate(col):
            top = bb.y0 - 3
            bottom = (col[i + 1][1].y0 - 3) if i + 1 < len(col) else rect.y1
            region = pymupdf.Rect(max(0, left), max(0, top), right, bottom)
            r = _trim(page, region)
            out.append((n, r))
    out.sort(key=lambda t: t[0])
    return [{
        "page": page.number, "label": f"{parent_label}-({n})" if parent_label else f"({n})", "col": 0,
        "rect": [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)],
        "on": True, "answer": None, "mask": bool(answer_rects(page, r)), "sub": n,
    } for n, r in out]


ANS_START = re.compile(r"^[\(\[（]?\s*정답")


def answer_rects(page, clip):
    """clip 안에서 '(정답 : …)' 로 인쇄된 글자들의 사각형 목록(쪽 좌표)."""
    clip = pymupdf.Rect(clip)
    words = [w for w in page.get_text("words", clip=clip)]
    words.sort(key=lambda w: (w[5], w[6], w[7]))   # block, line, word
    rects, i = [], 0
    while i < len(words):
        w = words[i]
        if ANS_START.match(w[4]):
            j = i
            r = pymupdf.Rect(w[:4])
            while j + 1 < len(words) and not words[j][4].rstrip().endswith((")", "）", "]")) \
                    and words[j + 1][5:7] == w[5:7] and j - i < 12:
                j += 1
                r |= pymupdf.Rect(words[j][:4])
            r = pymupdf.Rect(r.x0 - 1.5, r.y0 - 1.5, r.x1 + 1.5, r.y1 + 1.5)
            rects.append(r)
            i = j + 1
        else:
            i += 1
    return rects


if __name__ == "__main__":
    import sys
    d = pymupdf.open(sys.argv[1])
    ps = detect(d)
    for p in ps:
        print(p["page"] + 1, p["label"], p["rect"])
    print(len(ps), "problems")
