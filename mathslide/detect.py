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
from collections import Counter, defaultdict

import pymupdf

DETECT_VERSION = 12  # 검출 규칙을 고칠 때마다 올린다 (수정 안 한 작업은 열 때 자동으로 다시 검출됨)
NUM_RE = re.compile(r"\d{1,4}")
FOOTER_Y = 0.94   # 이 아래는 쪽번호 영역
HEADER_Y = 0.02


def _all_spans(page):
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                yield ln, sp


_OLIKE = str.maketrans({"O": "0", "o": "0"})


def _as_number(text):
    """숫자로 읽히면 숫자 문자열. 글꼴 때문에 0이 알파벳 O로 들어 있는 경우('1O' = 10)도 숫자로 본다."""
    t = text.strip()
    if NUM_RE.fullmatch(t):
        return t
    if re.fullmatch(r"[0-9Oo]{1,4}", t) and any(c.isdigit() for c in t):
        u = t.translate(_OLIKE)
        return u if NUM_RE.fullmatch(u) else None
    return None


def _num_lines(page):
    """숫자만으로 된 줄(예: 658, 0884)과 그 글자 모양(크기, 글꼴), 줄 상자.
    '0884'처럼 앞의 0과 나머지가 색·조각이 달라 글자 조각이 여러 개여도 한 줄 전체로 본다.
    '문제 3'처럼 작은 글자 머리말 뒤에 큰 숫자가 붙은 줄은 큰 숫자만 번호로 본다."""
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            t = _as_number("".join(s["text"] for s in spans))
            if t is not None:
                sp = max(spans, key=lambda s: (s["size"], len(s["text"])))
                yield t, (round(sp["size"]), sp["font"]), ln["bbox"], False
                continue
            if len(spans) >= 2:
                big = max(spans, key=lambda s: s["size"])
                bt = _as_number(big["text"])
                rest = [s for s in spans if s is not big]
                if bt is not None and all(s["size"] <= big["size"] * 0.6 for s in rest) and sum(len(s["text"].strip()) for s in rest) <= 6:
                    yield bt, (round(big["size"]), big["font"]), ln["bbox"], True   # 본문 속 '문제 3' 같은 작은 문제


def _style_match(key, styles, tol=2.5):
    """글꼴이 같고 크기가 비슷하면(34.5pt와 36pt처럼) 같은 번호 글꼴로 본다."""
    return any(key[1] == st[1] and abs(key[0] - st[0]) <= tol for st in styles)


def _looks_like_page_numbers(items):
    """쪽 번호인가? 모든 쪽에서 같은 높이(위·아래 가장자리)에 있고, 번호가 쪽 순서대로 늘어나면 쪽 번호로 본다.
    (홀수쪽은 오른쪽, 짝수쪽은 왼쪽에 찍히는 경우가 많아 가로 위치는 따지지 않는다)"""
    if len(items) < 3:
        return False
    cells = Counter(round(it[3][1] / 12) for it in items)
    if cells.most_common(1)[0][1] / len(items) < 0.6:
        return False
    if not all(it[3][1] < 0.14 * it[4] or it[3][1] > 0.88 * it[4] for it in items):
        return False   # 위·아래 가장자리가 아니면 쪽 번호가 아니다
    return len({it[0] for it in items}) >= 3   # 서로 다른 세 쪽 이상에 반복


def _consecutive_ratio(items):
    """읽는 순서(쪽 → 단 → 위에서 아래)로 늘어놓았을 때 번호가 1씩 이어지는 비율."""
    seq = sorted(items, key=lambda c: (c[0], round(c[3][0] / 60), c[3][1]))
    vals = [int(c[1]) for c in seq]
    if len(vals) < 2:
        return 0.0
    return sum(1 for a, b in zip(vals, vals[1:]) if b == a + 1) / (len(vals) - 1)


