#!/usr/bin/env python3
"""원문 확보·글 뽑기·문구 대조·화면 그림 — 검증 기록을 사람 대조 없이 증거로 올리는 길의 앞단.

설계 정본: ~/.claude/plans/ozl_redesign_plan_20261113_014132.md 3-2절. 등급을 올리는 판단은 여기서 하지 않는다
(`cards.machine_verify` 가 저장된 사본을 다시 해시하고 다시 대조해서 정한다).

    fetch(url, dest_dir)      원문을 받아 dest_dir/source.<확장자> 에 저장. 401·403·429·로그인 벽·봇 차단 화면은 예외가 아니라 ok=False
    extract_text(path, kind)  html(script·style 제외) · pdf(pdftotext -layout, 쪽 구분 \\f 유지) · xlsx(zipfile 로 셀 문자열)
                              · hwpx(한글 문서: zipfile 로 Contents/section*.xml 의 문단 글, 표의 칸은 칸마다 한 줄) · text · json
    find_phrase(text, phrase) 공백류(연속 공백·줄바꿈·NBSP 등 유니코드 공백)만 한 칸으로 정리한 뒤 부분 문자열로 찾는다(자리 찾기)
    passage_bounds_error(...) 규칙 1 — 찾은 자리가 통째 대목(문장 · 줄 · 표의 칸)인가
    find_value(text, value)   규칙 2 — 차트 점 값이 공백으로 나뉜 낱말 하나와 글자 그대로 같은가
    snapshot(...)             capture_claim 이 만드는 미리 보기 그림(verification.image). 덱은 이것을 쓰지 않는다
    evidence_image(...)       덱의 원문 캡처 — 빌드 때 해시가 확인된 사본과 대조한 자리(match.target)에서 새로 그린다(Chrome 없이)
    refetch_check(claim)      내기 직전 원문을 새로 받아 다시 대조(기록·사본은 고치지 않는다)

문구 대조에서 하지 않는 것: 쉼표 무시·단위 환산·반올림 허용·대소문자 무시·따옴표 통일. 원문 표기 그대로여야 한다.
이 저장소에서는 그런 너그러운 규칙을 넓힐 때마다 오통과가 생겼다.

어디에서 무엇으로 막는가 — "발췌가 수량을 자른다"를 글자 종류로 가리던 방식은 막을 때마다 새 구멍과 오거부를 번갈아 냈다. 그래서 중심을 구조로 옮겼다.
  규칙 1 · 통째 대목(passage_bounds_error · cards.machine_check 가 observed 의 대조한 자리와 author·recheck.located 에 적용, fresh=False 재검사도 같다)
    시작은 글의 처음 · 탭 뒤 · 줄바꿈·쪽 구분 뒤 · 문장 끝('. ! ? 。 …' + 닫는 따옴표·괄호) 뒤 공백 뒤, 끝은 그 짝. 안쪽에서 탭을 건너면 거부
    (칸은 하나씩). 줄바꿈·쪽 구분은 건너도 되지만, 그 줄바꿈이 수량 한가운데면(앞 줄 꼬리와 뒤 줄 머리를 이어 읽은 claim_tokens 가 따로 읽은 것과
    다르거나, 앞 줄이 부호·범위 이음·여는 괄호·통화 기호로 끝나거나, 뒤 줄이 범위 이음으로 시작하거나, 앞 줄이 수량으로 끝나고 뒤 줄이
    단위(측정 단위 낱말·크기 단위·%·%p·p — 한글 낱말은 뒤가 조사·어미일 때만: '달러다.' 는 단위, '대비' 는 낱말)로 시작하면) 경계가 아니다.
    문장 끝 뒤에는 각주 표시(1) · * · † · ¹ · [1]) 0~1개를 허용한다(마침표 앞이 숫자면 받지 않는다 — '3.1)'). 발췌의 양끝이 문장·줄·칸 경계라서
    부호·범위·복합 수량·단위가 발췌 안에 남고, 덱의 숫자 검사(numbers.py)가 그 문장 문맥으로 수량을 읽는다.
  규칙 2 · 낱말 일치(find_value · spec.chart_errors) — 차트 점 값은 사본 글의 낱말 하나와 같아야 한다. 같은 칸에서 바로 앞이 부호·범위 이음만인
    낱말이거나 바로 뒤가 범위 이음만인 낱말이면 세지 않는다(탭 너머 칸의 '-' 는 빈 칸 표시라 이웃으로 보지 않는다).
  탭을 건너는 일치 거부(find_phrase) — 표의 다른 칸을 잇지 못한다('1억\t2천만원').
  find_phrase 의 수 조각 판정은 이제 자리 찾기의 보조다(규칙 1 이 주 방어선): 앞뒤 경계 글자(숫자·자릿점·부호·범위 이음·크기 단위·'%'·'(수)' —
  보이지 않는 글자 Cf 는 건너뛴다) · 전각 숫자 · 측정 단위 낱말 자르기('3달러' 의 '3달') · 범위의 앞쪽(측정 단위 뒤 '3명~5명' 포함) ·
  수량 판독부의 토큰 경계(줄바꿈·쪽 구분은 공백으로 이어 읽고 탭만 끊는다) · 줄바꿈을 건넌 일치는 앞 줄이 수량으로 끝나고(claim_tokens 의
  마지막 토큰이 줄 끝에 닿는다) 뒤 줄이 수로 시작할 때만 거부. 지운 것: 줄 끝 글자 집합(_LINE_UNITS — '최대'·'up' 의 끝 글자를 단위로 오인했다),
  쪽 구분을 탭처럼 끊던 규칙(문장이 쪽을 넘기면 못 찾았다).
알려진 한계: 공백으로 자릿수를 나눈 수('1 234')는 두 수로 읽어, 그 줄바꿈('1\n234')을 경계로 받는다. 스타일시트(class)로 숨긴 글은 잡지 못한다
(html 글 뽑기는 hidden·aria-hidden="true"·인라인 style(display:none·visibility:hidden·font-size:0)·textarea·option 만 건너뛴다).
html 글 뽑기는 글자 노드 안의 공백류(소스의 들여쓰기 탭·줄바꿈)를 공백 하나로 접는다 — 뽑은 글의 탭은 td·th 경계, 줄바꿈은 블록 요소 경계에서만 나온다.
PDF(pdftotext -layout) 표는 열이 여러 칸 공백이라 칸 하나만 따올 수 없고 줄 전체만 통째 대목이다. 같은 이유로 PDF 표의 '-'(빈 칸)는 값의 이웃으로 본다.
같은 칸 값이 문서에 여러 번 나오면 located 에 그 칸이 든 표의 행 전체(줄의 처음부터 끝까지 · 탭 포함)를 적어 자리를 가리킨다
(observed 는 칸 하나 그대로). 행 안에 같은 값이 두 번이면(두 열의 값이 같음) 자리를 하나로 정할 수 없어 기계 대조로 올리지 못한다.
차트의 칸(어느 달·어느 항목)과 값의 짝은 프로그램이 보지 못한다 — 문장 대조에서 본다.

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
KINDS = ("html", "pdf", "xlsx", "hwpx", "text", "json")
BLOCKED_STATUS = {401, 403, 429}
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_EXT = {"html": "html", "pdf": "pdf", "xlsx": "xlsx", "hwpx": "hwpx", "text": "txt", "json": "json", "other": "bin"}
_HWPX_MIME = b"application/hwp+zip"   # hwpx 는 zip 의 첫 항목 mimetype 에 이 글이 압축 없이 들어 있다
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
    if head.startswith(b"PK\x03\x04") and _HWPX_MIME in head[:512]:
        return "hwpx"
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
    """content-type 없이 바이트만으로 가를 수 있는 종류: pdf · hwpx · xlsx(그 밖의 zip) · html. 가를 수 없으면 빈 글(text·json 등)."""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "hwpx" if _HWPX_MIME in head[:512] else "xlsx"
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
    if kind in ("pdf", "xlsx", "hwpx"):
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
        """글자 노드 안의 공백류(들여쓰기 탭·줄바꿈 포함)는 브라우저처럼 보통 공백 하나로 접는다 — 뽑은 글의 탭은 td·th 경계에서만,
        줄바꿈은 블록 요소 경계에서만 나온다(원문 소스의 들여쓰기 탭을 표의 칸으로 오인하지 않게). <pre> 안은 줄바꿈을 두고 탭만 공백으로."""
        if self.hidden:
            return
        if any(t == "pre" for t, _ in self.stack):
            data = _PRE_SPACE.sub(" ", data.replace("\r\n", "\n").replace("\r", "\n"))
        else:
            data = _HTML_SPACE.sub(" ", data)
        self.out.append(data)


_HTML_SPACE = re.compile(r"[ \t\n\r\f\v\x1c\x1d\x1e\x85\u2028\u2029]+")   # 글자 노드에서 한 칸으로 접는 공백류(NBSP 등 보이는 공백은 둔다)
_PRE_SPACE = re.compile(r"[\t\f\v\x1c\x1d\x1e\x85\u2028\u2029]")


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


def _hwpx_text(path) -> str:
    """한글 문서(hwpx)의 글. 문단(p)마다 한 줄, 표의 칸 안 문단도 한 줄씩. 머리말과 각주의 글도 문서에 놓인 순서대로 들어간다.

    옛 hwp(이진 파일)는 받지 않는다. 그림으로 넣은 글은 뽑히지 않는다."""
    lines: list[str] = []

    def walk(el, buf: list[str]) -> None:
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            mine: list[str] = []
            for ch in el:
                walk(ch, mine)
            line = "".join(mine).strip()
            if line:
                lines.append(line)
            return
        if tag == "t":      # 글 조각. 안에 든 탭과 줄바꿈 표시는 공백 한 칸으로
            buf.append(el.text or "")
            for ch in el:
                buf.append(" " if ch.tag.rsplit("}", 1)[-1] in ("tab", "lineBreak") else "".join(ch.itertext()))
                buf.append(ch.tail or "")
            return
        if tag in ("tab", "lineBreak"):
            buf.append(" ")
        for ch in el:
            walk(ch, buf)

    with zipfile.ZipFile(path) as z:
        wanted = sorted((i for i in z.infolist() if re.fullmatch(r"Contents/section\d+\.xml", i.filename)),
                        key=lambda i: int(re.search(r"(\d+)", i.filename.rsplit("/", 1)[1]).group(1)))
        if any(i.file_size > MAX_XLSX_MEMBER for i in wanted) or sum(i.file_size for i in wanted) > MAX_XLSX_TOTAL:
            raise _TooBig("hwpx 압축을 풀면 크기 상한을 넘는다(항목 50MB · 합 200MB)")
        for i in wanted:
            walk(ET.fromstring(z.read(i.filename)), [])
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
        elif kind == "hwpx":
            text = _hwpx_text(p)
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
_CURRENCY = set("$€£¥₩")
# 줄을 끊는 글자. 탭은 칸 구분이라 따로 다룬다(칸은 하나씩이다). 쪽 구분(\f)도 줄바꿈처럼 다룬다 — 문장은 줄과 쪽을 넘길 수 있다
_LINE_BREAKS = "\n\r\f\v\x1c\x1d\x1e\x85  "
# 문장 끝: 마침표류 뒤에 닫는 따옴표·괄호가 0개 이상, 그 뒤에 각주 표시(1) · 12) · * · † · ‡ · ¹²³ · [1])가 0~1개.
# 각주 표시가 붙은 꼴은 마침표 앞이 숫자·자릿점이 아닐 때만(값은 3.1) 의 '.1)' 을 문장 끝으로 읽지 않게)
_FOOTNOTE = r"(?:\d{1,3}\)|\*|†|‡|[¹²³⁰⁴⁵⁶⁷⁸⁹]{1,3}|\[\d{1,3}\])"
_SENT_END = re.compile(r"(?:[.!?。…][\"'”’)\]」』]*|(?<![\d.,])[.!?。…][\"'”’)\]」』]*" + _FOOTNOTE + r")$")
_LINE_TAIL_CUT = set("-+−–—‐‑﹣－＋△▲▽▼~∼〜～(") | _CURRENCY    # 앞 줄이 이것으로 끝나면 그 줄바꿈은 수량 한가운데다
_LINE_HEAD_CUT = set("~∼〜～–—")                                 # 뒤 줄이 범위 이음으로 시작해도 그렇다
_LINE_SPAN = 40                                                   # 줄 경계 검사에서 보는 앞 줄 꼬리·뒤 줄 머리의 길이


def _unit_words() -> list[str]:
    from ozl.render import numbers as N
    return [w for w in N._UNITS.split("|") if w]


_UNIT_WORDS = _unit_words()
_TRAIL_UNIT = re.compile(r"(?: ?(?:" + "|".join(map(re.escape, sorted(_UNIT_WORDS, key=len, reverse=True))) + r"))?\)?$")
# find_phrase 가 줄바꿈을 건넌 일치를 거부하는 뒤 줄 머리: 숫자로 바로 시작(1\n234) · 부호·범위 이음+수(3%\n-5% · 3%\n~5% · 3%\n−5%).
# 여는 괄호로 시작하는 줄(매출은 3%\n(2억 원) 증가했다)은 거부하지 않는다
_NUM_HEAD = re.compile(r"[-+−–—‐‑﹣－＋△▲▽▼~∼〜～]?[$€£¥₩]?\.?\d")
# 줄 머리가 단위로 시작: 측정 단위 낱말(numbers.py 목록) · 퍼센트 · 영문 크기·비율 낱말 · 한글 크기 단위 · % · %p · p.
# 한글 낱말은 뒤가 조사·어미이거나 한글이 아닐 때만 단위로 본다('달러다.' · '원이다.' · '억 원' 은 단위, '대비' · '원래' · '조사' · '만약' 은 낱말)
_KO_END = (r"(?:다|이었다|였다|이다|입니다|이며|이고|이라|으로는|으로|로|에서|에는|에|까지|부터|보다|씩|당|어치|짜리|쯤|가량|정도"
           r"|[은는이가을를의와과도만])?(?![가-힣A-Za-z])")
_KO_UNITS = "|".join(map(re.escape, sorted([w for w in _UNIT_WORDS if not w.isascii()] + ["퍼센트포인트", "퍼센트", "포인트"], key=len, reverse=True)))
_ASCII_UNIT = ("percentage points?|percent|per cent|pct|thousand|million|billion|trillion|bn|mn|kg|km|MW|GW|TEU|bbl|barrels?|dollars?|usd|p")
_UNIT_HEAD = re.compile(r"(?:%|[십백천만억조경]+ ?(?:(?:" + _KO_UNITS + r")" + _KO_END + r"|" + _KO_END + r")|(?:" + _KO_UNITS + r")" + _KO_END
                        + r"|(?:" + _ASCII_UNIT + r")(?![A-Za-z]))", re.IGNORECASE)


def _run(text: str, pos: list[int], k: int) -> str:
    """정리한 글의 k 번째 글자(공백)가 원문에서 차지한 공백류 묶음."""
    return text[pos[k]:pos[k + 1]] if k + 1 < len(pos) else text[pos[k]:]


def _has_tab(run: str) -> bool:
    return "\t" in run


def _has_break(run: str) -> bool:
    return any(x in run for x in _LINE_BREAKS)


def _hard_at(text: str, pos: list[int], k: int) -> bool:
    """정리한 글의 k 번째 공백이 원문에서 탭(표의 칸 구분)을 건넜는가. 줄바꿈·쪽 구분은 이어 읽는다."""
    return k + 1 < len(pos) and _has_tab(text[pos[k]:pos[k + 1]])


def _line_tail(text: str, r0: int, n: int = _LINE_SPAN) -> str:
    """원문 r0 앞의 같은 줄·같은 칸 글(탭·줄바꿈에서 끊는다)의 끝 n 자 — 공백류는 한 칸으로."""
    seg = text[:r0]
    cut = max(seg.rfind(x) for x in "\t" + _LINE_BREAKS)
    return _WS.sub(" ", seg[cut + 1:]).strip()[-n:]


def _line_head(text: str, r1: int, n: int = _LINE_SPAN) -> str:
    seg = text[r1:]
    cuts = [x for x in (seg.find(c) for c in "\t" + _LINE_BREAKS) if x >= 0]
    return _WS.sub(" ", seg[:min(cuts) if cuts else len(seg)]).strip()[:n]


def _sig(t: str) -> list[tuple]:
    from ozl.render.numbers import claim_tokens
    return [(x.kind, x.canon, x.fragment) for x in claim_tokens(t)]


def _line_break_is_boundary(text: str, pos: list[int], k: int) -> bool:
    """정리한 글의 k 번째 공백(원문의 줄바꿈·쪽 구분)이 대목의 경계가 될 수 있는가 — 수량이 그 줄을 넘지 않는가.
    앞 줄 꼬리 L 과 뒤 줄 머리 R 을 이어 읽은 토큰 열이 따로 읽어 이은 것과 다르면(3\\n억원 · 1억\\n2천만원) 경계가 아니다.
    L 이 부호·범위 이음·여는 괄호·통화 기호로 끝나거나(−\\n$3) R 이 범위 이음으로 시작해도(3%\\n~5%) 경계가 아니다."""
    L, R = _line_tail(text, pos[k]), _line_head(text, pos[k + 1]) if k + 1 < len(pos) else ""
    if L and L[-1] in _LINE_TAIL_CUT:
        return False
    if R and R[0] in _LINE_HEAD_CUT:
        return False
    if L and R and _UNIT_HEAD.match(R) and _ends_with_quantity(L):
        return False   # 3\n달러 · 3억\n원 · 3\n% — 수량과 그 단위 사이의 줄바꿈(판독부의 토큰은 측정 단위를 담지 않아 따로 본다)
    if not L or not R:
        return True
    return _sig(L + " " + R) == _sig(L) + _sig(R)


def _ends_with_quantity(line: str) -> bool:
    """줄 꼬리가 수량(뒤에 측정 단위 낱말·닫는 괄호가 붙어도)으로 끝나는가 — 수량 판독부의 마지막 토큰이 줄 끝에 닿는지로 본다.
    낱말 하나(공백이 없어 판독부의 정리로 자리가 바뀌지 않는다)를, 그것만으로 수가 없으면 마지막 두 낱말을 본다('70 million' · '70 만')."""
    from ozl.render.numbers import claim_tokens
    words = _TRAIL_UNIT.sub("", line, count=1).split(" ")
    for n in (1, 2):
        if len(words) < n or not words[-1]:
            return False
        w = " ".join(words[-n:])
        toks = claim_tokens(w)
        if toks:
            e = toks[-1].end
            return e == len(w) or (n == 2 and e == len(w) - 1 and all(ch in _MAGS for ch in words[-1]))
    return False


def _joins_line_quantities(text: str, pos: list[int], k: int) -> bool:
    """줄바꿈(쪽 구분) 앞 줄이 수량으로 끝나고 뒤 줄이 수(또는 부호+수)로 시작하는가 — 두 줄의 수량을 한 문구로 이은 자리."""
    if k + 1 >= len(pos):
        return False
    return _ends_with_quantity(_line_tail(text, pos[k])) and bool(_NUM_HEAD.match(_line_head(text, pos[k + 1])))


def _ends_with_unit_word(q: str) -> bool:
    """문구가 '숫자[크기 단위·%] + 측정 단위 낱말' 로 끝나는가('3명' · '3억원' · '5 달러')."""
    m = re.search(r"\d[" + "".join(_MAGS) + r"%]*(?: ?(" + "|".join(map(re.escape, sorted(_UNIT_WORDS, key=len, reverse=True))) + r"))$", q)
    return bool(m)


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
    """norm[a:b] 에서 원문의 탭을 건넌 공백을 ' ¶ ' 로 바꾼다(표의 칸 경계에서 수량을 이어 읽지 않게).
    줄바꿈·쪽 구분은 공백으로 이어 읽는다 — PDF 의 줄바꿈이 수량 한가운데('3\\n억원' · '−\\n$3 million')일 수 있다."""
    out = []
    for k in range(a, b):
        ch = norm[k]
        if ch == " " and _hard_at(text, pos, k):
            out.append(" ¶ ")
        else:
            out.append(ch)
    return "".join(out)


def _token_cut(text: str, norm: str, pos: list[int], i: int, j: int) -> bool:
    """수량 판독부(src/ozl/render/numbers.py 의 claim_tokens)로 본 판정: 일치 구간의 경계가 수량 토큰을 자르면
    '앞+일치+뒤'를 한 번에 읽은 토큰 열과 셋을 따로 읽어 이은 토큰 열이 달라진다. 일치 구간 자체에 조각 토큰이 있어도 거부한다."""
    wb = _window_bounds(norm, i, j)
    if wb is None:
        return True
    a, b = wb
    left, mid, right = _hard(text, norm, pos, a, i), _hard(text, norm, pos, i, j), _hard(text, norm, pos, j, b)
    m = _sig(mid)
    if any(f for _, _, f in m):
        return True
    return _sig(left + mid + right) != _sig(left) + m + _sig(right)


def _cuts_number(text: str, norm: str, pos: list[int], i: int, j: int) -> bool:
    """문구가 더 긴 수(부호·자릿수·소수·범위·복합 수량·%p 가 다른 수)의 일부를 잘라 낸 자리인가. 찾은 자리를 줄이기만 한다.
    경계 글자 규칙(판독부와 무관하게, Cf 는 건너뛰고 본다) → 전각 숫자 거부 → 수량 판독부의 토큰 경계(_token_cut).
    앞 경계(문구 첫 글자가 숫자·'.'·','·크기 단위·'%'): 앞이 숫자 · 부호 표기 · 범위 이음 · 크기 단위 · '%' · '.'/','+숫자 이면 거부.
      공백 한 칸 너머가 부호 표기·범위 이음이어도 거부. '(수)' 회계식 음수도 거부.
    앞 경계(문구 첫 글자가 부호·범위 이음): 앞이 숫자·크기 단위·'%' 면 거부(범위 '3-5' 의 '-5').
    뒤 경계(문구 끝이 숫자·'.'·','·크기 단위·'%', 또는 수 뒤의 측정 단위 낱말 '3명'·'3달러'): 뒤가 숫자 · 크기 단위(숫자 뒤) · '%'(숫자 뒤) ·
      '%p' 의 p · 숫자 뒤 영문자 · '.'/','+숫자 이면 거부. 뒤(공백 한 칸 건너도, 탭은 건너지 않는다)가 범위 이음·'-' 이고 그 너머(공백 한 칸
      건너도)가 숫자·부호·통화 기호면 거부(범위의 앞쪽 — '3%~5%' 의 '3%', '3명~5명' 의 '3명').
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
            if pc == " " and not _hard_at(text, pos, k):   # 탭 너머(다른 칸의 '-' — 빈 칸 표시)는 부호가 아니다
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
    numeric_end = _isdig(last) or last in _SEPS or last in _MAGS or last == "%"
    if n < len(norm) and numeric_end:
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
    if n < len(norm) and (numeric_end or _ends_with_unit_word(norm[i:j])):
        # 범위의 앞쪽: 바로 뒤의 범위 이음('~'·'–'·'—'·'-'), 또는 탭을 건너지 않고 공백 한 칸 뒤의 '~'·'–' (공백 뒤 '-' 는 다음 수의 부호다)
        nc = norm[n]
        if nc == " ":
            m = n + 1 if not _hard_at(text, pos, n) and n + 1 < len(norm) and norm[n + 1] in "~∼〜～–" else -1
        else:
            m = n if (nc in _RANGE or nc == "-") else -1
        if m >= 0:
            m2 = m + 1
            if m2 < len(norm) and norm[m2] == " ":
                m2 += 1
            if m2 < len(norm) and (_isdig(norm[m2]) or norm[m2] in _SIGNS or norm[m2] in _CURRENCY):
                return True
    if any(ch.isdigit() for ch in norm[i:j]) and _token_cut(text, norm, pos, i, j):
        return True
    return False


