#!/usr/bin/env python3
"""원문 확보·글 뽑기·문구 대조·화면 그림 — 검증 기록을 사람 대조 없이 증거로 올리는 길의 앞단.

설계 정본: ~/.claude/plans/ozl_redesign_plan_20261113_014132.md 3-2절. 등급을 올리는 판단은 여기서 하지 않는다
(`cards.machine_verify` 가 저장된 사본을 다시 해시하고 다시 대조해서 정한다).

    fetch(url, dest_dir)      원문을 받아 dest_dir/source.<확장자> 에 저장. 401·403·429·로그인 벽·봇 차단 화면은 예외가 아니라 ok=False
    extract_text(path, kind)  html(script·style 제외) · pdf(pdftotext -layout, 쪽 구분 \\f 유지) · xlsx(zipfile 로 셀 문자열) · text · json
    find_phrase(text, phrase) 공백류(연속 공백·줄바꿈·NBSP 등 유니코드 공백)만 한 칸으로 정리한 뒤 부분 문자열로 찾는다
    snapshot(...)             capture_claim 이 만드는 미리 보기 그림(verification.image). 덱은 이것을 쓰지 않는다
    evidence_image(...)       덱의 원문 캡처 — 빌드 때 해시가 확인된 사본과 대조한 자리(match.target)에서 새로 그린다(Chrome 없이)
    refetch_check(claim)      내기 직전 원문을 새로 받아 다시 대조(기록·사본은 고치지 않는다)

문구 대조에서 하지 않는 것: 쉼표 무시·단위 환산·반올림 허용·대소문자 무시·따옴표 통일. 원문 표기 그대로여야 한다.
이 저장소에서는 그런 너그러운 규칙을 넓힐 때마다 오통과가 생겼다.
더 긴 수의 조각인 자리는 찾은 것으로 치지 않는다(문구가 숫자·'.'·','로 시작하거나 끝날 때): 바로 앞뒤(보이지 않는 글자 Cf 는 건너뛴다)가
숫자(전각 포함)·소수점·자릿점이거나, 앞이 부호 표기(- − – — ‐ ‑ ﹣ － + △ ▲ ▽ ▼, 공백 한 칸 건너도 같다)이거나, '(수)' 회계식 음수인 경우.
판정은 수량 판독부(src/ozl/render/numbers.py 의 claim_tokens)의 토큰 경계가 먼저이고, 판독부가 부호로 읽지 않는 표기에만 좁은 보조 규칙을 둔다.
일치 구간 안의 '숫자 공백 숫자' 가 원문에서 탭·줄바꿈·쪽 구분을 건넜으면(표의 다른 칸) 찾은 것으로 치지 않는다.
알려진 한계: '공백 + 앞 숫자'는 조각으로 치지 않는다(표에서 뽑은 글은 열이 공백으로 나뉜다). 그래서 '1 234' 가 '1 234 567' 안에서,
'345명' 이 '인구는 12 345명이다.'(공백으로 자릿수를 나눈 표기) 안에서 찾힌다.
html 글 뽑기는 hidden·aria-hidden="true"·인라인 style(display:none·visibility:hidden·font-size:0)·textarea·option 을 건너뛴다.
스타일시트(class)로 숨긴 글은 잡지 못한다.

차단을 우회하지 않는다: User-Agent 는 하나로 고정하고 돌려쓰지 않는다. 쿠키를 넣지 않고, 재시도하지 않으며, CAPTCHA 를 다루지 않는다.
Chrome 은 임시 --user-data-dir 로 띄우고, 제한 시간이 지나면 이 모듈이 띄운 프로세스 묶음(세션)만 끝낸다(이름 단위 종료를 쓰지 않는다).
그림: PDF 는 문구가 있는 쪽. 그 밖에 문구를 찾은 것은 사본에서 뽑은 글의 해당 대목을 주소·시각·해시와 함께 그린다(원래 화면 모양이 아니다 —
headless 화면 캡처는 문구 자리로 스크롤하지 못하고 스크립트를 끄면 찍히지 않았다). 못 찾은 html 은 사본 첫 화면을 망 차단·스크립트 차단(CSP)으로 그린다.
"""
from __future__ import annotations

import bisect
import hashlib
import html.parser
import http.client
import ipaddress
import time
import unicodedata
import os
import pathlib
import re
import shutil
import signal
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

KST = timezone(timedelta(hours=9))
# 브라우저인 척하지 않는다. 자동 수집기를 막는 곳은 "열지 못함"으로 남긴다(우회하지 않는다)
USER_AGENT = "Mozilla/5.0 (compatible; document-capture/0.1)"
TIMEOUT = 30
DEADLINE = 90            # 한 건을 받는 전체 제한 시간(초) — 소켓 제한 시간은 읽기 한 번마다만 걸린다
MAX_BYTES = 30 * 1024 * 1024
MAX_XLSX_MEMBER = 50 * 1024 * 1024
MAX_XLSX_TOTAL = 200 * 1024 * 1024
MAX_PDF_TEXT = 50 * 1024 * 1024
MIN_TEXT = 80            # 공백을 뺀 글자가 이보다 적으면 "프로그램 대조 불가"(그림 PDF·스크립트로만 그리는 웹 등)
CONTEXT = 120            # 찾은 자리 앞뒤로 보여 줄 글자 수
KINDS = ("html", "pdf", "xlsx", "text", "json")
BLOCKED_STATUS = {401, 403, 429}
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_EXT = {"html": "html", "pdf": "pdf", "xlsx": "xlsx", "text": "txt", "json": "json", "other": "bin"}
# 봇 차단·로그인 벽 화면의 표지 — 푼 글의 앞부분(_WALL_SCAN 자)에서만 찾고, 보이는 본문 글이 _WALL_BODY 자(공백 제외) 이상이면 벽으로 보지 않는다
_WALL_MARKS = ("captcha", "cf-challenge", "challenge-platform", "just a moment...", "attention required", "access denied",
               "are you a robot", "verify you are human", "enable javascript and cookies", "please log in", "sign in to continue",
               "로그인이 필요", "자동입력 방지")
_WALL_SCAN = 200_000
_WALL_BODY = 2000


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 원문 확보 ─────────────────────────────────────────────────────────

def sniff_kind(head: bytes, content_type: str, url: str = "") -> str:
    ct = (content_type or "").lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04") and ("spreadsheet" in ct or url.lower().split("?")[0].endswith(".xlsx") or b"xl/" in head[:2048]):
        return "xlsx"
    if "html" in ct or re.search(rb"<!doctype html|<html", head[:2048].lower()):
        return "html"
    if "json" in ct:
        return "json"
    if ct.startswith("text/"):
        return "text"
    return "other"