def find_number_styles(doc, allow_page_like=False):
    """문제 번호 글꼴(크기, 글꼴) 목록. 가장 많이 나온 글꼴이 첫째.
    교재는 단원 구간마다 번호 글꼴이 다르므로(예: 표준·발전 / 대단원 평가), 번호가 1씩 이어지는 다른 글꼴도 함께 쓴다."""
    sizes, cands = [], []
    for pn, page in enumerate(doc):
        H = page.rect.height
        for ln, sp in _all_spans(page):
            t = sp["text"].strip()
            if t:
                sizes.extend([sp["size"]] * len(t))
        for t, key, bb, inl in _num_lines(page):
            if HEADER_Y * H < bb[1] < FOOTER_Y * H:
                cands.append((pn, t, key, bb, H))
    if not sizes or not cands:
        return None
    body = statistics.median(sizes)
    groups = defaultdict(list)
    reps = []   # 글꼴이 같고 크기가 비슷한 묶음은 하나로 합친다
    for c in sorted(cands, key=lambda c: c[2][0]):
        rep = next((r for r in reps if r[1] == c[2][1] and abs(r[0] - c[2][0]) <= 2.5), None)
        if rep is None:
            rep = c[2]
            reps.append(rep)
        groups[rep].append(c)
    ok = []
    for key, items in groups.items():
        if key[0] < body * 1.25 or len(items) < 2:
            continue
        if not allow_page_like and _looks_like_page_numbers(items):
            continue   # 문제 번호가 아니라 쪽 번호(머리말·꼬리말)
        ok.append((len(items), key, items))   # 개수가 많은 묶음 우선
    if not ok:
        return []
    ok.sort(key=lambda t: -t[0])
    styles = [ok[0][1]]
    for n, key, items in ok[1:]:
        # 첫째 글꼴과 크기가 비슷하고 번호가 차례로 이어지면 같은 교재의 다른 구간 번호로 본다
        if n >= 3 and key[0] >= styles[0][0] * 0.8 and _consecutive_ratio(items) >= 0.7:
            styles.append(key)
    return styles


def find_number_style(doc, allow_page_like=False):
    st = find_number_styles(doc, allow_page_like)
    return st[0] if st else None


def _trim(page, rect, pad=5.0, dpi=60, xmin=None):
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
        if xmin is not None and c.x1 < xmin:
            continue  # 번호보다 완전히 왼쪽에 있는 것은 옆 단·옆 쪽의 내용
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


REF_RE = re.compile(r"^\s*[\(（\[]?\s*교과서\s*\d+\s*쪽")
LEADNUM_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]")


def find_textbook_refs(doc):
    """'(교과서 27쪽) 중단원 마무리 문제' 같은 출처 꼬리표 바로 아래 줄이 '19. …'로 시작하면 그것을 문제 표지로 본다.
    (추가문제 모음처럼 '추가 1.'과 교과서 문제 번호가 섞인 자료용.) 영역 맨 위는 꼬리표 줄부터. {쪽: [(번호, 꼬리표+번호 줄 bbox)]}"""
    out = {}
    for pn, page in enumerate(doc):
        H = page.rect.height
        lines = []
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                t = "".join(s["text"] for s in ln["spans"]).strip()
                if t:
                    lines.append((t, ln["bbox"]))
        for t, bb in lines:
            if not REF_RE.match(t) or not (HEADER_Y * H < bb[1] < FOOTER_Y * H):
                continue
            below = [(t2, b2) for t2, b2 in lines if abs(b2[0] - bb[0]) < 25 and 0 <= b2[1] - bb[3] < 14]
            below.sort(key=lambda x: x[1][1])
            for t2, b2 in below[:1]:
                m = LEADNUM_RE.match(t2)
                if m:
                    out.setdefault(pn, []).append((m.group(1), (min(bb[0], b2[0]), bb[1], max(bb[2], b2[2]), b2[3]), False, True))   # 마지막 True: 꼬리표 줄부터 딱 맞게
    return out


PLAIN_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*$")