def _crosses_cells(text: str, norm: str, pos: list[int], i: int, j: int, cross_tabs: bool = False) -> bool:
    """일치 구간 안의 공백이 원문에서 탭을 건넜으면 무조건(표의 다른 칸), 줄바꿈·쪽 구분을 건넜으면 앞 줄이 수량으로 끝나고 뒤 줄이
    숫자로 바로 시작하거나 부호·범위 이음+수로 시작할 때만(자릿수 잇기 1\n234 · 복합 수량 1억\n2천 · 범위 3%\n-5%) 거부한다.
    문장이 줄·쪽을 넘기는 것은 허용(여는 괄호로 시작하는 줄 '3%\n(2억 원)' 포함)."""
    for k in range(i, j):
        if norm[k] != " ":
            continue
        run = _run(text, pos, k)
        if _has_tab(run):
            if not cross_tabs:
                return True
            continue   # located(표의 행일 수 있다)를 찾을 때 — 통째 대목인지는 passage_bounds_error(allow_row=True) 가 본다
        if _has_break(run) and _joins_line_quantities(text, pos, k):
            return True
    return False


def _drops_unit_after_break(text: str, norm: str, pos: list[int], i: int, j: int) -> bool:
    """문구가 수량으로 끝나는 줄 끝에서 멈추고 다음 줄이 그 수량의 단위로 시작하는가('가격은 3\n달러다.' 의 '가격은 3' · '3억\n원' 의 '3억')."""
    if j >= len(norm) or norm[j] != " " or j + 1 >= len(pos):
        return False
    run = _run(text, pos, j)
    if _has_tab(run) or not _has_break(run):
        return False
    return _ends_with_quantity(_line_tail(text, pos[j])) and bool(_UNIT_HEAD.match(_line_head(text, pos[j + 1])))


