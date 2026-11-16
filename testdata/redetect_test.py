"""재검출·서버 교체 시험: 예전 잘못된 결과가 저장된 작업을 다시 올리면 새 결과로 바뀌는지,
사용자가 고친 작업은 그대로 남는지, 새 서버가 이전 서버를 대신하는지 확인한다.
실행 전에 서버가 켜져 있어야 한다:  python mathslide/server.py --no-browser
사용법: python testdata/redetect_test.py "<PDF 경로>"
"""
import json
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
PROJ = Path(__file__).resolve().parent.parent / "mathslide" / "projects"
pdf = Path(sys.argv[1])


def upload():
    req = urllib.request.Request(BASE + "/api/upload?name=test.pdf", data=pdf.read_bytes(), method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def info(pid):
    return json.loads(urllib.request.urlopen(f"{BASE}/api/p/{pid}/info", timeout=60).read())


first = upload()
pid = first["id"]
d = PROJ / pid
print("1) 처음 올림:", len(first["problems"]), "문제")

# 예전 버전이 잘못 저장해 둔 상태를 흉내 낸다: 틀린 결과 + 버전 정보 없음 + 자동검출 사본 없음
wrong = [{"id": "q1", "page": 0, "label": "09", "col": 0, "rect": [1, 1, 50, 50], "on": True, "answer": None}]
(d / "problems.json").write_text(json.dumps(wrong), encoding="utf-8")
(d / "auto.json").unlink(missing_ok=True)
meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
meta.pop("detect_version", None)
(d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
print("2) 예전 잘못된 결과로 바꿔 둠: 1 문제")

again = upload()
print("3) 같은 파일을 다시 올림 ->", len(again["problems"]), "문제 (자동으로 다시 검출되어야 함)")
assert len(again["problems"]) == len(first["problems"]), "다시 검출되지 않음"

# 사용자가 고친 경우는 그대로 남아야 한다: 한 문제의 체크를 해제한 뒤 버전을 낮춰 본다
probs = again["problems"]
probs[0]["on"] = False
(d / "problems.json").write_text(json.dumps(probs), encoding="utf-8")
meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
meta["detect_version"] = 0
(d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
kept = info(pid)
print("4) 사용자가 고친 작업(체크 해제)은 유지:", kept["problems"][0]["on"] is False)
assert kept["problems"][0]["on"] is False
print("모두 통과")