def find_plain_markers(doc):
    """모의고사처럼 문제 글 바로 앞에 '5.' '18.' 같은 번호가 따로 인쇄된 경우.
    첫 글자 조각이 '숫자.' 뿐인 줄을 모아, (글꼴·크기)가 같은 묶음 중 가장 많고 순서대로 늘어나는 것을 문제 번호로 본다."""
    groups = defaultdict(list)
    for pn, page in enumerate(doc):
        H, W = page.rect.height, page.rect.width
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                spans = [sp for sp in ln["spans"] if sp["text"].strip()]
                if not spans:
                    continue
                m = PLAIN_RE.match(spans[0]["text"])
                if m and HEADER_Y * H < ln["bbox"][1] < FOOTER_Y * H:
                    groups[(round(spans[0]["size"], 1), spans[0]["font"])].append((pn, m.group(1), ln["bbox"], W))
    # 쪽마다 글자 크기가 0.1pt쯤 다르게 찍힌 같은 번호 글꼴(9.4 / 9.5)은 한 묶음으로 합친다
    merged = {}
    for key in sorted(groups, key=lambda k: -len(groups[k])):
        tgt = next((k for k in merged if k[1] == key[1] and abs(k[0] - key[0]) <= 0.3), None)
        merged.setdefault(tgt or key, []).extend(groups[key])
    groups = merged
    best, best_n = {}, 0
    for key, items in groups.items():
        if len(items) < 4 or len(items) <= best_n:
            continue
        order = sorted(items, key=lambda it: (it[0], 0 if it[2][0] < it[3] / 2 else 1, it[2][1]))
        seq = [int(it[1]) for it in order]
        steps = sum(1 for a, b in zip(seq, seq[1:]) if b == a + 1)
        if steps < 0.5 * (len(seq) - 1):
            continue   # 번호가 순서대로 늘어나지 않으면 문제 번호가 아니다 (목록 등)
        best, best_n = {}, len(items)
        for pn, label, bb, _w in items:
            best.setdefault(pn, []).append((label, bb))
    return best


def find_lead_markers(doc):
    """교재처럼 문제 번호가 본문 첫 줄의 맨 앞 글자(본문보다 큰 숫자 한 조각)로 붙어 있는 경우.
    예: '1 두 점 A(a,4), B(-1,-2) 사이의 거리가…'  첫 조각이 숫자뿐이고 뒤에 본문 글이 이어지는 줄을 모은다.
    (글꼴·크기)가 같은 묶음 중 가장 많고, 한 쪽 안에서 번호가 순서대로 늘어나는 것을 문제 번호로 본다.
    반환 {쪽: [(번호, 번호 조각 bbox)]}"""
    sizes = []
    for pg in doc:
        for _ln, sp in _all_spans(pg):
            t = sp["text"].strip()
            if t:
                sizes.extend([sp["size"]] * len(t))
    if not sizes:
        return {}
    body = statistics.median(sizes)
    groups = defaultdict(list)
    for pn, page in enumerate(doc):
        H = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                spans = [sp for sp in ln["spans"] if sp["text"].strip()]
                if len(spans) < 2 or not NUM_RE.fullmatch(spans[0]["text"].strip()):
                    continue   # 번호 뒤에 본문이 이어져야 한다
                sp = spans[0]
                if sp["size"] < body * 1.25 or not (HEADER_Y * H < sp["bbox"][1] < FOOTER_Y * H):
                    continue
                groups[(round(sp["size"], 1), sp["font"])].append((pn, sp["text"].strip(), sp["bbox"]))
    best, best_n = {}, 0
    for items in groups.values():
        if len(items) < 4 or len(items) <= best_n:
            continue
        by_page = defaultdict(list)
        for it in items:
            by_page[it[0]].append(it)
        steps = total = 0
        for its in by_page.values():
            its = sorted(its, key=lambda it: (round(it[2][0] / 60), it[2][1]))   # 단(왼→오) → 위→아래
            seq = [int(it[1]) for it in its]
            steps += sum(1 for a, b in zip(seq, seq[1:]) if b == a + 1)
            total += len(seq) - 1
        if total and steps < 0.6 * total:
            continue   # 번호가 순서대로 늘어나지 않으면 문제 번호가 아니다
        best, best_n = {}, len(items)
        for pn, label, bb in items:
            best.setdefault(pn, []).append((label, bb))
    return best