def byte_kind(head: bytes) -> str:
    """content-type 없이 바이트만으로 가를 수 있는 종류: pdf · xlsx(zip) · html. 가를 수 없으면 빈 글(text·json 등)."""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    h = head[:8192]
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if h.startswith(bom):
            h = h.decode(enc, "ignore").encode("utf-8", "ignore")
    if re.search(rb"<!doctype html|<html|<head|<body|<script|<style|<meta|<div|<p[ >]|<table", h.lower()):
        return "html"
    return ""


def _charset(content_type: str) -> str:
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    return m.group(1) if m else ""


def _result(url: str, **kw) -> dict:
    base = {"ok": False, "reason": "", "url": url, "final_url": url, "status": None, "content_type": "", "charset": "",
            "bytes": 0, "sha256": "", "path": "", "kind": "", "fetched_at": now_kst()}
    base.update(kw)
    return base


def _urlopen(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


def _host(url: str) -> str:
    h = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def internal_host(url: str) -> str:
    """받지 않는 주소면 사유, 아니면 빈 글. 호스트 이름은 localhost 만 보고, IP 리터럴만 대역을 본다(DNS 조회는 하지 않는다)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "http(s) 주소가 아니다"
    h = (parts.hostname or "").lower().rstrip(".")
    if not h:
        return "호스트가 없다"
    if h == "localhost" or h.endswith(".localhost"):
        return "내부 주소(localhost)"
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return ""
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved or ip.is_multicast:
        return f"내부 주소({ip})"
    return ""


def wall_mark(data: bytes, kind: str, charset: str = "") -> str:
    """차단·로그인 벽 표지. 종류와 무관하게 푼 글(인코딩을 맞춰 푼 것)의 앞부분에서 찾는다. pdf·xlsx 는 벽 화면일 수 없어 보지 않는다.
    보이는 본문 글이 충분히 길면(공백 빼고 _WALL_BODY 자 이상) 본문 어딘가의 낱말로 막지 않는다."""
    if kind in ("pdf", "xlsx"):
        return ""
    txt = _decode(data, charset)
    head = txt[:_WALL_SCAN].lower()
    hit = next((m for m in _WALL_MARKS if m in head), "")
    if not hit:
        return ""
    body = html_text(data, charset) if kind == "html" else txt
    return "" if len(re.sub(r"\s+", "", body)) >= _WALL_BODY else hit


def fetch(url: str, dest_dir, *, timeout: int = TIMEOUT, max_bytes: int = MAX_BYTES, opener=None, deadline: float = DEADLINE) -> dict:
    """원문 한 건을 받아 dest_dir/source.<확장자> 에 저장한다. 막히면 예외 대신 ok=False 와 reason 을 돌려준다.
    opener(req, timeout) 는 시험에서 망 없이 응답을 주입할 때 쓴다(urllib 응답처럼 status·headers·geturl()·read(n) 을 갖춘 것)."""
    dest = pathlib.Path(dest_dir)
    bad = internal_host(str(url))
    if bad:
        return _result(url, reason=f"열지 못함: {bad}")
    t_end = time.monotonic() + deadline
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Language": "ko,en;q=0.8"})
    try:
        resp = (opener or _urlopen)(req, timeout)
    except urllib.error.HTTPError as e:
        why = "열지 못함: HTTP %d" % e.code + (" (권한·차단·요청 한도)" if e.code in BLOCKED_STATUS else "")
        return _result(url, reason=why, status=e.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException) as e:
        return _result(url, reason=f"열지 못함: {type(e).__name__}: {e}")
    try:
        status = getattr(resp, "status", None) or resp.getcode()
        final = resp.geturl() if hasattr(resp, "geturl") else url
        ct = resp.headers.get("Content-Type", "") if getattr(resp, "headers", None) is not None else ""
        clen = resp.headers.get("Content-Length") if getattr(resp, "headers", None) is not None else None
        if clen and str(clen).isdigit() and int(clen) > max_bytes:
            return _result(url, final_url=final, status=status, content_type=ct, reason=f"열지 못함: 크기 상한 {max_bytes} 바이트 초과({clen})")
        buf = bytearray()
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            buf += chunk
            if len(buf) > max_bytes:
                return _result(url, final_url=final, status=status, content_type=ct, reason=f"열지 못함: 크기 상한 {max_bytes} 바이트 초과")
            if time.monotonic() > t_end:
                return _result(url, final_url=final, status=status, content_type=ct, reason=f"열지 못함: 전체 제한 시간 {deadline}초 초과")
    except (TimeoutError, OSError, http.client.HTTPException) as e:
        return _result(url, reason=f"열지 못함: 읽는 중 {type(e).__name__}: {e}")
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001 — 닫기 실패는 결과에 영향이 없다
            pass
    data = bytes(buf)
    if status in BLOCKED_STATUS:
        return _result(url, final_url=final, status=status, content_type=ct, reason=f"열지 못함: HTTP {status}")
    if _host(final) != _host(url):
        return _result(url, final_url=final, status=status, content_type=ct, reason=f"열지 못함: 다른 호스트로 넘겨짐({_host(final)})")
    kind = sniff_kind(data[:4096], ct, final)
    if data:
        hit = wall_mark(data, kind, _charset(ct))
        if hit:
            return _result(url, final_url=final, status=status, content_type=ct, bytes=len(data),
                           reason=f"열지 못함: 봇 차단·로그인 벽 화면으로 보인다(표지 '{hit}')")
    if not data:
        return _result(url, final_url=final, status=status, content_type=ct, reason="열지 못함: 빈 응답")
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"source.{_EXT[kind]}"
    path.write_bytes(data)
    return _result(url, ok=True, final_url=final, status=status, content_type=ct, charset=_charset(ct), bytes=len(data),
                   sha256=hashlib.sha256(data).hexdigest(), path=str(path), kind=kind)


# ── 글 뽑기 ───────────────────────────────────────────────────────────

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr", "param"}
_HIDE_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])", re.I)


class _HTMLText(html.parser.HTMLParser):
    """화면에 보이는 글만. 요소마다 쌓아 두고, 숨김 요소 안의 글은 버린다. 스스로 닫은 꼴의 비어 있지 않은 요소(<script/>)는
    브라우저처럼 열린 것으로 친다."""
    SKIP = {"script", "style", "noscript", "template", "svg", "head", "textarea", "option", "iframe", "object"}
    CELL = {"td", "th"}   # 표의 칸 사이는 탭(칸이 한 문장처럼 붙어 수량이 이어 읽히지 않게) — 줄은 tr 의 줄바꿈
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table",
             "ul", "ol", "dd", "dt", "header", "footer", "pre", "blockquote", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.hidden = 0

    @staticmethod
    def _hides(tag, attrs) -> bool:
        a = {k.lower(): (v or "") for k, v in attrs}
        return (tag in _HTMLText.SKIP or "hidden" in a or a.get("aria-hidden", "").strip().lower() == "true"
                or bool(_HIDE_STYLE.search(a.get("style", ""))))

    def handle_starttag(self, tag, attrs):
        if tag == "body":   # 닫지 않은 head 가 본문 전체를 가리지 않게
            while any(t == "head" for t, _ in self.stack):
                self._pop()
        if tag in self.BLOCK:
            self.out.append("\n")
        elif tag in self.CELL:
            self.out.append("\t")
        if tag in _VOID:
            return
        h = self._hides(tag, attrs)
        self.stack.append((tag, h))
        self.hidden += h

    def _pop(self):
        _, h = self.stack.pop()
        self.hidden -= h

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.out.append("\n")
        elif tag in self.CELL:
            self.out.append("\t")
        if any(t == tag for t, _ in self.stack):
            while self.stack:
                t, _ = self.stack[-1]
                self._pop()
                if t == tag:
                    break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if not self.hidden:
            self.out.append(data)


def _decode(raw: bytes, charset: str = "") -> str:
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc, "replace")
    cands = [charset] if charset else []
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", raw[:4096], re.I)
    if m:
        cands.append(m.group(1).decode("ascii", "ignore"))
    cands += ["utf-8", "cp949"]
    for enc in cands:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def html_text(raw: bytes, charset: str = "") -> str:
    p = _HTMLText()
    p.feed(_decode(raw, charset))
    p.close()
    return "".join(p.out)


def _xlsx_text(path) -> str:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    lines: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        wanted = [i for i in z.infolist() if i.filename == "xl/sharedStrings.xml" or re.fullmatch(r"xl/worksheets/sheet\d+\.xml", i.filename)]
        if any(i.file_size > MAX_XLSX_MEMBER for i in wanted) or sum(i.file_size for i in wanted) > MAX_XLSX_TOTAL:
            raise _TooBig("xlsx 압축을 풀면 크기 상한을 넘는다(항목 50MB · 합 200MB)")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.iter(f"{ns}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
        sheets = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        for n in sheets:
            lines.append(f"[{n.rsplit('/', 1)[1]}]")
            root = ET.fromstring(z.read(n))
            for row in root.iter(f"{ns}row"):
                cells = []
                for c in row.iter(f"{ns}c"):
                    t = c.get("t")
                    if t == "s":
                        v = c.find(f"{ns}v")
                        idx = int(v.text) if v is not None and (v.text or "").isdigit() else -1
                        cells.append(shared[idx] if 0 <= idx < len(shared) else "")
                    elif t == "inlineStr":
                        cells.append("".join(x.text or "" for x in c.iter(f"{ns}t")))
                    else:  # 숫자·참거짓·수식 결과는 저장된 값 그대로(표시 서식은 적용하지 않는다 · 수식을 계산하지 않는다)
                        v = c.find(f"{ns}v")
                        cells.append(v.text or "" if v is not None else "")
                lines.append("\t".join(cells))
    return "\n".join(lines)


class _TooBig(Exception):
    pass


def _pdftotext(exe: str, p: pathlib.Path, limit: int = MAX_PDF_TEXT, timeout: int = 120) -> str:
    """pdftotext 출력을 임시 파일로 받되 크기 상한을 넘으면 그 프로세스만 끝내고 멈춘다."""
    with tempfile.TemporaryDirectory(prefix="ozl-pdftext-") as td:
        out = pathlib.Path(td) / "t.txt"
        proc = subprocess.Popen([exe, "-layout", "-enc", "UTF-8", str(p), str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        t_end = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                if out.exists() and out.stat().st_size > limit:
                    raise _TooBig(f"pdftotext 출력이 {limit} 바이트를 넘는다")
                if time.monotonic() > t_end:
                    raise subprocess.TimeoutExpired(exe, timeout)
                time.sleep(0.05)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"pdftotext 실패({(proc.stderr.read() if proc.stderr else b'').decode('utf-8', 'ignore')[:200]})")
        if out.stat().st_size > limit:
            raise _TooBig(f"pdftotext 출력이 {limit} 바이트를 넘는다")
        return out.read_text(encoding="utf-8", errors="replace")


def extract_text(path, kind: str, charset: str = "") -> dict:
    """{ok, text, reason}. 글이 거의 없으면 ok=False, reason 이 '프로그램 대조 불가: …' 로 시작한다."""
    p = pathlib.Path(path)
    if not p.is_file():
        return {"ok": False, "text": "", "reason": f"프로그램 대조 불가: 사본 파일 없음({p})"}
    try:
        if kind == "html":
            text = html_text(p.read_bytes(), charset)
        elif kind == "pdf":
            exe = shutil.which("pdftotext")
            if not exe:
                return {"ok": False, "text": "", "reason": "프로그램 대조 불가: pdftotext 없음"}
            text = _pdftotext(exe, p)
        elif kind == "xlsx":
            text = _xlsx_text(p)
        elif kind in ("text", "json"):
            text = _decode(p.read_bytes(), charset)
        else:
            return {"ok": False, "text": "", "reason": f"프로그램 대조 불가: 글을 뽑지 않는 종류({kind})"}
    except (zipfile.BadZipFile, ET.ParseError, subprocess.TimeoutExpired, OSError, RuntimeError, _TooBig) as e:
        return {"ok": False, "text": "", "reason": f"프로그램 대조 불가: {type(e).__name__}: {e}"}
    n = len(re.sub(r"\s+", "", text))
    if n < MIN_TEXT:
        return {"ok": False, "text": text, "reason": f"프로그램 대조 불가: 뽑힌 글이 {n}자뿐이다(그림으로 된 문서이거나 스크립트로만 그리는 화면)"}
    return {"ok": True, "text": text, "reason": ""}


# ── 문구 대조 ─────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def normalize(text: str) -> tuple[str, list[int]]:
    """공백류 연속을 한 칸으로 바꾸고 앞뒤 공백을 지운다. (정리한 글, 정리한 글의 각 글자가 원래 글에서 있던 자리)."""
    out: list[str] = []
    pos: list[int] = []
    prev_space = True   # 맨 앞 공백은 버린다
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                pos.append(i)
            prev_space = True
        else:
            out.append(ch)
            pos.append(i)
            prev_space = False
    if out and out[-1] == " ":
        out.pop()
        pos.pop()
    return "".join(out), pos


_SIGNS = set("-+−–—‐‑﹣－＋△▲▽▼")   # 수 앞에 붙는 부호 표기(하이픈·대시류·전각·증감 기호)
_RANGE = set("~∼〜～–—")             # 범위 이음(양옆이 수량인 '-' 는 _SIGNS 쪽 규칙이 받는다)
_SEPS = set(".,")
_MAGS = set("십백천만억조경")          # 한글 크기 단위(수량의 일부)


def _line_units() -> set[str]:
    """줄바꿈 앞에 오면 '수량이 끝난 자리'로 보는 글자 — 숫자 판독부(numbers.py)의 측정 단위 낱말 끝 글자 + 크기 단위 + % · p."""
    from ozl.render import numbers as N
    return {w[-1] for w in N._UNITS.split("|") if w} | _MAGS | set("%p")


_LINE_UNITS = _line_units()


def _unit_words() -> list[str]:
    from ozl.render import numbers as N
    return [w for w in N._UNITS.split("|") if w]


_UNIT_WORDS = _unit_words()


def _hard_at(text: str, pos: list[int], k: int) -> bool:
    """정리한 글의 k 번째 공백이 원문에서 탭·줄바꿈·쪽 구분을 건넜는가."""
    return k + 1 < len(pos) and any(x in "\t\n\r\f\v" for x in text[pos[k]:pos[k + 1]])


def _cuts_unit_word(norm: str, i: int, j: int, n: int) -> bool:
    """문구가 수 뒤의 측정 단위 낱말을 중간에서 잘랐는가('3달러' 의 '3달'). 마지막 숫자 뒤 글자(크기 단위·% 를 뗀 것)가
    단위 낱말의 앞부분이고 원문이 그 낱말의 나머지로 이어지면 거부한다."""
    q = norm[i:j]
    last_digit = max((x for x, ch in enumerate(q) if ch.isdigit()), default=-1)
    if last_digit < 0:
        return False
    tail = q[last_digit + 1:].lstrip("".join(_MAGS) + "%")
    if not tail or not all(ch.isalpha() for ch in tail):
        return False
    rest = norm[n:]
    return any(w.startswith(tail) and len(w) > len(tail) and rest.startswith(w[len(tail):]) for w in _UNIT_WORDS)


def _isdig(ch: str) -> bool:
    return ch.isdigit()   # 전각 숫자 등 유니코드 숫자 전부


def _prev(norm: str, i: int) -> int:
    """i 바로 앞에서 보이지 않는 글자(Cf)를 건너뛴 자리. 없으면 -1."""
    k = i - 1
    while k >= 0 and unicodedata.category(norm[k]) == "Cf":
        k -= 1
    return k


def _next(norm: str, j: int) -> int:
    k = j
    while k < len(norm) and unicodedata.category(norm[k]) == "Cf":
        k += 1
    return k


_FULLWIDTH_DIGIT = re.compile(r"[０-９]")
_TOKEN_WINDOW = 60
_WINDOW_MAX = 400


def _window_bounds(norm: str, i: int, j: int) -> tuple[int, int] | None:
    """일치 구간 앞뒤 _TOKEN_WINDOW 자쯤의 창. 양끝은 공백 자리에서 끊어 창이 수를 자르지 않게 하고, 공백이 없으면 공백을 찾을 때까지
    넓힌다(일치 구간에서 _WINDOW_MAX 자까지). 그래도 공백이 없으면 None — 그 일치는 거부한다(문맥을 버리고 판정하지 않는다)."""
    a = max(0, i - _TOKEN_WINDOW)
    if a > 0:
        sp = norm.find(" ", a, i)
        if sp < 0:
            sp = norm.rfind(" ", max(0, i - _WINDOW_MAX), a)
            if sp < 0 and i - _WINDOW_MAX > 0:
                return None
        a = sp + 1 if sp >= 0 else 0
    b = min(len(norm), j + _TOKEN_WINDOW)
    if b < len(norm):
        sp = norm.rfind(" ", j, b)
        if sp < 0:
            sp = norm.find(" ", b, min(len(norm), j + _WINDOW_MAX))
            if sp < 0 and j + _WINDOW_MAX < len(norm):
                return None
        b = sp if sp >= 0 else len(norm)
    return a, b


def _hard(text: str, norm: str, pos: list[int], a: int, b: int) -> str:
    """norm[a:b] 에서 원문의 탭·줄바꿈·쪽 구분을 건넌 공백을 ' ¶ ' 로 바꾼다(칸·줄 경계에서 수량을 이어 읽지 않게)."""
    out = []
    for k in range(a, b):
        ch = norm[k]
        if ch == " " and k + 1 < len(pos) and any(x in "\t\n\r\f\v" for x in text[pos[k]:pos[k + 1]]):
            out.append(" ¶ ")
        else:
            out.append(ch)
    return "".join(out)


def _token_cut(text: str, norm: str, pos: list[int], i: int, j: int) -> bool:
    """수량 판독부(src/ozl/render/numbers.py 의 claim_tokens)로 본 판정: 일치 구간의 경계가 수량 토큰을 자르면
    '앞+일치+뒤'를 한 번에 읽은 토큰 열과 셋을 따로 읽어 이은 토큰 열이 달라진다. 일치 구간 자체에 조각 토큰이 있어도 거부한다."""
    from ozl.render.numbers import claim_tokens
    wb = _window_bounds(norm, i, j)
    if wb is None:
        return True
    a, b = wb
    left, mid, right = _hard(text, norm, pos, a, i), _hard(text, norm, pos, i, j), _hard(text, norm, pos, j, b)

    def sig(t):
        return [(x.kind, x.canon, x.fragment) for x in claim_tokens(t)]
    m = sig(mid)
    if any(f for _, _, f in m):
        return True
    return sig(left + mid + right) != sig(left) + m + sig(right)


def _cuts_number(text: str, norm: str, pos: list[int], i: int, j: int) -> bool:
    """문구가 더 긴 수(부호·자릿수·소수·범위·복합 수량·%p 가 다른 수)의 일부를 잘라 낸 자리인가. 찾은 자리를 줄이기만 한다.
    경계 글자 규칙(판독부와 무관하게, Cf 는 건너뛰고 본다) → 전각 숫자 거부 → 수량 판독부의 토큰 경계(_token_cut).
    앞 경계(문구 첫 글자가 숫자·'.'·','·크기 단위·'%'): 앞이 숫자 · 부호 표기 · 범위 이음 · 크기 단위 · '%' · '.'/','+숫자 이면 거부.
      공백 한 칸 너머가 부호 표기·범위 이음이어도 거부. '(수)' 회계식 음수도 거부.
    앞 경계(문구 첫 글자가 부호·범위 이음): 앞이 숫자·크기 단위·'%' 면 거부(범위 '3-5' 의 '-5').
    뒤 경계(문구 끝 글자가 숫자·'.'·','·크기 단위·'%'): 뒤가 숫자 · 크기 단위(숫자 뒤) · '%'(숫자 뒤) · '%p' 의 p · 숫자 뒤 영문자 ·
      '.'/','+숫자 이면 거부. 뒤(공백 한 칸 건너도)가 범위 이음·'-' 이고 그 너머(공백 한 칸 건너도)가 숫자·부호면 거부(범위의 앞쪽).
    측정 단위 낱말(원·명·톤·달러…)은 수량에 넣지 않는다(numbers.py 와 같다): '3억원' 안의 '3억' 은 찾는다."""
    first, last = norm[i], norm[j - 1]
    k, n = _prev(norm, i), _next(norm, j)
    near = norm[i:j] + (norm[k] if k >= 0 else "") + (norm[n] if n < len(norm) else "")
    if _FULLWIDTH_DIGIT.search(near):
        return True
    if k >= 0:
        pc = norm[k]
        if _isdig(first) or first in _SEPS or first in _MAGS or first == "%":
            if _isdig(pc) or pc in _SIGNS or pc in _RANGE or pc in _MAGS or pc == "%":
                return True
            if pc in _SEPS:
                k2 = _prev(norm, k)
                if k2 >= 0 and _isdig(norm[k2]):
                    return True
            if pc == " ":
                k2 = _prev(norm, k)
                if k2 >= 0 and (norm[k2] in _SIGNS or norm[k2] in _RANGE):
                    return True
            if pc == "(" and ((_isdig(last) and n < len(norm) and norm[n] == ")") or last == ")"):
                return True   # (0.8) 회계식 음수의 괄호를 뗀 값
        elif first in _SIGNS or first in _RANGE:
            if _isdig(pc) or pc in _MAGS or pc == "%":
                return True
    if first == "(" and ")" not in norm[i:j] and n < len(norm) and norm[n] == ")":
        return True   # '(3' ← '(3)'
    if n < len(norm) and (last in _RANGE or last in _SIGNS) and _isdig(norm[n]):
        return True   # '3~' ← '3~5'
    if n < len(norm) and _cuts_unit_word(norm, i, j, n):
        return True
    if n < len(norm) and (_isdig(last) or last in _SEPS or last in _MAGS or last == "%"):
        nc = norm[n]
        if _isdig(nc):
            return True
        if nc in _MAGS and (_isdig(last) or last in _MAGS):
            return True
        if nc == "%" and (_isdig(last) or last in _MAGS):
            return True
        if last == "%" and nc in "pP":
            return True
        if _isdig(last) and nc.isascii() and nc.isalpha():
            return True
        if _isdig(last) and nc in _SEPS:
            n2 = _next(norm, n + 1)
            if n2 < len(norm) and _isdig(norm[n2]):
                return True
        # 범위의 앞쪽: 바로 뒤의 범위 이음('~'·'–'·'—'·'-'), 또는 같은 줄에서 공백 한 칸 뒤의 '~'·'–' (공백 뒤 '-' 는 다음 수의 부호다)
        if nc == " ":
            m = n + 1 if not _hard_at(text, pos, n) and n + 1 < len(norm) and norm[n + 1] in "~∼〜～–" else -1
        else:
            m = n if (nc in _RANGE or nc == "-") else -1
        if m >= 0:
            m2 = m + 1
            if m2 < len(norm) and norm[m2] == " ":
                m2 += 1
            if m2 < len(norm) and (_isdig(norm[m2]) or norm[m2] in _SIGNS):
                return True
    if any(ch.isdigit() for ch in norm[i:j]) and _token_cut(text, norm, pos, i, j):
        return True
    return False


def _crosses_cells(text: str, norm: str, pos: list[int], i: int, j: int) -> bool:
    """일치 구간 안의 공백이 원문에서 탭·쪽 구분을 건넜으면 무조건(표의 다른 칸·다른 쪽), 줄바꿈을 건넜으면 줄바꿈 앞 글자가
    숫자나 수 단위 글자이고 뒤 글자가 숫자일 때(앞 줄의 수량과 다음 줄의 수량을 이은 자리) 거부한다. 문장이 줄을 넘기는 것은 허용."""
    for k in range(i + 1, j - 1):
        if norm[k] != " ":
            continue
        run = text[pos[k]:pos[k + 1]]
        if any(x in run for x in "\t\f\v"):
            return True
        after = norm[k + 1]
        nxt_num = _isdig(after) or ((after in _SIGNS or after == "(") and k + 2 < j and _isdig(norm[k + 2]))
        if ("\n" in run or "\r" in run) and (_isdig(norm[k - 1]) or norm[k - 1] in _LINE_UNITS or norm[k - 1] == ")") and nxt_num:
            return True
    return False


def find_phrase(text: str, phrase: str, context: int = CONTEXT) -> dict:
    """{found, count, matches:[{offset, end, raw_offset, page, before, after}], cut}. offset·end 는 정리한 글 기준, raw_offset 은 원래 글 기준,
    page 는 원래 글의 쪽 구분(\\f)으로 센 쪽 번호(쪽 구분이 없으면 1). 공백 정리 말고는 아무것도 맞춰 주지 않는다.
    문구가 숫자로 시작하거나 끝나면 더 긴 수의 조각인 자리(부호·자릿수가 다른 수)는 찾은 것으로 치지 않고 cut 에 센다."""
    norm, pos = normalize(text or "")
    needle = _WS.sub(" ", str(phrase or "")).strip()
    if not needle:
        return {"found": False, "count": 0, "matches": [], "cut": 0, "reason": "찾을 문구가 비었다"}
    matches = []
    cut = 0
    start = 0
    ff = [k for k, ch in enumerate(text or "") if ch == "\f"]
    while True:
        i = norm.find(needle, start)
        if i < 0:
            break
        if _cuts_number(text or "", norm, pos, i, i + len(needle)) or _crosses_cells(text or "", norm, pos, i, i + len(needle)):
            cut += 1
            start = i + 1
            continue
        raw = pos[i]
        matches.append({"offset": i, "end": i + len(needle), "raw_offset": raw, "page": bisect.bisect_left(ff, raw) + 1,
                        "before": norm[max(0, i - context):i], "after": norm[i + len(needle):i + len(needle) + context]})
        start = i + 1
    return {"found": bool(matches), "count": len(matches), "matches": matches, "cut": cut}


def context_of(m: dict, phrase: str) -> str:
    return f"…{m['before']}【{_WS.sub(' ', phrase).strip()}】{m['after']}…"


# ── 화면 그림 ─────────────────────────────────────────────────────────

def _run_bounded(cmd: list[str], timeout: int) -> tuple[int | None, str]:
    """새 세션으로 띄워, 제한 시간이 지나면 그 세션(이 함수가 띄운 프로세스와 그 자식)만 끝낸다."""
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        _, err = proc.communicate(timeout=timeout)
        return proc.returncode, (err or b"").decode("utf-8", "ignore")[-300:]
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        return None, f"제한 시간 {timeout}초 초과 — 띄운 프로세스 묶음만 종료"
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()


def _chrome_shot(chrome: str, page_path: pathlib.Path, out: pathlib.Path, timeout: int, height: int = 1600) -> tuple[bool, str]:
    """설치된 Chrome 을 임시 프로필·망 차단(모든 호스트 해석 실패)으로 띄워 파일 한 장을 찍는다. 띄운 프로세스 묶음만 정리한다."""
    prof = tempfile.mkdtemp(prefix="ozl-capture-chrome-")
    try:
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
               f"--user-data-dir={prof}", "--host-resolver-rules=MAP * ~NOTFOUND", f"--window-size=1280,{height}",
               "--virtual-time-budget=3000", f"--screenshot={out}", page_path.resolve().as_uri()]
        rc, err = _run_bounded(cmd, timeout)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    if out.is_file() and out.stat().st_size > 0:
        return True, ""
    return False, f"Chrome 화면 캡처 실패(rc={rc} {err.strip()[-160:]})"


def _esc(x) -> str:
    return html.escape(str(x or ""))


_CSP = (b'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; '
        b'script-src \'none\'; object-src \'none\'; frame-src \'none\'">')
_REFRESH = re.compile(rb"<meta[^>]*http-equiv\s*=\s*[\"']?\s*refresh[^>]*>", re.I)


def render_copy(raw: bytes) -> bytes:
    """그림용 임시 사본: 바깥 자원·스크립트를 막는 CSP 를 맨 앞에 붙이고, CSP 가 막지 못하는 meta refresh 를 지운다(해시한 사본은 그대로)."""
    return _CSP + _REFRESH.sub(b"", raw)


def snapshot(claim_id: str, source_path, kind: str, out_png, page: int | None = None, passage: dict | None = None,
             meta: dict | None = None, timeout: int = 60, chrome: str = CHROME) -> dict:
    """{path, reason, view}. 만들지 못하면 path 는 비고 reason 에 사유가 남는다(예외를 올리지 않는다).
    pdf  : 문구가 있는 쪽을 pdftoppm 으로 그린다(view=pdf_page).
    그 밖: 문구를 찾았으면(passage={before, phrase, after}) 사본에서 뽑은 글의 해당 대목을 받은 주소·시각·해시와 함께 한 장으로 그린다
           (view=text_passage · 원래 화면 모양이 아니다). 못 찾은 html 은 저장한 사본의 첫 화면을 스크립트·망 없이 그린다(view=page_top)."""
    out = pathlib.Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(source_path)
    meta = meta or {}
    try:
        if not src.is_file():
            return {"path": "", "reason": "사본 파일 없음"}
        if kind == "pdf":
            exe = shutil.which("pdftoppm")
            if not exe:
                return {"path": "", "reason": "pdftoppm 없음"}
            pg = str(int(page or 1))
            prefix = out.with_suffix("")
            rc, err = _run_bounded([exe, "-f", pg, "-l", pg, "-r", "110", "-png", "-singlefile", str(src), str(prefix)], timeout)
            got = prefix.with_suffix(".png")
            if rc == 0 and got.is_file():
                return {"path": str(got), "reason": "", "page": int(pg), "view": "pdf_page"}
            return {"path": "", "reason": f"pdftoppm 실패({err})"}
        if not pathlib.Path(chrome).exists():
            return {"path": "", "reason": f"Chrome 없음({chrome})"}
        with tempfile.TemporaryDirectory(prefix="ozl-capture-page-") as td:
            page_file = pathlib.Path(td) / "page.html"
            if passage:
                page_file.write_text(
                    '<!doctype html><meta charset="utf-8">' + _CSP.decode() + '<style>body{font:15px/1.6 -apple-system,"Apple SD Gothic Neo",sans-serif;margin:24px;'
                    'color:#111;background:#fff}.m{color:#555;font-size:12px;word-break:break-all}.p{border:1px solid #bbb;padding:16px;'
                    'white-space:pre-wrap;word-break:break-all}mark{background:#ffe066;padding:0 2px}</style>'
                    f'<div class="m">{_esc(claim_id)} · 저장한 사본에서 뽑은 글의 대목(원래 화면 모양 아님)<br>주소 {_esc(meta.get("url"))}<br>'
                    f'받은 시각 {_esc(meta.get("fetched_at"))} · sha256 {_esc(meta.get("sha256"))}</div>'
                    f'<p class="p">…{_esc(passage.get("before"))}<mark>{_esc(passage.get("phrase"))}</mark>{_esc(passage.get("after"))}…</p>',
                    encoding="utf-8")
                ok, why = _chrome_shot(chrome, page_file, out, timeout, height=700)
                return {"path": str(out), "reason": "", "view": "text_passage"} if ok else {"path": "", "reason": why}
            if kind == "html":
                page_file.write_bytes(render_copy(src.read_bytes()))
                ok, why = _chrome_shot(chrome, page_file, out, timeout)
                return ({"path": str(out), "reason": "", "view": "page_top",
                         "note": "문구를 찾지 못해 저장한 사본의 첫 화면을 스크립트·망 없이 그렸다"} if ok else {"path": "", "reason": why})
        return {"path": "", "reason": f"{kind} 이고 문구를 찾지 못해 그릴 대목이 없다"}
    except Exception as e:  # noqa: BLE001 — 그림은 부가 증거라 실패해도 전체를 멈추지 않는다
        return {"path": "", "reason": f"{type(e).__name__}: {e}"}


# ── 기록 한 건 묶음 ───────────────────────────────────────────────────

def _rel(p, root: pathlib.Path) -> str:
    q = pathlib.Path(p).resolve()
    try:
        return str(q.relative_to(root.resolve()))
    except ValueError:
        return str(q)


def capture_claim(claim: dict, captures_root, root, cache: dict | None = None, fetcher=None, shot: bool = True) -> dict:
    """원문 확보 → 글 뽑기 → 문구 대조 → 화면 그림. 기록의 verification 에 넣을 capture·match·image 를 돌려준다.
    같은 주소는 cache 로 한 번만 받는다(두 번째 기록부터는 받은 파일을 복사한다). 경로는 root 아래면 root 기준 상대 경로로 적는다."""
    from .cards import CLAIM_ID
    cid = claim.get("claim_id")
    if not isinstance(cid, str) or not CLAIM_ID.fullmatch(cid):
        raise ValueError(f"claim_id 형식 오류 — 사본 폴더 이름으로 쓰지 않는다: {cid!r}")
    url = (claim.get("source") or {}).get("url", "")
    root = pathlib.Path(root)
    croot = pathlib.Path(captures_root)
    d = croot / cid
    if croot.resolve() not in d.resolve().parents or croot.resolve() not in (croot / f"{cid}.png").resolve().parents:
        raise ValueError(f"사본 폴더 밖에 쓰려 한다: {d}")
    cache = {} if cache is None else cache
    if url in cache and cache[url].get("ok"):
        prev = cache[url]
        d.mkdir(parents=True, exist_ok=True)
        dst = d / pathlib.Path(prev["path"]).name
        shutil.copy2(prev["path"], dst)
        res = {**prev, "path": str(dst), "reused_from": prev.get("claim_id", "")}
    elif url in cache:
        res = {**cache[url]}
    else:
        res = (fetcher or fetch)(url, d)
        res["claim_id"] = cid
        cache[url] = res
    cap = {k: res.get(k) for k in ("ok", "reason", "url", "final_url", "fetched_at", "status", "content_type", "charset", "bytes", "sha256", "kind")}
    cap["path"] = _rel(res["path"], root) if res.get("path") else ""
    cap["text_path"] = ""
    match = {"found": False, "count": 0, "offsets": [], "context": "", "reason": ""}
    image = {"path": "", "reason": ""}
    if not res.get("ok"):
        match["reason"] = res.get("reason", "열지 못함")
        image["reason"] = "원문을 열지 못했다"
        return {"capture": cap, "match": match, "image": image}
    ex = extract_text(res["path"], res["kind"], res.get("charset") or "")
    tp = d / "text.txt"
    tp.write_text(ex["text"], encoding="utf-8")
    cap["text_path"] = _rel(tp, root)
    first_page = None
    first = None
    if not ex["ok"]:
        match["reason"] = ex["reason"]
    else:
        f = find_phrase(ex["text"], claim.get("observed") or "")
        match.update(found=f["found"], count=f["count"], offsets=[m["offset"] for m in f["matches"]],
                     context=context_of(f["matches"][0], claim["observed"]) if f["found"] else "")
        if f["found"]:
            match["pages"] = sorted({m["page"] for m in f["matches"]}) if res["kind"] == "pdf" else []
            first = f["matches"][0]
            first_page = first["page"]
        else:
            match["reason"] = "observed 가 사본 글에 없다(공백만 정리해 비교)"
    if shot:
        passage = ({"before": first["before"], "phrase": _WS.sub(" ", claim["observed"]).strip(), "after": first["after"]} if match["found"] else None)
        snap = snapshot(cid, res["path"], res["kind"], croot / f"{cid}.png", page=first_page, passage=passage,
                        meta={"url": res.get("final_url") or url, "fetched_at": res.get("fetched_at"), "sha256": res.get("sha256")})
        image = {"path": _rel(snap["path"], root) if snap.get("path") else "", "reason": snap.get("reason", ""), "view": snap.get("view", "")}
        if snap.get("note"):
            image["note"] = snap["note"]
        if res["kind"] == "pdf" and snap.get("path"):
            image["page"] = snap.get("page")
    else:
        image["reason"] = "그림 생략(--no-image)"
    return {"capture": cap, "match": match, "image": image}


# ── 내기 직전의 원문 재확인 ───────────────────────────────────────────

def refetch_check(claim: dict, fetcher=None, cache: dict | None = None) -> dict:
    """source.url 을 임시 폴더에 새로 받아 글을 뽑고 observed 를 다시 찾는다. 저장한 사본과 기록 파일은 고치지 않는다(임시 폴더는 지운다).
    {claim_id, ok(받았는가), found, count, same_sha(저장한 사본과 해시가 같은가), reason}. cache 를 주면 같은 주소는 한 번만 받는다."""
    cid = claim.get("claim_id", "")
    url = (claim.get("source") or {}).get("url", "")
    cap = ((claim.get("verification") or {}).get("capture") or {})
    out = {"claim_id": cid, "ok": False, "found": False, "count": 0, "same_sha": False, "reason": ""}
    if cache is not None and url in cache:
        got = cache[url]
    else:
        with tempfile.TemporaryDirectory(prefix="ozl-refetch-") as td:
            res = (fetcher or fetch)(url, pathlib.Path(td) / "copy")
            got = {"res": {k: v for k, v in res.items() if k != "path"}, "ex": None}
            if res.get("ok"):
                got["ex"] = extract_text(res["path"], res["kind"], res.get("charset") or "")
        if cache is not None:
            cache[url] = got
    res, ex = got["res"], got["ex"]
    if not res.get("ok"):
        out["reason"] = res.get("reason") or "열지 못함"
        return out
    out["ok"] = True
    out["same_sha"] = bool(cap.get("sha256")) and res.get("sha256") == cap.get("sha256")
    if not ex["ok"]:
        out["reason"] = ex["reason"]
        return out
    f = find_phrase(ex["text"], claim.get("observed") or "")
    out.update(found=f["found"], count=f["count"])
    if not f["found"]:
        out["reason"] = "새로 받은 원문에서 observed 를 찾지 못했다"
    return out


# ── 덱에 넣는 원문 캡처(빌드 때 해시가 확인된 사본에서 새로 그린다 · Chrome 을 띄우지 않는다) ──────────

def _match_at(text: str, phrase: str, offset: int) -> tuple[dict | None, list[dict]]:
    f = find_phrase(text, phrase)
    m = next((x for x in f["matches"] if x["offset"] == offset), None)
    return m, f["matches"]


def _pdf_words(pdf: pathlib.Path, page: int) -> tuple[float, float, list[tuple[float, float, float, float, str]]] | None:
    """pdftotext -bbox 로 한 쪽의 (쪽 폭, 쪽 높이, [(xMin, yMin, xMax, yMax, 낱말)]). 못 얻으면 None."""
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="ozl-bbox-") as td:
        out = pathlib.Path(td) / "b.html"
        rc, _ = _run_bounded([exe, "-f", str(page), "-l", str(page), "-bbox", str(pdf), str(out)], 60)
        if rc != 0 or not out.is_file():
            return None
        raw = out.read_text(encoding="utf-8", errors="replace")
    pm = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', raw)
    if not pm:
        return None
    words = [(float(a), float(b), float(c), float(d), html.unescape(w))
             for a, b, c, d, w in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', raw)]
    return float(pm.group(1)), float(pm.group(2)), words


def _pdf_band(pdf: pathlib.Path, page: int, phrase: str, page_nth: int, page_count: int, out: pathlib.Path, dpi: int = 200) -> dict:
    """문구가 있는 쪽을 그리고, 낱말 자리를 얻으면 그 줄 둘레를 띠로 잘라 문구에 형광 표시를 한다. 못 얻으면 쪽 전체."""
    from PIL import Image, ImageDraw
    exe = shutil.which("pdftoppm")
    if not exe:
        return {"path": "", "reason": "pdftoppm 없음"}
    with tempfile.TemporaryDirectory(prefix="ozl-page-") as td:
        prefix = pathlib.Path(td) / "pg"
        rc, err = _run_bounded([exe, "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile", str(pdf), str(prefix)], 60)
        png = prefix.with_suffix(".png")
        if rc != 0 or not png.is_file():
            return {"path": "", "reason": f"pdftoppm 실패({err})"}
        img = Image.open(png).convert("RGB")
    note = "쪽 전체(낱말 자리를 얻지 못했다)"
    wb = _pdf_words(pdf, page)
    if wb:
        pw, ph, words = wb
        k = img.width / pw
        joined, spans = "", []
        for w in words:
            if joined:
                joined += " "
            spans.append((len(joined), len(joined) + len(w[4])))
            joined += w[4]
        needle = _WS.sub(" ", phrase).strip()
        occ, st = [], 0
        while True:
            x = joined.find(needle, st)
            if x < 0:
                break
            occ.append(x)
            st = x + 1
        if occ and len(occ) == page_count and page_nth < len(occ):
            a = occ[page_nth]
            b = a + len(needle)
            hit = [w for w, (s0, s1) in zip(words, spans) if s0 < b and a < s1]
            x0, y0 = min(w[0] for w in hit), min(w[1] for w in hit)
            x1, y1 = max(w[2] for w in hit), max(w[3] for w in hit)
            lh = max(8.0, (y1 - y0) if len(hit) == 1 else max(w[3] - w[1] for w in hit))
            over = Image.new("RGBA", img.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(over)
            for w in hit:
                d.rectangle([w[0] * k - 2, w[1] * k - 2, w[2] * k + 2, w[3] * k + 2], fill=(255, 224, 102, 110), outline=(230, 150, 0, 255), width=3)
            img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
            line = [w for w in words if y0 - 2 <= (w[1] + w[3]) / 2 <= y1 + 2]   # 문구가 있는 줄 전체가 잘리지 않게
            x0, x1 = min([x0] + [w[0] for w in line]), max([x1] + [w[2] for w in line])
            bw = max(x1 - x0 + 4 * lh, pw * 0.55)
            cx = (x0 + x1) / 2
            bx0 = min(max(0.0, cx - bw / 2), max(0.0, pw - bw))
            bh = max(y1 - y0 + 8 * lh, bw * 0.55)
            cy = (y0 + y1) / 2
            by0 = min(max(0.0, cy - bh / 2), max(0.0, ph - bh))
            img = img.crop((int(bx0 * k), int(by0 * k), int(min(pw, bx0 + bw) * k), int(min(ph, by0 + bh) * k)))
            note = "문구가 있는 줄 둘레(형광 표시)"
        elif occ:
            note = f"쪽 전체(쪽의 낱말 열에서 문구가 {len(occ)}번 보여 대조한 자리와 맞추지 못했다)"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return {"path": str(out), "reason": "", "view": "pdf_band" if note.startswith("문구") else "pdf_page", "page": page, "note": note}


def _passage_png(lines_head: list[str], before: str, phrase: str, after: str, out: pathlib.Path, size_px: tuple[int, int], font_path: str) -> dict:
    """사본에서 뽑은 글의 대목을 그린 그림(원래 화면 모양 아님). 문구에 형광 표시."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = size_px
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    pad = int(W * 0.05)
    small = ImageFont.truetype(font_path, int(W * 0.024))
    big = ImageFont.truetype(font_path, int(W * 0.040))
    y = pad
    for ln in lines_head:   # 머리 글은 한 줄씩, 넘치면 글자 단위로 줄을 나눈다
        cur = ""
        for ch in ln:
            if d.textlength(cur + ch, font=small) > W - 2 * pad:
                d.text((pad, y), cur, fill=(85, 85, 85), font=small)
                y += int(small.size * 1.4)
                cur = ""
            cur += ch
        d.text((pad, y), cur, fill=(85, 85, 85), font=small)
        y += int(small.size * 1.4)
    y += int(big.size * 0.6)
    top = y
    d.rectangle([pad // 2, top - big.size // 2, W - pad // 2, H - pad // 2], outline=(187, 187, 187), width=2)
    segs = [("…" + before, False), (phrase, True), (after + "…", False)]
    x, lh = pad, int(big.size * 1.55)
    for seg, mark in segs:
        for ch in seg:
            wch = d.textlength(ch, font=big)
            if x + wch > W - pad:
                x, y = pad, y + lh
            if y + lh > H - pad:
                break
            if mark:
                d.rectangle([x, y - 2, x + wch, y + big.size + 6], fill=(255, 224, 102))
            d.text((x, y), ch, fill=(17, 17, 17), font=big)
            x += wch
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return {"path": str(out), "reason": "", "view": "text_passage"}


def evidence_image(claim_id: str, source_path, kind: str, text: str, phrase: str, offset: int, meta: dict, out_png,
                   size_px: tuple[int, int] = (1200, 1177), font_path: str = "") -> dict:
    """덱의 원문 캡처 — 해시가 확인된 사본과 대조한 자리(offset: 정리한 글 기준)에서 그때 새로 그린다. 기록의 verification.image 는 쓰지 않는다.
    pdf = 그 자리가 있는 쪽(낱말 자리를 얻으면 줄 둘레 띠) · 그 밖 = 그 자리의 대목(원래 화면 모양 아님). 만들지 못하면 path 가 빈다."""
    out = pathlib.Path(out_png)
    m, all_m = _match_at(text, phrase, offset)
    if m is None:
        return {"path": "", "reason": "대조한 자리를 사본 글에서 다시 찾지 못했다", "offset": offset}
    try:
        if kind == "pdf":
            same = [x for x in all_m if x["page"] == m["page"]]
            r = _pdf_band(pathlib.Path(source_path), m["page"], phrase, same.index(m), len(same), out)
        else:
            if not font_path:
                from ozl.render import charts as G
                font_path = G.pick_font()["path"]
            head = [f"{claim_id} · 저장한 사본에서 뽑은 글의 대목(원래 화면 모양 아님)", f"주소 {meta.get('url', '')}",
                    f"받은 시각 {meta.get('fetched_at', '')} · sha256 {str(meta.get('sha256', ''))[:16]}…"]
            r = _passage_png(head, m["before"][-90:], _WS.sub(" ", phrase).strip(), m["after"][:90], out, size_px, font_path)
    except Exception as e:  # noqa: BLE001 — 그림을 못 만들면 사유를 남기고 넘어간다
        return {"path": "", "reason": f"{type(e).__name__}: {e}", "offset": offset}
    r["offset"] = offset
    return r
