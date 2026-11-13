"""브라우저가 실제로 보내는 머리에 맞는지 — 직접 Origin 을 적는 시험이 못 잡는 것.

브라우저는 문서의 리퍼러 정책이 no-referrer 이면 폼 제출(POST)의 Origin 을 `null` 로 보낸다(Fetch 표준).
쓰기 검사는 Origin 이 `null` 이면 막으므로, 운영 화면이 no-referrer 를 내보내면 브라우저에서는 어떤 단추도 눌리지 않는다.
"""
import re

from ozl.ops import server, templates


def test_ops_pages_do_not_send_no_referrer():
    assert server.REFERRER == "same-origin"
    src = open(server.__file__, encoding="utf-8").read() + open(templates.__file__, encoding="utf-8").read()
    assert "no-referrer" not in re.sub(r"#.*", "", src)          # 주석 밖에는 없어야 한다


def test_null_origin_is_still_refused():
    """정책을 바꿨다고 `Origin: null` 을 받아 주는 것은 아니다."""
    from ozl.ops import auth

    class H(dict):
        def get(self, k, d=None):
            return super().get(k, d)

    import io
    import pytest
    h = H({"Host": "127.0.0.1:8765", "Origin": "null", "Content-Length": "0", "Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(auth.Reject) as e:
        auth.check_write(h, io.BytesIO(b""), token_path=__import__("pathlib").Path("/nonexistent"), allow={"127.0.0.1:8765"})
    assert e.value.code == 403