def find_footer_y(doc):
    """모든 쪽에서 같은 자리에 반복되는 숫자 줄(쪽 번호 상자 등)이 있으면 그 위쪽 y를, 없으면 None."""
    spots = []
    for pn, page in enumerate(doc):
        H = page.rect.height
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                t = "".join(sp["text"] for sp in ln["spans"]).strip()
                if t.isdigit() and len(t) <= 3 and ln["bbox"][1] > 0.85 * H:
                    spots.append((round(ln["bbox"][0] / 12), round(ln["bbox"][1] / 12), ln["bbox"][1]))
    if not spots:
        return None
    cells = Counter((a, b) for a, b, _ in spots)
    need = max(3, int(0.4 * len(doc)))
    ys = [y for a, b, y in spots if cells[(a, b)] >= need]
    return (min(ys) - 6) if ys else None


SUBJECT_SHORT = {"확률과 통계": "확통", "확률과통계": "확통"}


def label_sections(doc, problems):
    """번호가 겹치면(예: 확통·미적분·기하가 모두 23~30번) 쪽 머리말의 선택과목 이름을 번호 앞에 붙인다."""
    labels = [q["label"] for q in problems]
    if len(labels) - len(set(labels)) < 3:
        return
    subject = {}
    for pn, page in enumerate(doc):
        H = page.rect.height
        tops = []
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                if ln["bbox"][1] < 0.2 * H:
                    sps = [sp for sp in ln["spans"] if sp["text"].strip()]
                    if sps:
                        tops.append(("".join(sp["text"] for sp in ln["spans"]).strip(), max(sp["size"] for sp in sps)))
        for t, size in tops:
            m = re.search(r"영역\s*[\(（]([^()（）]{1,14})[\)）]", t) or (re.fullmatch(r"[\(（]([^()（）]{1,14})[\)）]", t) if size >= 18 else None)
            if m:
                name = m.group(1).strip()
                subject[pn] = SUBJECT_SHORT.get(name, name)
                break
    if not subject:
        return
    for q in problems:
        q["label"] = f"{subject.get(q['page'], '공통')} {q['label']}"


NOTICE_RE = re.compile(r"^[\s\*\u203b\u25e6\u2022\u25cb\u25cf\u25aa\u25a0\u25a1·]*확인\s*사항")


def find_notices(page):
    """'* 확인 사항' 같은 안내 상자(문제가 아님)의 위치를 찾는다. [(x0, x1, top)] — 상자 테두리가 있으면 테두리 위쪽까지."""
    out = []
    W = page.rect.width
    lines = [ln for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])]
    for ln in lines:
        t = "".join(sp["text"] for sp in ln["spans"]).strip()
        if not NOTICE_RE.match(t):
            continue
        x0, y0 = ln["bbox"][0], ln["bbox"][1]
        top, bx0, bx1 = y0 - 10, x0 - 12, W
        best = None
        for d in page.get_drawings():   # 글자 바로 위(30pt 이내)에서 글자 쪽을 덮는 가로 테두리선
            r = d["rect"]
            if (r[3] - r[1]) < 1.5 and (r[2] - r[0]) > 80 and r[0] <= x0 + 2 and r[2] >= x0 and 0 < y0 - r[3] <= 30:
                if best is None or r[1] > best[1]:
                    best = r
        if best is not None:
            top, bx0, bx1 = best[1], best[0], best[2]
        out.append((bx0, bx1, top))
    return out


def _is_spread(page, nums_cols):
    """두 쪽이 한 장에 펼쳐진 PDF의 한쪽에만 문제가 있는 경우인가?
    (가로로 넓고, 가운데 세로선을 가로지르는 글줄이 없다)"""
    W, H = page.rect.width, page.rect.height
    if W / H < 1.35:
        return False
    mid = W / 2
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            x0, y0, x1, y1 = ln["bbox"]
            if x0 < mid - 8 and x1 > mid + 8 and "".join(s["text"] for s in ln["spans"]).strip():
                return False
    return True


_SUBSTART = re.compile(r"^\s*(?:[\(（]\s*\d{1,2}\s*[\)）]|[①-⑳])")


