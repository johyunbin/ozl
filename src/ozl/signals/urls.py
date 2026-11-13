"""주소 정규화(§2-1). 같은 기사를 가리키는 주소를 한 꼴로 만든다."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DROP_PARAMS = frozenset({"fbclid", "gclid", "ocid", "oc", "mod", "traffic_source", "cmpid", "smid", "sref", "ref",
                         "rss", "rssfeed", "from", "partner", "plink", "cooper"})
DROP_PREFIX = ("utm_", "at_")
HOST_PREFIX = ("www.", "m.", "mobile.")


def canon_url(url: str | None) -> str | None:
    """추적 매개변수와 조각을 떼고, 남은 매개변수를 이름순으로 둔 주소. http(s) 가 아니면 None."""
    u = (url or "").strip()
    if not u:
        return None
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        return None
    host = p.netloc.lower()
    for pre in HOST_PREFIX:
        if host.startswith(pre):
            host = host[len(pre):]
            break
    keep = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in DROP_PARAMS and not k.lower().startswith(DROP_PREFIX)]
    keep.sort()
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(keep), ""))


def host_of(url: str | None) -> str:
    c = canon_url(url)
    return urlsplit(c).netloc if c else ""


def is_article_url(canon: str | None) -> bool:
    """같은 기사 규칙에 넣을 수 있는 주소인가: 있고, 급상승 피드가 아니고, 경로가 루트가 아니다."""
    if not canon:
        return False
    p = urlsplit(canon)
    return p.netloc != "trends.google.com" and p.path not in ("", "/")