def find_phrase(text: str, phrase: str, context: int = CONTEXT, cross_tabs: bool = False) -> dict:
    """{found, count, matches:[{offset, end, raw_offset, page, before, after}], cut}. offset·end 는 정리한 글 기준, raw_offset 은 원래 글 기준,
    page 는 원래 글의 쪽 구분(\\f)으로 센 쪽 번호(쪽 구분이 없으면 1). 공백 정리 말고는 아무것도 맞춰 주지 않는다.
    문구가 숫자로 시작하거나 끝나면 더 긴 수의 조각인 자리(부호·자릿수가 다른 수)는 찾은 것으로 치지 않고 cut 에 센다.
    통째 대목인지(규칙 1)는 여기서 보지 않는다 — passage_bounds_error 를 따로 부른다.
    cross_tabs=True 는 located(표의 행 전체일 수 있다)를 찾을 때만 — 탭을 건너는 일치를 받는다. observed 는 언제나 칸 하나(False)."""
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
        if (_cuts_number(text or "", norm, pos, i, i + len(needle)) or _crosses_cells(text or "", norm, pos, i, i + len(needle), cross_tabs)
                or _drops_unit_after_break(text or "", norm, pos, i, i + len(needle))):
            cut += 1
            start = i + 1
            continue
        raw = pos[i]
        matches.append({"offset": i, "end": i + len(needle), "raw_offset": raw, "page": bisect.bisect_left(ff, raw) + 1,
                        "before": norm[max(0, i - context):i], "after": norm[i + len(needle):i + len(needle) + context]})
        start = i + 1
    return {"found": bool(matches), "count": len(matches), "matches": matches, "cut": cut}