def _badge_top(page, left, right, top, xnum, num_top):
    """번호 위쪽 경계(top)에 걸쳐 있는 작은 꼬리표('서술형' 같은 아이콘·글자)가 있으면 통째로 포함하도록 경계를 올린다.
    (반만 잘려 들어오는 것을 막는다)"""
    H = page.rect.height
    new = top
    cand = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 1:
            cand.append((pymupdf.Rect(b["bbox"]), 0))
            continue
        for ln in b.get("lines", []):
            txt = "".join(s["text"] for s in ln["spans"]).strip()
            if txt:
                cand.append((pymupdf.Rect(ln["bbox"]), len(txt)))
    for d in page.get_drawings():
        r = pymupdf.Rect(d["rect"])
        fill = d.get("fill")
        if (fill and min(fill) > 0.97 and not d.get("color")) or r.height < 3:
            continue
        cand.append((r, 0))
    inside = [(r, n) for r, n in cand if not (r.x1 <= left or r.x0 >= right)]
    for r, n in inside:
        if not (r.y0 < top < r.y1):
            continue
        if not (r.width < 100 and r.height < 40 and n <= 6 and r.x0 >= xnum - 6):   # 번호와 왼쪽이 맞는 작은 것만
            continue
        # 같은 줄에 넓은 띠(그림·도형)가 있으면 꼬리표가 아니라 단원 제목 띠다 → 포함하지 않고 그 아래부터 시작한다
        row = [q for q, m in inside if q.y0 < r.y1 and q.y1 > r.y0 and q.y0 < num_top - 2 and m == 0 and q.width >= 100 and q.height < 40]
        if row:
            new = max(new, min(max(q.y1 for q in row) + 1, num_top - 4))
        else:
            new = min(new, r.y0 - 2)
    return new


def _trim_trailing_badge(page, left, right, top, bottom, next_top):
    """다음 문제 바로 위에 붙은 작은 꼬리표(예: '발전', '서술형' 배지)는 다음 문제의 것이므로 이 문제 영역에서 뺀다.
    이 문제 내용과 떨어져(30pt 이상) 있고, 작고(폭 90·높이 45 미만), 다음 번호 바로 위(60pt 이내)에 있는 덩어리가 대상이다."""
    H = page.rect.height
    boxes = []
    for b in page.get_text("dict")["blocks"]:
        r = pymupdf.Rect(b["bbox"])
        if r.x1 <= left or r.x0 >= right or r.y1 <= top or r.y0 >= bottom:
            continue
        if b["type"] == 1:
            if r.height > 0.6 * H or r.width > 1.5 * (right - left):
                continue
            boxes.append((r, 0))
            continue
        for ln in b.get("lines", []):
            txt = "".join(s["text"] for s in ln["spans"]).strip()
            if txt:
                lr = pymupdf.Rect(ln["bbox"])
                if lr.x1 > left and lr.x0 < right and lr.y1 > top:
                    boxes.append((lr, len(txt)))
    for d in page.get_drawings():
        r = pymupdf.Rect(d["rect"])
        if r.x1 <= left or r.x0 >= right or r.y1 <= top or r.y0 >= bottom or r.height > 0.5 * H or r.width > 1.2 * (right - left):
            continue
        if r.height < 3 or (r.height < 12 and r.width > 90):
            continue   # 점선·구분선
        fill = d.get("fill")
        if fill and min(fill) > 0.97 and not d.get("color"):
            continue
        boxes.append((r, 0))
    if not boxes:
        return bottom
    boxes.sort(key=lambda t: t[0].y0)
    r0, n0 = boxes[0]
    clusters = [[r0.x0, r0.y0, r0.x1, r0.y1, n0]]
    for r, n in boxes[1:]:
        c = clusters[-1]
        if r.y0 - c[3] > 30:
            clusters.append([r.x0, r.y0, r.x1, r.y1, n])
        else:
            c[0], c[1], c[2], c[3], c[4] = min(c[0], r.x0), min(c[1], r.y0), max(c[2], r.x1), max(c[3], r.y1), c[4] + n
    last = clusters[-1]
    # 배지는 글자가 거의 없고(2~3개 쌓여 있어도 6자 이하) 작다. 다음 번호 바로 위(100pt 이내)에 있다.
    if len(clusters) >= 2 and last[3] - last[1] < 80 and last[2] - last[0] < 100 and last[4] <= 6 and last[1] >= next_top - 100:
        return min(bottom, last[1] - 2)
    return bottom


