"""수업 슬라이드 메이커 - 로컬 서버.   실행:  python server.py
브라우저가 자동으로 열린다(http://localhost:8765).  외부 인터넷 불필요.
필요 라이브러리: pymupdf  (pip install pymupdf)
"""
import base64
import hashlib
import json
import mimetypes
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pymupdf

import detect

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
PROJECTS = ROOT / "projects"
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


def project_info(pid):
    d = pdir(pid)
    meta = read_json(d / "meta.json", {})
    doc = get_doc(pid)
    return {
        "id": pid, "name": meta.get("name", pid),
        "pages": [[round(p.rect.width, 1), round(p.rect.height, 1)] for p in doc],
        "scanned": meta.get("scanned", False),
        "problems": read_json(d / "problems.json", []),
    }


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
        meta = {"name": name, "pages": len(doc), "scanned": scanned, "created": time.time()}
        write_json(d / "meta.json", meta)
        if not (d / "problems.json").exists():
            write_json(d / "problems.json", number_ids(detect.detect(doc)))
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


def make_handout(pid, per):
    """학생용 유인물: A4, 한 장에 per(1/2/4)문제, 풀이 공간 포함. 벡터 그대로 잘라 붙인다."""
    problems = [p for p in read_json(pdir(pid) / "problems.json", []) if p.get("on", True)]
    W, H, M = 595.0, 842.0, 34.0
    cols, rows = {1: (1, 1), 2: (1, 2), 4: (2, 2)}[per]
    cw, ch = (W - 2 * M) / cols, (H - 2 * M) / rows
    out = pymupdf.open()
    with LOCK:
        src = get_doc(pid)
        for i, p in enumerate(problems):
            k = i % per
            if k == 0:
                page = out.new_page(width=W, height=H)
            r, c = divmod(k, cols)
            x0, y0 = M + c * cw, M + r * ch
            clip = pymupdf.Rect(*p["rect"])
            s = min((cw - 14) / clip.width, (ch * 0.62) / clip.height, 1.5)
            dst = pymupdf.Rect(x0 + 4, y0 + 4, x0 + 4 + clip.width * s, y0 + 4 + clip.height * s)
            page.show_pdf_page(dst, src, p["page"], clip=clip)
            for ar in detect.answer_rects(src[p["page"]], clip):   # 정답 글자 가리기
                page.draw_rect(pymupdf.Rect(dst.x0 + (ar.x0 - clip.x0) * s, dst.y0 + (ar.y0 - clip.y0) * s,
                                            dst.x0 + (ar.x1 - clip.x0) * s, dst.y0 + (ar.y1 - clip.y0) * s),
                               color=None, fill=(1, 1, 1))
            if per > 1 and (c < cols - 1):
                page.draw_line((x0 + cw, y0 + 4), (x0 + cw, y0 + ch - 4), color=(.8, .8, .8), width=.5, dashes="[3 3] 0")
            if per > 1 and r < rows - 1:
                page.draw_line((x0 + 4, y0 + ch), (x0 + cw - 4, y0 + ch), color=(.8, .8, .8), width=.5, dashes="[3 3] 0")
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

            if path == "/api/upload" and method == "POST":
                pid = create_project(unquote(q.get("name", "문제집.pdf")), self.body())
                return self.send(200, project_info(pid))

            if path == "/api/projects" and method == "GET":
                items = []
                for d in sorted(PROJECTS.iterdir(), key=lambda x: -x.stat().st_mtime):
                    m = read_json(d / "meta.json", None)
                    if m:
                        n = len(read_json(d / "problems.json", []))
                        items.append({"id": d.name, "name": m["name"], "pages": m["pages"], "problems": n})
                return self.send(200, items)

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
                    data = make_handout(pid, int(q.get("per", 2)))
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


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"
    print("수업 슬라이드 메이커 실행 중 ->", url, "(끝내려면 이 창에서 Ctrl+C)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