# ── 규칙 1: 통째 대목 ──────────────────────────────────────────────────

def _snip(norm: str, start: int, end: int, side: int = 25, mid: int = 60) -> str:
    body = norm[start:end]
    if len(body) > mid:
        body = body[:mid // 2] + " … " + body[-mid // 2:]
    return f"…{norm[max(0, start - side):start]}【{body}】{norm[end:end + side]}…"


# 줄 머리 기호 — 정부 문서의 '□ ', 'ㅇ ', '○ ', '▲ ', '※ ', '- ' 같은 항목 머리. 기호가 줄의 처음(또는 글의 처음, 문장 끝 뒤)에 있으면
# 그 뒤를 대목의 시작으로 받는다. 부호로도 읽히는 기호(- ▲ △)는 뒤가 숫자·통화 기호·소수점이면 받지 않는다(-3% · ▲ 3.2% 의 부호).
_LINE_MARKERS = "□■○●◦ㅇ▲△▶▷◆◇※-•∙·"
_SIGN_MARKERS = set("-▲△")
_MARKER_TAIL = re.compile(r"(?:^| )([" + re.escape(_LINE_MARKERS) + r"]{1,2}) ?$")


def _after_line_marker(text: str, pos: list[int], norm: str, start: int) -> bool:
    """정리한 글의 start 바로 앞이 줄 머리 기호(와 공백)인가 — 기호 앞이 글의 처음·줄바꿈(줄 경계)·탭·문장 끝 뒤 공백일 때만."""
    m = _MARKER_TAIL.search(norm[:start])
    if not m or not (norm[start - 1] == " " or norm[start - 1] in _LINE_MARKERS):
        return False
    if set(m.group(1)) & _SIGN_MARKERS and re.match(r"[\d.$€£¥₩+−-]", norm[start]):
        return False
    ms = m.start(1)
    if ms == 0:
        return True
    j = ms - 1                                       # 기호 앞 공백
    run = _run(text, pos, j)
    if _has_tab(run):
        return True
    if _has_break(run):
        return _line_break_is_boundary(text, pos, j)
    return bool(_SENT_END.search(norm[:j]))


def passage_bounds_error(text: str, start: int, end: int, allow_row: bool = False) -> str:
    """정리한 글(normalize) 기준의 자리 [start, end) 가 통째 대목(문장·줄·표의 칸)인가. 빈 글이면 통과, 아니면 사유(그 자리 앞뒤 글 포함).
    시작: 글의 처음 · 탭 바로 뒤 · 줄바꿈·쪽 구분 바로 뒤(줄 경계 검사 통과) · 문장 끝('. ! ? 。 …' + 닫는 따옴표·괄호 0개 이상) 뒤 공백 바로 뒤.
    끝:   글의 끝 · 탭 바로 앞 · 줄바꿈·쪽 구분 바로 앞(줄 경계 검사 통과) · 문장 끝 글자까지이고 그 뒤가 공백.
    안쪽: 탭을 건너면 거부(칸은 하나씩). 줄바꿈·쪽 구분은 건너도 된다(문장이 줄·쪽을 넘기는 것은 정상이다).
    줄 경계 검사(_line_break_is_boundary): 수량이 그 줄바꿈을 넘으면(3\\n억원 · −\\n$3 million · 3%~\\n5%) 그 줄바꿈은 경계가 아니다."""
    norm, pos = normalize(text or "")
    if not (0 <= start < end <= len(norm)):
        return f"자리({start}~{end})가 글 밖이다"
    if norm[start] == " " or norm[end - 1] == " ":
        return "대목이 공백으로 시작하거나 끝난다"
    where = _snip(norm, start, end)
    # allow_row=True(located 검사에서만): 줄의 처음부터 끝까지인 대목(표의 한 행 — 시작이 글의 처음이거나 줄바꿈 바로 뒤, 끝이 글의 끝이거나
    # 줄바꿈 바로 앞)은 안쪽에 탭이 있어도 받는다. 행의 양 끝에도 줄 경계 검사를 한다. 줄의 일부가 탭을 건너면 아래에서 그대로 거부한다
    if allow_row:
        head = start == 0 or (norm[start - 1] == " " and _has_break(_run(text, pos, start - 1)))
        tail = end == len(norm) or (norm[end] == " " and _has_break(_run(text, pos, end)))
        if head and tail:
            if start > 0 and not _line_break_is_boundary(text, pos, start - 1):
                return f"행이 시작하는 줄바꿈이 수량 한가운데다(앞 줄 꼬리 '{_line_tail(text, pos[start - 1], 15)}'): {where}"
            if end < len(norm) and not _line_break_is_boundary(text, pos, end):
                return f"행이 끝나는 줄바꿈이 수량 한가운데다(뒤 줄 머리 '{_line_head(text, pos[end + 1], 15)}'): {where}"
            return ""
    for k in range(start, end):
        if norm[k] == " " and _has_tab(_run(text, pos, k)):
            return f"표의 칸 경계(탭)를 건넌다 — 칸은 하나씩 따온다: {where}"
    if start > 0:
        k = start - 1
        if norm[k] != " ":
            if not _after_line_marker(text, pos, norm, start):   # 줄 머리 기호에 붙여 쓴 대목('□정부는')
                return f"낱말 중간에서 시작한다: {where}"
        else:
            run = _run(text, pos, k)
            if _has_tab(run):
                pass
            elif _has_break(run):
                if not _line_break_is_boundary(text, pos, k):
                    return f"시작하는 줄바꿈이 수량 한가운데다(앞 줄 꼬리 '{_line_tail(text, pos[k], 15)}'): {where}"
            elif not _SENT_END.search(norm[:k]) and not _after_line_marker(text, pos, norm, start):
                return f"문장 중간에서 시작한다: {where}"
    if end < len(norm):
        k = end
        if norm[k] != " ":
            return f"낱말 중간에서 끝난다: {where}"
        run = _run(text, pos, k)
        if _has_tab(run):
            pass
        elif _has_break(run):
            if not _line_break_is_boundary(text, pos, k):
                return f"끝나는 줄바꿈이 수량 한가운데다(뒤 줄 머리 '{_line_head(text, pos[k + 1], 15)}'): {where}"
        elif not _SENT_END.search(norm[start:end]):
            return f"문장 끝(마침표 등)까지 따오지 않았다: {where}"
    return ""


# ── 규칙 2: 차트 점 값 = 공백으로 나뉜 낱말 하나 ──────────────────────

_WORD_SIGN_CH = "-+−–—‐‑﹣－＋△▲▽▼"
_WORD_RANGE_CH = "-–—~∼〜～"
# 바로 앞 낱말: 부호·범위 이음으로 끝나거나(3%~ · -) 부호(+통화 기호)·여는 괄호만으로 됐으면(-$ · △ · ( ) 그 값은 세지 않는다. 통화 기호만('$')은 센다
_WORD_BEFORE = re.compile(r"(?:.*[" + re.escape(_WORD_SIGN_CH + "~∼〜～") + r"]|\(?[" + re.escape(_WORD_SIGN_CH) + r"]+[$€£¥₩]*|\()$", re.S)
_WORD_AFTER = re.compile(r"[" + re.escape(_WORD_RANGE_CH) + r"]")   # 바로 뒤 낱말이 범위 이음으로 시작(~5% · - 5)
_WORD_RX = re.compile(r"\S+")
_GAP_SAME = re.compile(r"[^\S\t" + _LINE_BREAKS + r"]+")             # 이웃으로 보는 간격: 같은 줄·같은 칸의 공백만(탭·줄바꿈 너머는 이웃이 아니다)


def find_value(text: str, notation: str) -> dict:
    """{found, count, skipped}. 사본 글을 공백류로 나눈 낱말 가운데 notation 과 글자 그대로 같은 것의 수.
    바로 앞 낱말이 부호·범위 이음으로 끝나거나(3%~ · -) 부호(+통화 기호)만으로 되어 있거나(-$ · △), 바로 뒤 낱말이 범위 이음으로 시작하면(~5%)
    그 자리는 세지 않고 skipped 에 센다. 이웃은 같은 줄·같은 칸에서 공백으로만 떨어진 낱말이다(탭·줄바꿈 너머의 '-' 는 빈 칸 표시다.
    PDF 표는 칸이 여러 칸 공백이라 가르지 못해 이웃으로 본다).
    보이지 않는 글자(Cf)가 든 표기는 찾지 않는다. 조사가 붙은 낱말('4명이다.')·부호가 붙은 낱말('-0.8%')·범위 낱말('3%~5%')은
    다른 낱말이라 찾은 것이 아니다 — 차트 자료는 표의 칸에서 온다."""
    q = str(notation or "").strip()
    out = {"found": False, "count": 0, "skipped": 0}
    if not q or any(ch.isspace() for ch in q) or any(unicodedata.category(ch) == "Cf" for ch in q):
        return out
    t = text or ""
    ms = list(_WORD_RX.finditer(t))
    for x, m in enumerate(ms):
        if m.group() != q:
            continue
        # 이웃 낱말은 같은 칸 안에서만 본다 — 탭 너머(다른 칸)의 '-' 는 빈 칸 표시·범례이지 이 값의 부호나 범위가 아니다
        before = ms[x - 1].group() if x and _GAP_SAME.fullmatch(t[ms[x - 1].end():m.start()]) else ""
        after = ms[x + 1].group() if x + 1 < len(ms) and _GAP_SAME.fullmatch(t[m.end():ms[x + 1].start()]) else ""
        if (before and _WORD_BEFORE.match(before)) or (after and _WORD_AFTER.match(after)):
            out["skipped"] += 1
            continue
        out["count"] += 1
    out["found"] = out["count"] > 0
    return out


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


PASSAGE_NOTE = "원문의 글을 옮겨 그린 것 · 화면 모양은 원문과 다름"   # 대목을 다시 그린 그림 맨 아래 한 줄(정직성 표기)
SLOT_W_IN = 4.20            # 덱 왼쪽 그림 자리 폭(in · deck.IMG_W) — 그림 글자를 슬라이드 위 pt 로 정하는 기준
PASSAGE_PT = (18, 16, 14, 13, 12, 11, 10, 9)  # 대목 글자 크기(슬라이드 위 pt) — 큰 것부터, 마지막이 최소(이보다 작으면 실패)
PASSAGE_PT_FULL = 12        # 이 크기 이하에서만 앞뒤 문맥을 모두 뺀 배치까지 해 본다(더 큰 글자에서는 문맥을 짧게라도 남긴다)
FALLBACK_FONTS = ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                  "/Library/Fonts/Arial Unicode.ttf")   # 주 글꼴에 없는 글자(・ ‧ 등)만 이 글꼴로 그린다(네모로 찍지 않는다)
NOTE_PT = 7.5
BAND_MIN_PT = 9.0           # PDF 띠를 그림 자리 폭에 맞췄을 때 대목 글자가 이보다 작으면 띠 대신 대목을 다시 그린다
BAND_MAX_RATIO = 3.0        # 띠의 가로:세로가 이를 넘으면 위아래 줄을 더 담아 세로를 확보한다(최대 BAND_CTX_LINES 줄)
BAND_CTX_LINES = (1, 2, 3)
BAND_TARGET_PX = 1400       # 띠 그림의 가로 픽셀(자리 폭 4.2in 에서 약 330dpi)
CTX_CHARS = 60              # 대목 앞뒤 문맥(한 문장 안팎)의 최대 글자 수