def _content_bottom(page, left, right, top, bottom, max_gap, text_only=False):
    """top에서 시작해 글줄·그림이 max_gap보다 크게 끊기기 전까지의 아래쪽 끝. (번호 없는 아래쪽 안내·표를 문제에서 떼어 낸다)"""
    W, H = page.rect.width, page.rect.height
    boxes = []
    fig_x = {}
    for b in page.get_text("dict")["blocks"]:
        r = pymupdf.Rect(b["bbox"])
        if r.x1 <= left or r.x0 >= right or r.y1 <= top or r.y0 >= bottom:
            continue
        if b["type"] == 1:
            if r.height > 0.6 * H or r.width > 1.5 * (right - left):
                continue   # 배경 그림
            boxes.append((r.y0, r.y1, ""))
            fig_x[(r.y0, r.y1, "")] = (r.x0, r.x1)
            continue
        for ln in b.get("lines", []):
            txt = "".join(s["text"] for s in ln["spans"]).strip()
            if txt:
                lr = pymupdf.Rect(ln["bbox"])
                if left < (lr.x0 + lr.x1) / 2 < right and lr.y1 > top:   # 글줄은 가운데가 이 단 안에 있어야 한다 (옆 단 글이 살짝 걸친 것은 제외)
                    boxes.append((lr.y0, lr.y1, txt))
    for d in page.get_drawings():   # 벡터로 그려진 그래프도 내용이다
        r = pymupdf.Rect(d["rect"])
        if r.x1 <= left or r.x0 >= right or r.y1 <= top or r.y0 >= bottom or r.height > 0.5 * H:
            continue
        fill = d.get("fill")
        if fill and min(fill) > 0.97 and not d.get("color"):
            continue
        if r.width > 1.2 * (right - left):
            # 옆 단·옆 쪽까지 넓게 깔린 색 상자(자기 평가 상자 등)는 문제 안이 아니라 문제 아래를 끊는 표지로만 쓴다
            if fill and r.height >= 30 and r.y0 > top + 20:
                boxes.append((r.y0, r.y1, ""))
                fig_x[(r.y0, r.y1, "")] = (r.x0, r.x1)
            continue
        boxes.append((r.y0, r.y1, ""))
        fig_x[(r.y0, r.y1, "")] = (r.x0, r.x1)
    panel_tops = [k[0] for k, v in fig_x.items() if v[1] - v[0] >= 150]
    figs = []
    if text_only:   # 본문 속 작은 문제: 글줄로만 이어짐을 따지고, 글 옆에 겹쳐 있는 그림만 나중에 보탠다 (아래에 붙은 장식 그림·상자는 뺀다)
        figs = [b for b in boxes if not b[2]]
        boxes = [b for b in boxes if b[2]]
    boxes.sort()
    if not boxes:
        return bottom
    cur = boxes[0][1]
    for bi in range(1, len(boxes)):
        y0, y1, txt = boxes[bi]
        if y0 >= 0.85 * H and y0 - cur >= 8:
            # 쪽 맨 아래에 붙은 작은 띠(이해도 표시 등): 그림·도형이 섞여 있고 글자가 거의 없으면 문제가 아니다
            rest = boxes[bi:]
            chars = sum(len(t) for _a, _b, t in rest)
            if max(r[1] for r in rest) - y0 <= 60 and any(not t for _a, _b, t in rest) and chars <= 25:
                break
        gap_lim = min(30, max_gap) if y0 > 0.85 * H else max_gap   # 쪽 맨 아래 띠(예: 이해도 표시)는 작은 빈틈에서도 끊는다
        # 40pt 넘게 떨어진 뒤에 큰 그림·색 상자(자기 평가 상자, 이해도 띠 같은 것)가 이어지면 문제 밖의 내용이다
        wide_panel = y0 - cur > 40 and any(py0 <= y1 + 40 and py0 > cur for py0 in panel_tops)
        if y0 - cur > (min(gap_lim, 40) if wide_panel else gap_lim) and not _SUBSTART.match(txt):   # '(2)' '②'로 시작하는 작은 문제는 같은 문제의 이어지는 부분
            break
        cur = max(cur, y1)
    for fb in figs:
        y0, y1, _t = fb
        x0, x1 = fig_x.get(fb, (left, right))
        inside = max(0.0, min(x1, right) - max(x0, left)) / max(1.0, x1 - x0)
        if y0 < cur - 6 and inside >= 0.5 and (y1 - y0) <= max(150, 2 * (cur - top)):   # 이 단 안에 있는 그림만 (옆으로 넓게 깔린 상자는 제외)
            cur = max(cur, y1)
    return min(bottom, cur + 8)


