"""스캔본(글자 정보가 없는 이미지 PDF)에서 문제 영역을 찾는다. OCR 없이 화면 구조만 본다.

원리
  1) 페이지를 흑백 이미지로 바꾸고, 긴 직선(표 테두리·그림 축)은 지운다.
  2) 두 단 사이의 빈 세로 띠(여백 통로)를 찾아 단을 나눈다.
  3) 각 단에서 글줄을 찾고, 줄의 '맨 앞 덩어리'가 폭이 좁고 본문보다 큰 글자면 번호 후보로 본다.
     (예: 658 처럼 크게 인쇄된 문제 번호)
  4) 문서 전체에서 크기가 비슷한 후보가 가장 많은 묶음을 '문제 번호'로 확정한다.
  5) 번호 위치부터 같은 단의 다음 번호 직전까지를 한 문제로 자르고 여백을 다듬는다.
번호 글자를 읽지는 않으므로 라벨은 1, 2, 3… 순서로 임시로 붙인다(화면에서 고칠 수 있다).
"""
import numpy as np
import pymupdf

import digits

DPI = 100
K = 72.0 / DPI


def _gray(page):
    pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)


def _kill_runs(m, minlen):
    """세로 방향으로 minlen 이상 이어진 잉크를 지운다."""
    out = m.copy()
    for x in np.where(m.sum(0) >= minlen)[0]:
        d = np.diff(np.concatenate(([0], m[:, x].astype(np.int8), [0])))
        for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
            if e - s >= minlen:
                out[s:e, x] = False
    return out


def _ink(gray):
    bg = float(np.percentile(gray, 90))
    ink = gray < min(190.0, bg - 55)
    ink = _kill_runs(ink, 60)               # 세로 직선
    ink = _kill_runs(ink.T, 110).T          # 가로 직선
    return ink


def _runs(v, gap):
    """불리언 1차원 배열에서 True 구간을 (시작, 끝(미포함))로. gap 이하 틈은 이어 붙인다."""
    idx = np.where(v)[0]
    if not len(idx):
        return []
    out, s, p = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - p > gap + 1:
            out.append((int(s), int(p) + 1))
            s = i
        p = i
    out.append((int(s), int(p) + 1))
    return out


def _gutter(ink, y0, y1):
    """두 단 사이 통로의 x 중심(없으면 None)."""
    W = ink.shape[1]
    lo, hi = int(W * .3), int(W * .7)
    votes, n = np.zeros(W, int), 0
    for y in range(y0, y1 - 40, 40):
        slab = ink[y:y + 40]
        # 왼쪽 단 자리와 오른쪽 단 자리에 모두 글이 있는 띠만 '두 단 증거'로 센다
        if slab[:, int(W * .1):int(W * .4)].sum() < 15 or slab[:, int(W * .6):int(W * .9)].sum() < 15:
            continue
        n += 1
        votes += (slab.sum(0) == 0)
    if n < 2:
        return None
    ok = votes >= 0.7 * n
    best = None
    for s, e in _runs(ok[lo:hi], 0):
        if e - s >= 8 and (best is None or (e - s) > best[1] - best[0]):
            best = (s + lo, e + lo)
    # 통로의 오른쪽 끝 = 오른쪽 단 글자가 시작되는 곳
    return best


def _candidates(ink, x0, x1, y0, y1):
    sub = ink[:, x0:x1]
    rows = sub[y0:y1].sum(1) >= 1
    cands = []
    for ls, le in _runs(rows, 1):
        ls += y0
        le += y0
        if le - ls > 130:
            continue
        cols = sub[ls:le].sum(0) >= 1
        chunks = _runs(cols, 6)
        if not chunks:
            continue
        xs, xe = chunks[0]
        if xe - xs > 62:
            # 번호 바로 아래 글줄이 붙어 있는 경우: 맨 위쪽에서 폭이 좁은 줄들만 번호로 본다
            blk = sub[ls:le, xs:xe]
            narrow_end, started = None, False
            for r in range(blk.shape[0]):
                cols_r = np.where(blk[r])[0]
                if len(cols_r) == 0:
                    if started and narrow_end is None:
                        narrow_end = r
                    continue
                if cols_r[-1] > 60:
                    narrow_end = r
                    break
                started = True
            if narrow_end is None:
                narrow_end = blk.shape[0]
            if narrow_end >= 15:
                le = ls + narrow_end
                cols2 = sub[ls:le].sum(0) >= 1
                ch2 = _runs(cols2, 6)
                if not ch2:
                    continue
                xs, xe = ch2[0]
        h_rows = np.where(sub[ls:le, xs:xe].any(1))[0]
        if not len(h_rows):
            continue
        top, bot = ls + int(h_rows[0]), ls + int(h_rows[-1]) + 1
        h, w = bot - top, xe - xs
        if not (15 <= h <= 42 and 0.5 * h <= w <= 3.4 * h):
            continue
        if x0 + xs > ink.shape[1] * 0.93:
            continue  # 가장자리 인덱스 탭
        cands.append({"x0": x0 + xs, "x1": x0 + xe, "top": top, "bot": bot, "h": h})
    return cands


