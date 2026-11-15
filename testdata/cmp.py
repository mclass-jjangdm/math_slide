"""스캔본 자동 인식 결과를 원본(텍스트 PDF) 자동 검출 결과와 비교하는 시험 스크립트."""
import os
import sys
import pymupdf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mathslide"))
import detect
import detect_scan as ds

HERE = os.path.dirname(__file__)
SAMPLE = r"G:\공유 드라이브\Bank\고등수학\2022개정교육과정\미적분1\교재\수학의바이블유형ON라이트\sample_미적분1.pdf"
d = pymupdf.open(os.path.join(HERE, "sample_scanned.pdf"))
ref = pymupdf.open(SAMPLE)
a = ds.detect_scanned(d)
b = detect.detect(ref)
print("스캔 인식", len(a), "/ 정답(텍스트 검출)", len(b))


def iou(r, s):
    x0, y0 = max(r[0], s[0]), max(r[1], s[1])
    x1, y1 = min(r[2], s[2]), min(r[3], s[3])
    i = max(0, x1 - x0) * max(0, y1 - y0)
    u = (r[2] - r[0]) * (r[3] - r[1]) + (s[2] - s[0]) * (s[3] - s[1]) - i
    return i / u


miss, good = [], 0
for q in b:
    m = max((iou(q["rect"], p["rect"]) for p in a if p["page"] == q["page"]), default=0)
    if m > 0.7:
        good += 1
    else:
        miss.append((q["label"], round(m, 2)))
print("일치(IoU>0.7):", good, " 놓침/부정확:", miss)
print("엉뚱하게 추가:", [(p["page"] + 1, p["label"]) for p in a
                    if max((iou(p["rect"], q["rect"]) for q in b if q["page"] == p["page"]), default=0) < 0.3])
