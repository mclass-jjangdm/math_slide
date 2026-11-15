import os, sys
import pymupdf
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mathslide"))
import detect, detect_scan as ds, digits

HERE = os.path.dirname(__file__)
SAMPLE = r"G:\공유 드라이브\Bank\고등수학\2022개정교육과정\미적분1\교재\수학의바이블유형ON라이트\sample_미적분1.pdf"
d = pymupdf.open(os.path.join(HERE, "sample_scanned.pdf"))
truth = detect.detect(pymupdf.open(SAMPLE))
tl = {}
for q in truth:
    tl.setdefault(q["page"], []).append((q["rect"][0] / ds.K, q["rect"][1] / ds.K, q["label"]))
good, bad = [], []
for pn in range(len(d)):
    ink = ds._ink(ds._gray(d[pn]))
    H, W = ink.shape
    zt, zb = int(H * .02), int(H * .935)
    gr = ds._gutter(ink, zt, zb)
    mid = (gr[0] + gr[1]) // 2 if gr else None
    strips = [(0, mid, 0, mid), (mid, W, mid, W)] if gr else [(0, W, 0, W)]
    for x0, x1, lo, hi in strips:
        for c in ds._candidates(ink, x0, x1, zt, zb):
            if not (lo <= c["x0"] < hi):
                continue
            s, sc = digits.read_number(ink, c["x0"], c["top"], c["x1"], c["bot"])
            match = [t for t in tl.get(pn, []) if abs(t[1] - c["top"]) < 25 and abs(t[0] - c["x0"]) < 70]
            (good if match else bad).append((pn + 1, c["x0"], c["top"], c["h"], s, round(sc, 2), match[0][2] if match else ""))
print("진짜 번호 후보 (읽은 값 / 점수 / 정답):")
for g in good:
    print("  ", g)
print("가짜 후보:")
for b in bad:
    print("  ", b)