def _trim(ink, r, pad_pt=5):
    x0, y0, x1, y1 = r
    x1 = min(x1, int(ink.shape[1] * 0.93))   # 가장자리 인덱스 탭 제외
    sub = ink[y0:y1, x0:x1]
    rows = np.where(sub.sum(1) >= 2)[0]
    cols = np.where(sub.sum(0) >= 2)[0]
    if not len(rows) or not len(cols):
        return r
    p = int(pad_pt / K)
    return (max(x0, x0 + int(cols[0]) - p), max(y0, y0 + int(rows[0]) - p),
            min(x1, x0 + int(cols[-1]) + 1 + p), min(y1, y0 + int(rows[-1]) + 1 + p))


def detect_scanned(doc):
    pages = []
    for pn, page in enumerate(doc):
        ink = _ink(_gray(page))
        H, W = ink.shape
        zt, zb = int(H * .02), int(H * .935)
        gr = _gutter(ink, zt, zb)
        # 두 단이면 통로의 한가운데에서 가른다 (통로 오른쪽 끝 g = 오른쪽 단 글자 시작)
        if gr:
            g = gr[1]
            mid = max(gr[0] + 2, g - 8)   # 오른쪽 단 글자가 시작되기 직전
            strips = [(0, mid, 0, mid, 0, g), (mid, W, mid, W, g, W)]
        else:
            strips = [(0, W, 0, W, 0, W)]
        found = []
        for ci, (x0, x1, lo, hi, cx0, cx1) in enumerate(strips):
            cs = [c for c in _candidates(ink, x0, x1, zt, zb) if lo <= c["x0"] < hi]
            found.append((ci, cx0, cx1, cs))
        pages.append((pn, ink, H, W, zt, zb, found))

    # 문서 전체에서 번호 글자 크기 묶음 고르기
    hs = [c["h"] for p in pages for f in p[6] for c in f[3]]
    if len(hs) < 2:
        return []
    cnt = {h0: sum(1 for h in hs if abs(h - h0) <= 1) for h0 in range(min(hs), max(hs) + 1)}
    best = max(cnt, key=cnt.get)
    if cnt[best] < 2:
        return []

    # 숫자로 읽히는지 확인(템플릿 매칭). 후보의 절반 이상이 숫자로 읽히면 읽힌 것만 쓰고 번호값도 쓴다.
    sized = []
    for pn, ink, H, W, zt, zb, found in pages:
        for ci, x0, x1, cands in found:
            for c in cands:
                if abs(c["h"] - best) <= 2:
                    c["txt"], c["sc"] = digits.read_number(ink, c["x0"], c["top"], c["x1"], c["bot"])
                    sized.append(c)
    readable = [c for c in sized if c["sc"] >= 0.45 and c["txt"].strip("0")]
    use_read = len(readable) >= max(2, 0.5 * len(sized))
    keep = set(id(c) for c in (readable if use_read else sized))

    problems = []
    for pn, ink, H, W, zt, zb, found in pages:
        for ci, x0, x1, cands in found:
            cs = [c for c in cands if id(c) in keep]
            if not cs:
                continue
            med = float(np.median([c["x0"] for c in cs]))
            cs = sorted([c for c in cs if abs(c["x0"] - med) <= 16], key=lambda c: c["top"])
            for i, c in enumerate(cs):
                top = max(zt, c["top"] - 11)
                bottom = (cs[i + 1]["top"] - 11) if i + 1 < len(cs) else zb
                left = max(0, c["x0"] - 30) if ci == 0 else max(x0, c["x0"] - 14)
                right = x1 - 10 if ci + 1 < len(found) or len(found) == 1 else W - 10
                if ci + 1 < len(found):
                    right = x1 - 10
                r = _trim(ink, (left, top, right, bottom))
                problems.append({
                    "page": pn, "label": c["txt"] if use_read else "", "col": ci, "_k": (pn, ci, c["top"]),
                    "rect": [round(v * K, 1) for v in r], "on": True, "answer": None,
                })
    problems.sort(key=lambda p: p.pop("_k"))
    if use_read:
        _repair([p for p in problems])
    for i, p in enumerate(problems):
        if not p["label"]:
            p["label"] = str(i + 1)
    return problems


def _repair(ps):
    """읽은 번호가 순서(+1씩 증가)에 어긋나면 이웃으로 바로잡는다. 예: 700, 5131, 702 → 701"""
    def val(i):
        t = ps[i]["label"]
        return int(t) if t.isdigit() else None
    n = len(ps)
    for _ in range(2):
        for i in range(n):
            v = val(i)
            prev = val(i - 1) if i > 0 else None
            nxt = val(i + 1) if i + 1 < n else None
            if prev is not None and nxt is not None and nxt - prev == 2 and v != prev + 1:
                ps[i]["label"] = str(prev + 1)
            elif i == 0 and nxt is not None and v != nxt - 1 and n > 2 and val(2) == nxt + 1:
                ps[i]["label"] = str(nxt - 1)
            elif i == n - 1 and prev is not None and v != prev + 1 and n > 2 and val(n - 3) == prev - 1:
                ps[i]["label"] = str(prev + 1)


if __name__ == "__main__":
    import sys
    d = pymupdf.open(sys.argv[1])
    for p in detect_scanned(d):
        print(p["page"] + 1, p["label"], p["rect"])