def find_big_numbers(doc, style):
    styles = style if isinstance(style, list) else [style]
    out = {}
    for pn, page in enumerate(doc):
        H = page.rect.height
        for t, key, bb, inl in _num_lines(page):
            if _style_match(key, styles) and HEADER_Y * H < bb[1] < FOOTER_Y * H:
                out.setdefault(pn, []).append((t, bb, inl))
    return out


def detect(doc):
    """문제 표지를 찾는 방법을 차례로 시도한다: 큰 번호 글자 / '추가 1.' 같은 글머리 / (스캔본) 이미지 분석."""
    style = find_number_styles(doc)
    big = find_big_numbers(doc, style) if style else {}
    marks = find_markers(doc)
    for pn, items in find_textbook_refs(doc).items():
        have = {m[0] for m in marks.get(pn, [])}
        marks.setdefault(pn, []).extend(it for it in items if it[0] not in have)
    plain = find_plain_markers(doc)
    lead = find_lead_markers(doc)
    n_big, n_mark, n_plain, n_lead = (sum(map(len, d.values())) for d in (big, marks, plain, lead))
    # 가장 많이 찾은 방법을 쓴다 (동점이면 큰 번호 > 낱말 글머리 > 굵은 번호 > 줄머리 번호 순)
    options = [(n, -i, per) for i, (n, per, need) in enumerate([(n_big, big, 1), (n_mark, marks, 2), (n_plain, plain, 4), (n_lead, lead, 4)]) if n >= need]
    if not options and not style:   # 마지막 수단: 쪽 번호처럼 보여도 큰 숫자 글자를 문제 번호로 써 본다
        style2 = find_number_styles(doc, allow_page_like=True)
        if style2:
            big = find_big_numbers(doc, style2)
            n_big = sum(map(len, big.values()))
            if n_big >= 1:
                options = [(n_big, 0, big)]
    if not options:
        import detect_scan  # 글자 정보가 없으면 이미지 분석(스캔본)으로 넘어간다
        return detect_scan.detect_scanned(doc)
    per_page = max(options)[2]
    foot_y = find_footer_y(doc)
    problems = []
    notices = {pn: find_notices(pg) for pn, pg in enumerate(doc)}   # 문제가 아닌 안내 상자 (예: '확인 사항')
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
                if xl < W / 2 and _is_spread(page, cols):
                    right = W / 2 - 10   # 펼침면의 반대쪽 쪽(읽기 자료 등)까지 번지지 않게
            col.sort(key=lambda n: n[1][1])
            tops = [n[1][1] - 1 if len(n) > 3 and n[3] else max(0, _badge_top(page, left, right, n[1][1] - 8, n[1][0], n[1][1])) for n in col]
            for i, (t, bb, *_x) in enumerate(col):
                inl = bool(_x and _x[0])
                top = tops[i]
                bottom = tops[i + 1] if i + 1 < len(col) else min(FOOTER_Y * H, foot_y if foot_y else H)
                if i + 1 < len(col):   # 다음 문제 위에 붙은 배지는 다음 문제의 것
                    bottom = _trim_trailing_badge(page, left, right, top, bottom, col[i + 1][1][1])
                if inl:   # 본문 속 작은 문제는 문제 글 바로 아래의 다른 설명·상자까지 가져오지 않는다
                    bottom = _content_bottom(page, left, right, top, bottom, 24, text_only=True)
                if i + 1 == len(col):   # 단의 마지막 문제: 아래에 번호 없는 표·안내가 있으면 큰 빈틈에서 끊는다
                    bottom = _content_bottom(page, left, right, top, bottom, 125)
                for nx0, nx1, ntop in notices.get(pn, []):   # 안내 상자는 마지막 문제 영역에서 뺀다
                    if nx1 > left and nx0 < right and ntop > top:
                        bottom = min(bottom, ntop - 4)
                region = pymupdf.Rect(left, max(0, top), right, bottom)
                rect = _trim(page, region, xmin=xl - 3)
                problems.append({
                    "page": pn, "label": t, "col": ci,
                    "rect": [round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1)],
                    "on": True, "answer": None,
                    "mask": bool(answer_rects(page, rect)),   # 문제 안에 '(정답 : …)'이 인쇄돼 있으면 수업 화면에서 가린다
                })
    label_sections(doc, problems)
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


