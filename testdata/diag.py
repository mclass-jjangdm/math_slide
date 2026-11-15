import os, sys
import numpy as np
import pymupdf
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mathslide"))
import detect, detect_scan as ds

HERE = os.path.dirname(__file__)
SAMPLE = r"G:\공유 드라이브\Bank\고등수학\2022개정교육과정\미적분1\교재\수학의바이블유형ON라이트\sample_미적분1.pdf"
d = pymupdf.open(os.path.join(HERE, "sample_scanned.pdf"))
b = detect.detect(pymupdf.open(SAMPLE))
inks = {}
for q in b:
    pn = q["page"]
    if pn not in inks:
        inks[pn] = ds._ink(ds._gray(d[pn]))
        H, W = inks[pn].shape
        g = ds._gutter(inks[pn], int(H * .02), int(H * .935))
        inks[pn] = (inks[pn], g)
    ink, g = inks[pn]
    H, W = ink.shape
    zt, zb = int(H * .02), int(H * .935)
    # 번호 위치(상자 왼쪽 위 + 약간)
    x = int((q["rect"][0] + 8) / ds.K); y = int((q["rect"][1] + 8) / ds.K)
    strips = [(0, g + 40, 0, g - 30), (g - 30, W, g - 30, W)] if g else [(0, W, 0, W)]
    hit = None
    for x0, x1, lo, hi in strips:
        for c in ds._candidates(ink, x0, x1, zt, zb):
            if lo <= c["x0"] < hi and abs(c["top"] - y) < 22 and abs(c["x0"] - x) < 60:
                hit = c
    if not hit:
        # 해당 위치 줄 분석
        sub = ink[max(0, y - 14):y + 30, max(0, x - 40):x + 160]
        rows = ds._runs(sub.sum(1) >= 1, 3)
        info = []
        for ls, le in rows[:3]:
            ch = ds._runs(sub[ls:le].sum(0) >= 1, 5)
            info.append((ls, le, [(a, bb) for a, bb in ch[:4]]))
        print(f"p{pn+1} {q['label']} gutter={g} expect px=({x},{y}) 못찾음  lines={info}")
