"""pdftotext 찾기 — PATH 에 없어도(launchd 로 뜬 서버) 흔한 설치 자리에서 찾는다."""
import os
import stat

from ozl.research import capture


def _fake_exe(d):
    p = d / "pdftotext"
    p.write_text("#!/bin/sh\nexit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def test_path_first(monkeypatch, tmp_path):
    exe = _fake_exe(tmp_path)
    monkeypatch.setattr(capture.shutil, "which", lambda name: str(exe))
    monkeypatch.setattr(capture, "PDFTOTEXT_DIRS", ())
    assert capture.find_pdftotext() == str(exe)


def test_known_dir_when_path_lacks_it(monkeypatch, tmp_path):
    exe = _fake_exe(tmp_path)
    monkeypatch.setattr(capture.shutil, "which", lambda name: None)
    monkeypatch.setattr(capture, "PDFTOTEXT_DIRS", (str(tmp_path / "none"), str(tmp_path)))
    assert capture.find_pdftotext() == str(exe)


def test_none_when_nowhere(monkeypatch, tmp_path):
    monkeypatch.setattr(capture.shutil, "which", lambda name: None)
    monkeypatch.setattr(capture, "PDFTOTEXT_DIRS", (str(tmp_path),))
    assert capture.find_pdftotext() is None


def test_not_executable_is_skipped(monkeypatch, tmp_path):
    p = tmp_path / "pdftotext"
    p.write_text("x")
    os.chmod(p, 0o644)
    monkeypatch.setattr(capture.shutil, "which", lambda name: None)
    monkeypatch.setattr(capture, "PDFTOTEXT_DIRS", (str(tmp_path),))
    assert capture.find_pdftotext() is None