def find_figures(page, rect, min_size=38.0):
    """문제 영역 안의 그래프·그림 후보 사각형들(읽는 순서). 벡터 도형 묶음과 이미지를 함께 찾는다."""
    rect = pymupdf.Rect(rect)
    boxes = []   # [rect, 개수]
    for im in page.get_image_info():
        r = pymupdf.Rect(im["bbox"])
        c = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if rect.contains(c) and r.width >= min_size and r.height >= min_size:
            boxes.append([r & rect, 8])
    for d in page.get_drawings():
        r = pymupdf.Rect(d["rect"])
        if r.x0 < rect.x0 - 3 or r.y0 < rect.y0 - 3 or r.x1 > rect.x1 + 3 or r.y1 > rect.y1 + 3:
            continue   # 영역 밖으로 나가는 큰 배경·테두리
        if r.width > 0.9 * rect.width and r.height > 25:
            continue   # 문제 전체를 두른 상자
        if max(r.width, r.height) > 140 and min(r.width, r.height) < 3:
            continue   # 긴 구분선·테두리선
        # 두께 0인 선은 합집합 계산에서 빠지므로 아주 조금 부풀린다
        boxes.append([pymupdf.Rect(r.x0 - .4, r.y0 - .4, r.x1 + .4, r.y1 + .4), 1])
    # 가까운(겹치거나 6pt 이내) 도형끼리 묶는다
    merged = True
    while merged and len(boxes) > 1:
        merged = False
        out = []
        while boxes:
            a = boxes.pop()
            grow = pymupdf.Rect(a[0].x0 - 6, a[0].y0 - 6, a[0].x1 + 6, a[0].y1 + 6)
            keep = []
            for b in boxes:
                if grow.intersects(b[0]):
                    a = [a[0] | b[0], a[1] + b[1]]
                    grow = pymupdf.Rect(a[0].x0 - 6, a[0].y0 - 6, a[0].x1 + 6, a[0].y1 + 6)
                    merged = True
                else:
                    keep.append(b)
            boxes = keep
            out.append(a)
        boxes = out
    figs = [r for r, n in boxes if n >= 6 and r.width >= min_size and r.height >= min_size]
    # 축 이름·점 이름 같은 짧은 글자도 그림에 포함한다
    lines = [pymupdf.Rect(ln["bbox"]) for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])
             if ln["bbox"][2] - ln["bbox"][0] < 70]
    res = []
    for f in figs:
        g = pymupdf.Rect(f)
        near = pymupdf.Rect(f.x0 - 12, f.y0 - 10, f.x1 + 12, f.y1 + 10)
        for ln in lines:
            if near.contains(pymupdf.Point((ln.x0 + ln.x1) / 2, (ln.y0 + ln.y1) / 2)):
                g |= ln
        g = pymupdf.Rect(g.x0 - 5, g.y0 - 5, g.x1 + 5, g.y1 + 5) & rect
        res.append(g)
    res.sort(key=lambda r: (round(r.y0 / 25), r.x0))
    return [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)] for r in res]


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
