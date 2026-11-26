"""엠클래스수학과학전문학원 수업 슬라이드 - 로컬 서버.   실행:  python server.py
브라우저가 자동으로 열린다(http://localhost:8765).  외부 인터넷 불필요.
필요 라이브러리: pymupdf  (pip install pymupdf)
"""
import base64
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    import pymupdf
except ImportError as _e:   # 설치가 안 됐거나, 파이썬 버전과 맞지 않을 때 안내
    print("\n[오류] PyMuPDF를 불러오지 못했습니다:", _e)
    print("  - 'pip install -r requirements.txt' 를 실행했는지 확인하세요.")
    print("  - 파이썬 3.14 이상(미리보기 버전)이면 정식 버전(3.12 권장)을 쓰세요.")
    print("  - 'DLL load failed'라면 Microsoft Visual C++ 재배포 패키지를 설치하세요: https://aka.ms/vs/17/release/vc_redist.x64.exe")
    print("  - 가장 쉬운 방법: 저장소 맨 위의 start.bat 을 더블클릭하세요.")
    sys.exit(1)

import detect

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
PROJECTS = ROOT / "projects"
UPLOAD_TMP = ROOT / "upload_tmp.pdf"
PROJECTS.mkdir(exist_ok=True)
PORT = 8765
LOCK = threading.RLock()   # pymupdf는 스레드 안전하지 않다
_docs = {}


def pdir(pid):
    if not re.fullmatch(r"[0-9a-f]{10}", pid):
        raise ValueError("bad id")
    return PROJECTS / pid


def get_doc(pid):
    if pid not in _docs:
        _docs[pid] = pymupdf.open(str(pdir(pid) / "src.pdf"))
    return _docs[pid]


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def number_ids(problems):
    for i, p in enumerate(problems):
        p["id"] = f"q{i + 1}"
    return problems


def _unedited(cur, auto):
    """사용자가 손대지 않은 검출 결과인가? (자동 검출 결과 사본과 같거나, 사본이 없으면 흔적이 없는 경우)"""
    if auto is not None:
        return cur == auto
    return not any(p.get("figs") or p.get("figV") or p.get("view") or p.get("answer") or not p.get("on", True) for p in cur)


def refresh_detection(pid, force=False):
    """문제 영역이 없거나, 검출 규칙이 새로워졌는데 사용자가 고친 것이 없으면 다시 검출한다."""
    d = pdir(pid)
    meta = read_json(d / "meta.json", {})
    cur = read_json(d / "problems.json", None)
    stale = meta.get("detect_version") != detect.DETECT_VERSION
    if cur is None or force or (stale and _unedited(cur, read_json(d / "auto.json", None))):
        with LOCK:
            new = number_ids(detect.detect(get_doc(pid)))
        write_json(d / "problems.json", new)
        write_json(d / "auto.json", new)
    meta["detect_version"] = detect.DETECT_VERSION
    write_json(d / "meta.json", meta)


def project_info(pid):
    d = pdir(pid)
    refresh_detection(pid)
    meta = read_json(d / "meta.json", {})
    doc = get_doc(pid)
    return {
        "id": pid, "name": meta.get("name", pid),
        "pages": [[round(p.rect.width, 1), round(p.rect.height, 1)] for p in doc],
        "scanned": meta.get("scanned", False),
        "problems": read_json(d / "problems.json", []),
    }


def parse_pages(spec, n):
    """'48-50,61,68-70' 같은 쪽 지정(1부터, 쉼표·공백으로 구분, 범위는 - 또는 ~)을 쪽 번호 목록으로. 적은 순서대로, 중복은 한 번만."""
    out = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:\s*[-~]\s*(\d+))?", part)
        if not m:
            raise ValueError(f"쪽 범위를 읽을 수 없습니다: '{part}' (예: 48-50,61,68-70)")
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a < 1 or a > b or b > n:
            raise ValueError(f"쪽 범위가 올바르지 않습니다: '{part}' (이 PDF는 {n}쪽까지 있어요)")
        out.extend(p for p in range(a, b + 1) if p not in out)
    if not out:
        raise ValueError("가져올 쪽이 없습니다")
    return out


