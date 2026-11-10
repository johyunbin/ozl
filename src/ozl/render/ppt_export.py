#!/usr/bin/env python3
"""파워포인트(맥)로 pptx → PDF 내보내기 — 맑은 고딕·줄 간격을 원본과 같은 엔진으로 렌더하는 검증 경로.

LibreOffice 는 ① 오피스 번들 폰트(맑은 고딕)를 못 보고 ② 배수 줄 간격을 폰트 줄 높이(1.33em) 기준으로 계산해 파워포인트(1.2em 기준)와 줄 위치가 달라진다.
맥용 오피스는 샌드박스라 임의 경로를 열면 '파일 액세스 부여' 대화상자에 걸린다 → 앱 컨테이너의 Documents 아래로 복사해 열고, PDF 도 그 안에 저장한 뒤 되가져온다.

    python -m ozl.render.ppt_export <pptx>   # 같은 폴더에 <이름>.pdf
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import time

SANDBOX = pathlib.Path.home() / "Library/Containers/com.microsoft.Powerpoint/Data/Documents/ozl_export"

SCRIPT = '''
tell application "Microsoft PowerPoint"
  open POSIX file "{src}"
  delay 2
  save active presentation in (POSIX file "{dst}") as save as PDF
  delay 2
  close active presentation saving no
end tell
'''


def export_pdf(pptx: pathlib.Path, timeout: int = 120) -> pathlib.Path | None:
    if not pathlib.Path("/Applications/Microsoft PowerPoint.app").exists():
        print("Microsoft PowerPoint 미설치 — LibreOffice 경로(deck.to_pdf_png)를 쓴다", file=sys.stderr)
        return None
    SANDBOX.mkdir(parents=True, exist_ok=True)
    src, dst = SANDBOX / "in.pptx", SANDBOX / "out.pdf"
    dst.unlink(missing_ok=True)
    shutil.copyfile(pptx, src)
    r = subprocess.run(["osascript", "-e", SCRIPT.format(src=src, dst=dst)], capture_output=True, text=True, timeout=timeout)
    for _ in range(20):  # 저장이 비동기로 끝나는 경우 대기
        if dst.exists() and dst.stat().st_size > 0:
            break
        time.sleep(0.5)
    if not dst.exists():
        print("PDF 내보내기 실패:", (r.stderr or r.stdout)[-300:], file=sys.stderr)
        return None
    out = pptx.with_suffix(".pdf")
    shutil.copyfile(dst, out)
    src.unlink(missing_ok=True)
    dst.unlink(missing_ok=True)
    return out


if __name__ == "__main__":
    p = export_pdf(pathlib.Path(sys.argv[1]).resolve())
    print(p)
    sys.exit(0 if p else 1)
