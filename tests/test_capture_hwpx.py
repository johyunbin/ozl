"""한글 문서(hwpx) 글 뽑기 — 지어낸 문서로만 시험한다."""
import zipfile

from ozl.research import capture as K

NS = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
SECTION = f"""<?xml version="1.0" encoding="UTF-8"?>
<hs:sec {NS}>
  <hp:p><hp:run><hp:t>한빛시는 시내버스 요금을 조정한다고 밝혔다.</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:t>조정 폭은 </hp:t></hp:run><hp:run><hp:t>성인 기준 사백 원이다.</hp:t></hp:run></hp:p>
  <hp:p><hp:run><hp:tbl><hp:tr>
    <hp:tc><hp:subList><hp:p><hp:run><hp:t>구분</hp:t></hp:run></hp:p></hp:subList></hp:tc>
    <hp:tc><hp:subList><hp:p><hp:run><hp:t>지어낸 값 하나</hp:t></hp:run></hp:p></hp:subList></hp:tc>
  </hp:tr></hp:tbl></hp:run></hp:p>
  <hp:p><hp:run><hp:t>첫 줄<hp:lineBreak/>둘째 줄</hp:t></hp:run></hp:p>
</hs:sec>"""


def make_hwpx(p, sections=(SECTION,)):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")   # 첫 항목, 압축 없음
        for i, s in enumerate(sections):
            z.writestr(f"Contents/section{i}.xml", s, compress_type=zipfile.ZIP_DEFLATED)
    return p


def test_sniff_and_byte_kind(tmp_path):
    p = make_hwpx(tmp_path / "a.hwpx")
    head = p.read_bytes()[:4096]
    assert K.sniff_kind(head, "application/octet-stream", "https://example.org/down.do?seq=1") == "hwpx"
    assert K.byte_kind(head) == "hwpx"
    assert "hwpx" in K.KINDS


def test_xlsx_zip_is_still_xlsx(tmp_path):
    p = tmp_path / "b.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    head = p.read_bytes()[:4096]
    assert K.sniff_kind(head, "", "https://example.org/b.xlsx") == "xlsx" and K.byte_kind(head) == "xlsx"


def test_text_lines_paragraphs_and_cells(tmp_path):
    p = make_hwpx(tmp_path / "a.hwpx", (SECTION, SECTION.replace("한빛시는", "누리시는")))
    r = K.extract_text(p, "hwpx")
    assert r["ok"], r["reason"]
    lines = r["text"].split("\n")
    assert lines[0] == "한빛시는 시내버스 요금을 조정한다고 밝혔다."
    assert lines[1] == "조정 폭은 성인 기준 사백 원이다."          # 한 문단의 조각은 이어 붙는다
    assert lines[2:4] == ["구분", "지어낸 값 하나"]                # 표의 칸은 칸마다 한 줄
    assert lines[4] == "첫 줄 둘째 줄"                              # 줄바꿈 표시는 공백으로
    assert lines[5].startswith("누리시는")                          # 둘째 구역이 뒤에 온다


def test_broken_file_is_refused_not_crash(tmp_path):
    p = tmp_path / "c.hwpx"
    p.write_bytes(b"PK\x03\x04 not a zip")
    r = K.extract_text(p, "hwpx")
    assert not r["ok"] and r["reason"].startswith("프로그램 대조 불가")