def slice_pdf(data, pages_spec=None, first=1, last=10**6):
    """지정한 쪽만 남긴 새 PDF. pages_spec('48-50,61')가 없으면 first~last(양끝 포함). 전체면 원본 그대로.
    반환: (PDF 바이트, 전체 쪽 수, 선택한 쪽 번호 목록)"""
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        raise ValueError("암호가 걸린 PDF입니다. 암호를 해제한 파일을 올려 주세요.")
    n = len(doc)
    if pages_spec:
        sel = parse_pages(pages_spec, n)
    else:
        first, last = max(1, first), min(n, last)
        if first > last:
            raise ValueError(f"쪽 범위가 올바르지 않습니다 (이 PDF는 {n}쪽까지 있어요)")
        sel = list(range(first, last + 1))
    if sel == list(range(1, n + 1)):
        return data, n, sel
    doc.select([p - 1 for p in sel])
    return doc.tobytes(garbage=3, deflate=True), n, sel


def pages_label(sel):
    """[48,49,50,61,68,69,70] → '48-50,61,68-70'"""
    runs, i = [], 0
    while i < len(sel):
        j = i
        while j + 1 < len(sel) and sel[j + 1] == sel[j] + 1:
            j += 1
        runs.append(str(sel[i]) if i == j else f"{sel[i]}-{sel[j]}")
        i = j + 1
    return ",".join(runs)


def create_project(name, data):
    pid = hashlib.sha1(data).hexdigest()[:10]
    d = PROJECTS / pid
    d.mkdir(exist_ok=True)
    if not (d / "src.pdf").exists():
        (d / "src.pdf").write_bytes(data)
    with LOCK:
        doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.needs_pass:
            raise ValueError("암호가 걸린 PDF입니다. 암호를 해제한 파일을 올려 주세요.")
        _docs[pid] = pymupdf.open(str(d / "src.pdf"))
        doc = _docs[pid]
        scanned = sum(len(p.get_text()) for p in doc) < 20 * max(1, len(doc))
        meta = read_json(d / "meta.json", {})
        meta.update({"name": name, "pages": len(doc), "scanned": scanned})
        meta.setdefault("created", time.time())
        write_json(d / "meta.json", meta)
    refresh_detection(pid)   # 새로 올렸거나 규칙이 바뀌었으면(사용자가 고친 게 없을 때) 다시 검출
    return pid


def render_png(pid, pno, clip, dpi, mask=False):
    key = hashlib.md5(f"{pno}{clip}{dpi}{mask}".encode()).hexdigest()
    cache = pdir(pid) / "cache"
    cache.mkdir(exist_ok=True)
    f = cache / f"{key}.png"
    if f.exists():
        return f.read_bytes()
    with LOCK:
        pg = get_doc(pid)[pno]
        pix = pg.get_pixmap(dpi=dpi, clip=pymupdf.Rect(*clip) if clip else None, alpha=False)
        png = None
        if mask and clip:   # 인쇄된 '(정답 : …)'을 흰색으로 덮는다
            rs = detect.answer_rects(pg, clip)
            if rs:
                from PIL import Image, ImageDraw
                import io
                s = dpi / 72.0
                im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                dr = ImageDraw.Draw(im)
                for r in rs:
                    dr.rectangle([(r.x0 - clip[0]) * s, (r.y0 - clip[1]) * s,
                                  (r.x1 - clip[0]) * s + 1, (r.y1 - clip[1]) * s + 1], fill=(255, 255, 255))
                buf = io.BytesIO()
                im.save(buf, "PNG")
                png = buf.getvalue()
        if png is None:
            png = pix.tobytes("png")
    f.write_bytes(png)
    return png