def focus_spans(phrase: str, focus) -> list[tuple[int, int]] | None:
    """capture_focus(구절 또는 구절 목록)가 공백을 정리한 대목 안에서 차지하는 자리들. focus 가 없으면 None(대목 전체 강조).
    한 구절이라도 대목 안에 글자 그대로(공백만 정리) 없으면 ValueError."""
    if focus in (None, "", []):
        return None
    items = [focus] if isinstance(focus, str) else list(focus)
    norm = _WS.sub(" ", phrase or "").strip()
    out: list[tuple[int, int]] = []
    for f in items:
        n = _WS.sub(" ", str(f or "")).strip()
        if not n:
            raise ValueError("capture_focus 에 빈 구절이 있다")
        st, hit = 0, False
        while True:
            i = norm.find(n, st)
            if i < 0:
                break
            out.append((i, i + len(n)))
            hit, st = True, i + 1
        if not hit:
            raise ValueError(f"capture_focus '{n}' 가 대조한 대목 안에 글자 그대로 없다")
    return sorted(set(out))


def _pdf_lines(words) -> list[list[tuple]]:
    """낱말을 세로 가운데로 묶은 줄(위에서 아래로)."""
    lines: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        cy, h = (w[1] + w[3]) / 2, max(1.0, w[3] - w[1])
        if lines:
            last = lines[-1]
            lcy = sum((x[1] + x[3]) / 2 for x in last) / len(last)
            if abs(cy - lcy) < 0.5 * h:
                last.append(w)
                continue
        lines.append([w])
    return lines


