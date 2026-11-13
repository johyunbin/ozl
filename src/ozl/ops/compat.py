"""옛 주소를 지금 서비스(`ozl.pulse.serve`)와 같은 몸체·같은 머리로 내준다(설계 9절 앞 여섯 줄, 10절).

`ozl.pulse.serve` 의 읽기 함수를 불러 쓰기만 한다(그 파일은 고치지 않는다). iOS 앱과 옛 대시보드가 바꿔 끼운 날에도 그대로 돈다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from ozl.pulse import serve as P

OLD_CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:"
STATIC = {"/": "index.html", "/index.html": "index.html", "/deck": "deck.html"}
TOPIC = re.compile(r"/api/topic/([0-9]{1,12})")
BRIEF = re.compile(r"/api/brief/([A-Za-z0-9-]{1,40})")
JSON_CT = "application/json; charset=utf-8"


def is_compat(path: str) -> bool:
    return path in STATIC or path in ("/api/now", "/api/health") or bool(TOPIC.fullmatch(path) or BRIEF.fullmatch(path))


def send(h, code: int, body: bytes, ctype: str) -> None:
    """옛 서버의 send 와 같은 머리."""
    h.send_response(code)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Content-Type-Options", "nosniff")
    h.send_header("Content-Security-Policy", OLD_CSP)
    h.end_headers()
    if h.command != "HEAD":
        h.wfile.write(body)
    h.status_sent = code


def send_json(h, obj, code: int = 200) -> None:
    send(h, code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), JSON_CT)


def get(h, path: str, cfg) -> None:
    """GET·HEAD. Host 는 부르는 쪽이 이미 host_ok 로 보았다."""
    now = datetime.now(timezone.utc)
    try:
        if path in STATIC:
            return send(h, 200, (P.WEB / STATIC[path]).read_bytes(), "text/html; charset=utf-8")
        m = BRIEF.fullmatch(path)
        if m:
            d = P.read_brief(m.group(1))
            if d is None:
                return send_json(h, {"error": "없는 기사"}, 404)
            return send(h, 200, json.dumps(d, ensure_ascii=False, default=str).encode("utf-8"), JSON_CT)
        if path == "/api/now":
            d = P.read_now(cfg.pulse_out)
            return send_json(h, d) if d is not None else send_json(h, {"error": "now.json 없음 — 아직 실행 전"}, 503)
        if path == "/api/health":
            return send_json(h, P.health(cfg.pulse_db, cfg.pulse_out, now))
        m = TOPIC.fullmatch(path)
        if m:
            d = P.topic_payload(int(m.group(1)), cfg.pulse_db, cfg.pulse_out, now)
            return send_json(h, d) if d is not None else send_json(h, {"error": "없는 주제"}, 404)
        return send_json(h, {"error": "없는 경로"}, 404)
    except ConnectionError:
        return None
    except Exception as e:  # noqa: BLE001 — 내부 경로·값을 응답에 싣지 않는다
        try:
            return send_json(h, {"error": type(e).__name__}, 500)
        except ConnectionError:
            return None


def host_refused(h) -> None:
    send_json(h, {"error": "허용하지 않은 Host"}, 403)


def read_only(h) -> None:
    send_json(h, {"error": "읽기 전용"}, 405)