def make_handout(pid, per, title=""):
    """학생용 유인물: A4, 한 장에 per(1/2/4)문제, 풀이 공간 포함. 벡터 그대로 잘라 붙인다."""
    problems = [p for p in read_json(pdir(pid) / "problems.json", []) if p.get("on", True) and not p.get("blank")]   # 빈 페이지는 유인물에서 뺀다
    W, H, M = 595.0, 842.0, 34.0
    cols, rows = {1: (1, 1), 2: (1, 2), 4: (2, 2)}[per]
    cw, ch = (W - 2 * M) / cols, (H - 2 * M) / rows
    out = pymupdf.open()
    with LOCK:
        src = get_doc(pid)
        rects = [pymupdf.Rect(*p["rect"]) for p in problems]
        # 글자 크기를 문제마다 맞추지 않고 모두 같은 배율로: 폭에 맞는 배율의 중앙값을 기준으로 한다.
        fits = sorted((cw - 14) / r.width for r in rects)
        s0 = min(1.5, fits[len(fits) // 2]) if fits else 1.0
        pages, owner, k = [], None, 0   # owner[r][c] = 칸을 차지한 문제 번호(여러 칸에 걸칠 수 있음)

        for i, (p, clip) in enumerate(zip(problems, rects)):
            s = min(s0, (cw - 14) / clip.width)
            n = max(1, -(-int(clip.height * s / 0.62 * 1000) // int(ch * 1000)))   # 풀이 공간까지 합쳐 필요한 칸 수
            if n >= rows:
                n = rows
                s = min(s, 0.85 * rows * ch / clip.height)
            # 순서를 지키면서 문제가 들어갈 첫 빈 자리를 찾는다 (세로로 n칸이 비어 있어야 함)
            while True:
                if owner is None or k >= rows * cols:
                    page = out.new_page(width=W, height=H)
                    owner = [[None] * cols for _ in range(rows)]
                    pages.append(owner)
                    k = 0
                r, c = divmod(k, cols)
                if r + n <= rows and all(owner[r + j][c] is None for j in range(n)):
                    break
                k += 1
            for j in range(n):
                owner[r + j][c] = i
            k += 1
            x0, y0 = M + c * cw, M + r * ch
            dst = pymupdf.Rect(x0 + 4, y0 + 4, x0 + 4 + clip.width * s, y0 + 4 + clip.height * s)
            page.show_pdf_page(dst, src, p["page"], clip=clip)
            for ar in detect.answer_rects(src[p["page"]], clip):   # 정답 글자 가리기
                page.draw_rect(pymupdf.Rect(dst.x0 + (ar.x0 - clip.x0) * s, dst.y0 + (ar.y0 - clip.y0) * s,
                                            dst.x0 + (ar.x1 - clip.x0) * s, dst.y0 + (ar.y1 - clip.y0) * s),
                               color=None, fill=(1, 1, 1))
        if per > 1:   # 구분선: 같은 문제가 차지한 칸 사이에는 긋지 않는다
            for pno, ow in enumerate(pages):
                page = out[pno]
                for c in range(cols - 1):
                    page.draw_line((M + (c + 1) * cw, M + 4), (M + (c + 1) * cw, M + rows * ch - 4),
                                   color=(.8, .8, .8), width=.5, dashes="[3 3] 0")
                for r in range(rows - 1):
                    for c in range(cols):
                        if ow[r][c] is not None and ow[r][c] == ow[r + 1][c]:
                            continue
                        page.draw_line((M + c * cw + 4, M + (r + 1) * ch), (M + (c + 1) * cw - 4, M + (r + 1) * ch),
                                       color=(.8, .8, .8), width=.5, dashes="[3 3] 0")
        # 머리글(제목)과 쪽 번호: 바깥 여백에 작은 회색 글씨
        ff = Path(r"C:\Windows\Fonts\malgun.ttf")
        total = len(out)
        for pno in range(total):
            page = out[pno]
            kw = {"fontname": "mgn", "fontfile": str(ff)} if ff.exists() else {"fontname": "korea"}
            if title:
                page.insert_text((M, 24), title, fontsize=8.5, color=(.45, .45, .45), **kw)
            label = f"{pno + 1} / {total}"
            fnt = pymupdf.Font(fontfile=str(ff)) if ff.exists() else pymupdf.Font("helv")
            page.insert_text(((W - fnt.text_length(label, fontsize=8.5)) / 2, H - 16), label, fontsize=8.5, color=(.45, .45, .45), **kw)
        data = out.tobytes(garbage=3, deflate=True)
    return data


def make_slides_pdf(images):
    out = pymupdf.open()
    with LOCK:
        for url in images:
            raw = base64.b64decode(url.split(",", 1)[1])
            pg = out.new_page(width=960, height=540)
            pg.insert_image(pg.rect, stream=raw)
        return out.tobytes(garbage=3, deflate=True)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def route(self, method):
        u = urlparse(self.path)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if method == "GET" and not path.startswith("/api/"):
                rel = "index.html" if path in ("/", "") else path.lstrip("/")
                f = (STATIC / rel).resolve()
                if STATIC.resolve() not in f.parents or not f.is_file():
                    return self.send(404, b"not found", "text/plain")
                ct = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
                return self.send(200, f.read_bytes(), ct + ("; charset=utf-8" if ct.startswith("text") else ""),
                                 {"Cache-Control": "no-cache"})   # 화면 파일은 항상 최신으로

            if path == "/api/shutdown" and method == "POST":
                if self.headers.get("X-Quit") != "1":   # 다른 웹페이지가 마음대로 끄지 못하게 한다
                    return self.send(403, {"error": "forbidden"})
                self.send(200, {"ok": True})
                threading.Thread(target=lambda: (time.sleep(.3), SRV.shutdown()), daemon=True).start()
                return

            if path == "/api/probe" and method == "POST":   # 올린 PDF를 임시로 두고 쪽 수만 알려 준다 (범위를 고르기 위해)
                data = self.body()
                with LOCK:
                    doc = pymupdf.open(stream=data, filetype="pdf")
                    if doc.needs_pass:
                        raise ValueError("암호가 걸린 PDF입니다. 암호를 해제한 파일을 올려 주세요.")
                    n = len(doc)
                    doc.close()
                UPLOAD_TMP.write_bytes(data)
                return self.send(200, {"pages": n})

            if path == "/api/upload" and method == "POST":
                name = unquote(q.get("name", "문제집.pdf"))
                if q.get("tmp") == "1":   # probe로 올려 둔 PDF에서 지정한 쪽만 가져온다
                    if not UPLOAD_TMP.exists():
                        raise ValueError("올린 파일을 찾을 수 없습니다. 다시 올려 주세요")
                    data, n, sel = slice_pdf(UPLOAD_TMP.read_bytes(), q.get("pages"), int(q.get("from", 1)), int(q.get("to", 10**6)))
                    if sel != list(range(1, n + 1)):
                        lab = pages_label(sel)
                        if len(lab) > 40:
                            lab = lab[:37] + "…"
                        name = re.sub(r"\.pdf$", "", name, flags=re.I) + f" ({lab}쪽).pdf"
                else:
                    data = self.body()
                pid = create_project(name, data)
                return self.send(200, project_info(pid))

            if path == "/api/projects" and method == "GET":
                items = []
                for d in sorted(PROJECTS.iterdir(), key=lambda x: -x.stat().st_mtime):
                    m = read_json(d / "meta.json", None)
                    if m:
                        n = len([q for q in read_json(d / "problems.json", []) if not q.get("blank")])
                        items.append({"id": d.name, "name": m["name"], "pages": m["pages"], "problems": n})
                return self.send(200, items)

            md = re.fullmatch(r"/api/p/([0-9a-f]{10})", path)
            if md and method == "DELETE":   # 최근 작업 삭제: 이 작업의 PDF 사본·잘라낸 그림·필기·설정을 지운다 (원본 PDF는 그대로)
                pid = md.group(1)
                with LOCK:
                    doc = _docs.pop(pid, None)
                    if doc is not None:
                        doc.close()
                    shutil.rmtree(pdir(pid), ignore_errors=True)
                if pdir(pid).exists():
                    raise OSError("폴더를 지우지 못했습니다. 다른 프로그램이 파일을 쓰고 있는지 확인하세요")
                return self.send(200, {"ok": True})

            m = re.fullmatch(r"/api/p/([0-9a-f]{10})/(.+)", path)
            if m:
                pid, rest = m.groups()
                d = pdir(pid)
                if rest == "info" and method == "GET":
                    return self.send(200, project_info(pid))
                if rest == "problems" and method == "PUT":
                    write_json(d / "problems.json", json.loads(self.body()))
                    return self.send(200, {"ok": True})
                if rest == "redetect" and method == "POST":
                    with LOCK:
                        ps = number_ids(detect.detect(get_doc(pid)))
                    write_json(d / "problems.json", ps)
                    write_json(d / "auto.json", ps)
                    return self.send(200, ps)
                if rest == "figs" and method == "GET":   # 문제 안의 그래프 후보
                    clip = tuple(float(v) for v in q["r"].split(","))
                    with LOCK:
                        figs = detect.find_figures(get_doc(pid)[int(q["n"])], clip)
                    return self.send(200, figs)
                if rest == "split" and method == "POST":
                    qid = json.loads(self.body())["id"]
                    probs = read_json(d / "problems.json", [])
                    idx = next((i for i, p in enumerate(probs) if p["id"] == qid), None)
                    if idx is None:
                        raise ValueError("문제를 찾을 수 없습니다")
                    if probs[idx].get("blank"):
                        return self.send(200, {"n": 0, "problems": probs})
                    with LOCK:
                        new = detect.split_subitems(get_doc(pid)[probs[idx]["page"]], probs[idx]["rect"], probs[idx]["label"])
                    if len(new) < 2:
                        return self.send(200, {"n": 0, "problems": probs})
                    used = {p["id"] for p in probs}
                    k = 1
                    for p in new:
                        while f"q{k}" in used:
                            k += 1
                        p["id"] = f"q{k}"
                        used.add(p["id"])
                    probs[idx:idx + 1] = new
                    write_json(d / "problems.json", probs)
                    return self.send(200, {"n": len(new), "problems": probs, "first": new[0]["id"]})
                if rest == "strokes":
                    f = d / "strokes.json"
                    if method == "GET":
                        return self.send(200, read_json(f, {}))
                    if method == "PUT":
                        write_json(f, json.loads(self.body()))
                        return self.send(200, {"ok": True})
                if rest == "page.png" and method == "GET":
                    png = render_png(pid, int(q["n"]), None, int(q.get("dpi", 100)))
                    return self.send(200, png, "image/png", {"Cache-Control": "max-age=3600"})
                if rest == "crop.png" and method == "GET":
                    clip = tuple(round(float(v), 1) for v in q["r"].split(","))
                    png = render_png(pid, int(q["n"]), clip, int(q.get("dpi", 220)), q.get("mask") == "1")
                    return self.send(200, png, "image/png", {"Cache-Control": "max-age=3600"})
                if rest == "handout.pdf" and method == "GET":
                    data = make_handout(pid, int(q.get("per", 2)), q.get("title", "").strip()[:80])
                    return self.send(200, data, "application/pdf")
                if rest == "slides.pdf" and method == "POST":
                    data = make_slides_pdf(json.loads(self.body())["images"])
                    return self.send(200, data, "application/pdf")
            return self.send(404, {"error": "not found"})
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            return self.send(400, {"error": str(e)})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")


def open_app_window(url):
    """Edge/Chrome를 '앱 창 모드'(주소창·탭 없음)로 연다. 못 찾으면 False -> 일반 브라우저로 연다."""
    if os.name != "nt":
        return False
    bases = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")]
    for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for base in bases:
            exe = Path(base) / rel if base else None
            if exe and exe.exists():
                try:
                    subprocess.Popen([str(exe), "--app=" + url, "--start-maximized"], close_fds=True)
                    return True
                except OSError:
                    continue
    return False


def open_ui(url):
    if "--tab" in sys.argv or not open_app_window(url):   # --tab: 일반 브라우저 탭으로 열기
        webbrowser.open(url)


class Srv(ThreadingHTTPServer):
    # Windows 에서는 SO_REUSEADDR 가 있으면 같은 포트에 서버를 여러 개 켤 수 있고, 접속은 먼저 켠 (예전 코드의) 서버로 간다.
    # 그래서 업데이트 후에도 변화가 없어 보인다 -> Windows 에서는 끈다.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def handle_error(self, request, client_address):   # 브라우저가 연결을 끊을 때 나오는 긴 오류 출력은 무시
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


SRV = None


def _ask_old_server_to_quit():
    """이미 켜져 있는 이전 서버가 있으면 끄도록 부탁한다 (새 코드를 쓰려면 서버를 다시 켜야 하므로)."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/shutdown", data=b"", method="POST", headers={"X-Quit": "1"})
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def main():
    global SRV
    for attempt in range(2):
        try:
            SRV = Srv(("127.0.0.1", PORT), H)
            break
        except OSError:
            if attempt == 0 and _ask_old_server_to_quit():
                print("이미 실행 중이던 이전 서버를 종료하고 새로 시작합니다.")
                time.sleep(1.5)
                continue
            print("\n[안내] 이미 이 프로그램이 켜져 있습니다 (포트 %d 사용 중)." % PORT)
            print("  - 작업표시줄에 최소화된 검은 창(이전 실행)을 모두 닫고 다시 실행해 주세요.")
            print("  - 코드를 업데이트(git pull)한 뒤에는 이전 창을 닫아야 새 기능이 적용됩니다.")
            sys.exit(1)
    srv = SRV
    url = f"http://localhost:{PORT}"
    print("엠클래스수학과학전문학원 실행 중 ->", url, "(끝내려면 이 창을 닫거나 Ctrl+C)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: open_ui(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