def _pdf_band_plan(pdf: pathlib.Path, page: int, phrase: str, page_nth: int, page_count: int, focus=None,
                   slot_width_in: float = SLOT_W_IN) -> dict:
    """띠의 자리(pt)와 강조할 낱말. {'mode': 'band'|'page'|'redraw', ...}.
    band = 대목이 든 줄들 + 위아래 한두 줄, 가로는 그 쪽 글 영역 전체(왼쪽·오른쪽 여백 안쪽). 띠를 그림 자리 폭에 맞췄을 때
    대목 글자가 BAND_MIN_PT 보다 작으면 redraw(대목을 다시 그린다)."""
    wb = _pdf_words(pdf, page)
    if not wb:
        return {"mode": "page", "note": "쪽 전체(낱말 자리를 얻지 못했다)"}
    pw, ph, words = wb
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
    # 그 쪽에 문구가 한 번만 나올 때만 띠·강조. 두 번 이상이면 -layout 글과 -bbox 낱말의 순서가 달라(다단 PDF) n번째끼리 맞춰도
    # 다른 자리를 강조할 수 있다 — 쪽 전체를 넣고 사유를 남긴다
    if not (page_count == 1 and len(occ) == 1 and page_nth == 0):
        if page_count > 1:
            note = f"쪽 전체(그 쪽에 문구가 {page_count}번 나와 대조한 자리를 그림에서 가리지 못한다 — 띠로 자르지도 강조하지도 않았다)"
        elif occ:
            note = f"쪽 전체(쪽의 낱말 열에서 문구가 {len(occ)}번 보여 대조한 자리와 맞추지 못했다)"
        else:
            note = "쪽 전체(쪽의 낱말 열에서 문구를 찾지 못했다)"
        return {"mode": "page", "note": note, "pw": pw, "ph": ph}
    a = occ[0]
    b = a + len(needle)
    hit = [w for w, (s0, s1) in zip(words, spans) if s0 < b and a < s1]
    marks = hit
    fs = focus_spans(needle, focus)
    if fs:
        sel = [w for w, (s0, s1) in zip(words, spans) if any(s0 < a + f1 and a + f0 < s1 for f0, f1 in fs)]
        marks = sel or hit
    lines = _pdf_lines(words)
    hit_ids = {id(w) for w in hit}
    idx = [i for i, ln in enumerate(lines) if any(id(w) in hit_ids for w in ln)]
    i0, i1 = min(idx), max(idx)
    lh = max(6.0, sorted(w[3] - w[1] for w in hit)[len(hit) // 2])    # 대목 낱말 높이의 가운데 값 ≈ 글자 크기
    x0 = min(w[0] for w in words) - 0.4 * lh                            # 쪽 글 영역 전체 폭
    x1 = max(w[2] for w in words) + 0.4 * lh
    x0, x1 = max(0.0, x0), min(pw, x1)
    bw = x1 - x0
    eff = lh * slot_width_in * 72 / bw
    if eff < BAND_MIN_PT:
        return {"mode": "redraw", "note": f"PDF 띠의 글자가 그림 자리에서 {eff:.1f}pt 로 작아 대목을 옮겨 그렸다"}
    for n in BAND_CTX_LINES:
        j0, j1 = max(0, i0 - n), min(len(lines) - 1, i1 + n)
        y0 = min(w[1] for w in lines[j0]) - 0.5 * lh
        y1 = max(w[3] for w in lines[j1]) + 0.5 * lh
        y0, y1 = max(0.0, y0), min(ph, y1)
        if bw / (y1 - y0) <= BAND_MAX_RATIO:
            break
    return {"mode": "band", "pw": pw, "ph": ph, "box": (x0, y0, x1, y1), "marks": marks, "eff_pt": eff,
            "note": "문구가 있는 줄들(쪽 글 영역 전체 폭 · 형광 표시)"}


def _pdf_band(pdf: pathlib.Path, page: int, plan: dict, out: pathlib.Path) -> dict:
    """plan(band|page)대로 쪽을 그려 자른다. band 는 띠 가로가 BAND_TARGET_PX 가 되는 해상도로 뽑는다."""
    from PIL import Image, ImageDraw
    exe = shutil.which("pdftoppm")
    if not exe:
        return {"path": "", "reason": "pdftoppm 없음"}
    dpi = 200
    if plan["mode"] == "band":
        x0, y0, x1, y1 = plan["box"]
        dpi = int(min(600, max(150, BAND_TARGET_PX * 72 / (x1 - x0))))
    with tempfile.TemporaryDirectory(prefix="ozl-page-") as td:
        prefix = pathlib.Path(td) / "pg"
        rc, err = _run_bounded([exe, "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile", str(pdf), str(prefix)], 60)
        png = prefix.with_suffix(".png")
        if rc != 0 or not png.is_file():
            return {"path": "", "reason": f"pdftoppm 실패({err})"}
        img = Image.open(png).convert("RGB")
    if plan["mode"] == "band":
        k = img.width / plan["pw"]
        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        for w in plan["marks"]:
            d.rectangle([w[0] * k - 2, w[1] * k - 2, w[2] * k + 2, w[3] * k + 2], fill=(255, 224, 102, 110), outline=(230, 150, 0, 255), width=3)
        img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
        x0, y0, x1, y1 = plan["box"]
        img = img.crop((int(x0 * k), int(y0 * k), int(x1 * k), int(y1 * k)))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return {"path": str(out), "reason": "", "view": "pdf_band" if plan["mode"] == "band" else "pdf_page", "page": page, "note": plan["note"]}


_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+")


def _tail_words(t: str, limit: int) -> str:
    """끝에서 limit 자 안쪽의 온전한 어절들(어절 가운데서 자르지 않는다)."""
    t = t.strip()
    if len(t) <= limit:
        return t
    cut = t[-limit:]
    return cut.split(" ", 1)[1] if " " in cut else ""


def _head_words(t: str, limit: int) -> str:
    t = t.strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    return cut.rsplit(" ", 1)[0] if " " in cut else ""


def _ctx_before(before: str, limit: int = CTX_CHARS) -> str:
    """대목 바로 앞의 한 문장(없으면 앞 글의 끝 조각). 길면 끝에서 limit 자."""
    b = before.strip()
    if not b:
        return ""
    parts = _SENT_SPLIT.split(b)
    return _tail_words(parts[-1], limit)


def _ctx_after(after: str, limit: int = CTX_CHARS) -> str:
    a = after.strip()
    if not a:
        return ""
    return _head_words(_SENT_SPLIT.split(a)[0], limit)


class _Fonts:
    """주 글꼴 + 없는 글자만 받는 대체 글꼴(같은 크기). f(ch) = 그 글자를 그릴 글꼴."""

    def __init__(self, font_path: str, size: int):
        from PIL import ImageFont
        from matplotlib.ft2font import FT2Font
        self.main = ImageFont.truetype(font_path, size)
        self.size = size
        self._has = FT2Font(font_path)
        self._fb = [(ImageFont.truetype(p, size), FT2Font(p)) for p in FALLBACK_FONTS if pathlib.Path(p).is_file()]
        self._cache: dict[str, object] = {}

    def f(self, ch: str):
        if ch not in self._cache:
            font = self.main
            if not ch.isspace() and self._has.get_char_index(ord(ch)) == 0:
                font = next((pf for pf, ft in self._fb if ft.get_char_index(ord(ch)) != 0), self.main)
            self._cache[ch] = font
        return self._cache[ch]


def _layout_runs(d, runs: list[tuple[str, str]], fonts: "_Fonts", x0: float, x1: float, y0: float, lh: float, y_max: float):
    """(글, 모양) 연속을 어절 단위로 줄에 놓는다. 어절이 줄보다 길 때만 글자 단위로 끊는다.
    돌려주는 것: [(x, y, 글자, 모양)] — y_max 를 넘는 글자는 놓지 않는다."""
    chars = [(ch, st) for t, st in runs for ch in t]
    tokens: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    for ch, st in chars:
        if ch == " ":
            if cur:
                tokens.append(cur)
                cur = []
            tokens.append([(ch, st)])
        else:
            cur.append((ch, st))
    if cur:
        tokens.append(cur)
    # 수량 덩어리('74조 4,319억원으로' · '7 miles' · '약 5만 명')는 한 덩어리로 놓는다 — 덱 글 배치(spec.qty_groups)와 같은 규칙
    from ozl.render.spec import _qty_joined
    merged: list[list[tuple[str, str]]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        last = "".join(c for c, _ in tok)
        while (tok[0][0] != " " and i + 2 < len(tokens) and tokens[i + 1][0][0] == " " and tokens[i + 2][0][0] != " "
               and _qty_joined(last, "".join(c for c, _ in tokens[i + 2]))):
            last = "".join(c for c, _ in tokens[i + 2])
            tok = tok + tokens[i + 1] + tokens[i + 2]
            i += 2
        merged.append(tok)
        i += 1
    tokens = merged
    width = x1 - x0
    sp = d.textlength(" ", font=fonts.main)
    x, y, placed = x0, y0, []
    for tok in tokens:
        if tok[0][0] == " ":
            if x > x0:
                placed.append((x, y, " ", tok[0][1]))
                x += sp
            continue
        w = sum(d.textlength(c, font=fonts.f(c)) for c, _ in tok)
        if x > x0 and x + w > x1:
            if placed and placed[-1][2] == " ":
                placed.pop()
            x, y = x0, y + lh
        if y + lh > y_max:
            break
        if w <= width:
            for c, st in tok:
                placed.append((x, y, c, st))
                x += d.textlength(c, font=fonts.f(c))
            continue
        for c, st in tok:            # 줄보다 긴 어절(긴 수·주소 등) — 글자 단위
            cw = d.textlength(c, font=fonts.f(c))
            if x + cw > x1 and x > x0:
                x, y = x0, y + lh
            if y + lh > y_max:
                return placed
            placed.append((x, y, c, st))
            x += cw
    return placed


def _passage_plan(before: str, phrase: str, after: str, size_px: tuple[int, int], font_path: str, focus=None,
                  slot_width_in: float = SLOT_W_IN):
    """대목 그림의 배치. 큰 글자(슬라이드 위 12pt)부터, 각 크기에서 앞뒤 문맥(한 문장 → 짧게 → 없음)을 줄여 가며 대목 전체가 들어가는 첫 배치.
    최소(9pt)에서도 안 들어가면 None. 돌려주는 것: (대목 글꼴, 표기 글꼴, 글자 배치 [(x, y, 글자, 모양)], 강조 자리, pt)."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = size_px
    d = ImageDraw.Draw(Image.new("RGB", (8, 8), "white"))
    px_pt = W / (slot_width_in * 72)
    pad = int(W * 0.05)
    note_font = ImageFont.truetype(font_path, max(8, round(NOTE_PT * px_pt)))
    y_max = H - pad - note_font.size * 1.8
    spans = focus_spans(phrase, focus)
    styles = ["mark" if spans is None or any(a <= i < b for a, b in spans) else "norm" for i in range(len(phrase))]
    pruns: list[tuple[str, str]] = []
    for ch, st in zip(phrase, styles):
        if pruns and pruns[-1][1] == st:
            pruns[-1] = (pruns[-1][0] + ch, st)
        else:
            pruns.append((ch, st))
    bf, af = _ctx_before(before), _ctx_after(after)
    options = [(bf, af), (_tail_words(bf, 28), _head_words(af, 28)), ("", _head_words(af, 28)), ("", "")]
    for pt in PASSAGE_PT:
        big = _Fonts(font_path, max(8, round(pt * px_pt)))
        lh = big.size * 1.5
        for b, a in dict.fromkeys(options if pt <= PASSAGE_PT_FULL else options[:2]):
            runs = ([("…" + b + " ", "ctx")] if b else []) + pruns + ([(" " + a + "…", "ctx")] if a else [])
            placed = _layout_runs(d, runs, big, pad, W - pad, pad, lh, y_max)
            if sum(1 for x in placed if x[3] != "ctx" and x[2] != " ") == len(phrase.replace(" ", "")):   # 대목 글자가 전부 놓였다
                return big, note_font, placed, spans, pt
    return None


def _passage_png(before: str, phrase: str, after: str, out: pathlib.Path, size_px: tuple[int, int], font_path: str,
                 check_only: bool = False, focus=None, slot_width_in: float = SLOT_W_IN) -> dict:
    """사본에서 뽑은 글의 대목을 그린 그림(원래 화면 모양 아님). 그림에는 대목 글과 맨 아래 한 줄 표기(PASSAGE_NOTE)만 둔다 —
    기록 번호·주소·받은 시각·sha256 은 부록 「시각물 출처·검증표」가 맡는다. 강조: capture_focus 가 있으면 그 구절만, 없으면 대목 전체.
    글자를 정해 둔 최소(PASSAGE_PT 끝)까지 줄여도 대목 전체가 들어가지 않으면 그리지 않고 사유를 돌려준다."""
    from PIL import Image, ImageDraw
    plan = _passage_plan(before, phrase, after, size_px, font_path, focus, slot_width_in)
    if plan is None:
        return {"path": "", "reason": f"대조한 문구({len(phrase)}자)가 가장 작은 글자 크기({PASSAGE_PT[-1]}pt)로도 그림({size_px[0]}×{size_px[1]})에 다 들어가지 않는다 — 더 짧은 대목으로 따온다",
                "view": "text_passage"}
    big, note_font, placed, spans, pt = plan
    if check_only:
        return {"path": "", "reason": "", "view": "text_passage", "fits": True, "pt": pt, "focus_spans": spans}
    W, H = size_px
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    pad = int(W * 0.05)
    for x, y, ch, st in placed:
        if st == "mark":
            d.rectangle([x, y - 2, x + d.textlength(ch, font=big.f(ch)), y + big.size * 1.25], fill=(255, 224, 102))
    for x, y, ch, st in placed:
        d.text((x, y), ch, fill=(150, 150, 150) if st == "ctx" else (17, 17, 17), font=big.f(ch))
    d.text((pad, H - pad - note_font.size * 1.2), PASSAGE_NOTE, fill=(128, 128, 128), font=note_font)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return {"path": str(out), "reason": "", "view": "text_passage", "pt": pt, "focus_spans": spans}


def evidence_image(claim_id: str, source_path, kind: str, text: str, phrase: str, offset: int, meta: dict, out_png,
                   size_px: tuple[int, int] = (1200, 1177), font_path: str = "", check_only: bool = False, focus=None,
                   slot_width_in: float = SLOT_W_IN) -> dict:
    """덱의 원문 캡처 — 해시가 확인된 사본과 대조한 자리(offset: 정리한 글 기준)에서 그때 새로 그린다. 기록의 verification.image 는 쓰지 않는다.
    pdf = 대목이 든 줄들의 띠(쪽 글 영역 전체 폭 · 위아래 한두 줄 · 형광 표시). 그 쪽에 문구가 두 번 이상이면 쪽 전체와 사유 note.
          띠를 그림 자리 폭에 맞췄을 때 글자가 BAND_MIN_PT 보다 작으면 대목을 다시 그린다(view text_passage · note 에 사유).
    · 그 밖 = 그 자리의 대목을 다시 그린 그림(원래 화면 모양 아님 · 문구 전체가 안 들어가면 실패).
    focus = capture_focus(구절 또는 목록): 그 구절만 형광(대목 밖이면 실패). meta 는 쓰지 않는다(부록이 맡는다 · 호출 모양을 지킨다).
    만들지 못하면 path 가 비고 reason 에 사유. check_only 면 그리지 않고 그릴 수 있는지만 본다."""
    out = pathlib.Path(out_png) if out_png else pathlib.Path("unused.png")
    m, all_m = _match_at(text, phrase, offset)
    if m is None:
        return {"path": "", "reason": "대조한 자리를 사본 글에서 다시 찾지 못했다", "offset": offset}
    norm_phrase = _WS.sub(" ", phrase).strip()
    try:
        focus_spans(norm_phrase, focus)
    except ValueError as e:
        return {"path": "", "reason": str(e), "offset": offset}
    try:
        note = ""
        if kind == "pdf":
            same = [x for x in all_m if x["page"] == m["page"]]
            plan = _pdf_band_plan(pathlib.Path(source_path), m["page"], phrase, same.index(m), len(same), focus, slot_width_in)
            if plan["mode"] != "redraw":
                if check_only:
                    return {"path": "", "reason": "", "offset": offset, "fits": True, "view": "pdf_band" if plan["mode"] == "band" else "pdf_page"}
                r = _pdf_band(pathlib.Path(source_path), m["page"], plan, out)
                r["offset"] = offset
                return r
            note = plan["note"]
        if not font_path:
            from ozl.render import charts as G
            font_path = G.pick_font()["path"]
        r = _passage_png(m["before"], norm_phrase, m["after"], out, size_px, font_path, check_only=check_only, focus=focus, slot_width_in=slot_width_in)
        if note:
            r["note"] = note
    except Exception as e:  # noqa: BLE001 — 그림을 못 만들면 사유를 남기고 넘어간다
        return {"path": "", "reason": f"{type(e).__name__}: {e}", "offset": offset}
    r["offset"] = offset
    return r
