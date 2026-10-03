"""A sheet (PDF, image or link) in, a new songs/<slug>/ out."""

import functools
import http.server
import shutil
import threading
import tomllib
from pathlib import Path

import pytest

from pianist.sheet import (
    SheetError,
    direct,
    fetch,
    is_sheet,
    new_song,
    pages,
    title_from,
)

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "songs" / "amazing-grace" / "input" / "sheet.pdf"
SAMPLE = tomllib.loads((ROOT / "songs" / "amazing-grace" / "input" / "song.toml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("arg, sheet", [("songs/x", False), ("a.PDF", True), ("b.jpg", True), ("c.jpeg", True), ("d.png", True), ("https://x.org/y.pdf", True), ("http://x.org/y", True)])
def test_is_sheet(arg, sheet):
    assert is_sheet(arg) == sheet


@pytest.mark.parametrize("source, title", [("AmazingGrace.pdf", "Amazing Grace"), ("http://x.org/a/Dem_Thanh-Vo-Cung.png", "Dem Thanh Vo Cung"), ("scan 01.jpg", "scan 01")])
def test_title_from_file_name(source, title):
    assert title_from(source) == title


class PickyHandler(http.server.SimpleHTTPRequestHandler):
    """Like many sheet-music sites: refuses Python's default User-Agent, serves files without telling their type."""

    def do_GET(self):
        if "Python-urllib" in self.headers.get("User-Agent", ""):
            self.send_error(403)
            return
        if self.path.startswith(("/any/", "/cut", "/uc")):  # any name serves the sheet; /cut ends the connection halfway
            body = SHEET.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            if self.path.startswith("/uc"):  # like Google Drive: the name is only in the headers, as raw UTF-8
                name = "Đêm_Thánh.pdf" if "utf8" in self.path else "Cao_Cung_Len.pdf"
                self.send_header("Content-Disposition", f'attachment; filename="{name}"'.encode().decode("latin-1"))
            self.end_headers()
            self.wfile.write(body[: len(body) // 2] if self.path == "/cut" else body)
            return
        super().do_GET()

    def guess_type(self, path):
        return "application/octet-stream"


@pytest.fixture
def server(tmp_path):
    (tmp_path / "notes.txt").write_text("not music")
    shutil.copy(SHEET, tmp_path / "AmazingGrace.pdf")
    shutil.copy(SHEET, tmp_path / "download")  # no extension: the bytes say it is a PDF
    handler = functools.partial(PickyHandler, directory=str(tmp_path))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_fetch_downloads_a_linked_sheet(server, tmp_path):
    got = fetch(f"{server}/AmazingGrace.pdf", tmp_path / "work")
    assert got.read_bytes() == SHEET.read_bytes() and got.suffix == ".pdf"
    assert fetch(f"{server}/download", tmp_path / "work2").suffix == ".pdf"


@pytest.mark.parametrize(
    "link, url",
    [
        ("https://drive.google.com/file/d/1nc-pG_9/view?pli=1", "https://drive.google.com/uc?export=download&id=1nc-pG_9"),
        ("https://github.com/o/r/blob/master/A/Kiss%20The%20Rain.pdf", "https://github.com/o/r/raw/master/A/Kiss%20The%20Rain.pdf"),
        ("https://drive.google.com/open?id=1nc", "https://drive.google.com/uc?export=download&id=1nc"),
        ("https://docs.google.com/file/d/1nc/edit", "https://drive.google.com/uc?export=download&id=1nc"),
        ("https://example.com/blob/a.pdf", "https://example.com/blob/a.pdf"),
    ],
)
def test_share_links_lead_to_the_file(link, url):
    assert direct(link) == url


def test_fetch_names_the_sheet_as_the_server_does(server, tmp_path):
    assert fetch(f"{server}/uc?export=download&id=1", tmp_path / "work").name == "Cao Cung Len.pdf"
    assert fetch(f"{server}/uc?utf8", tmp_path / "work2").name == "Đêm Thánh.pdf"


def test_fetch_explains_a_link_that_opens_a_web_page(server, tmp_path):
    (tmp_path / "view.html").write_text("<!doctype html><title>Sign in</title>")
    with pytest.raises(SheetError, match="opened a web page"):
        fetch(f"{server}/view.html", tmp_path / "work")


@pytest.mark.parametrize("path", ["/any/Amazing Grace.pdf", "/any/Đêm Thánh.pdf", "/any/" + "x" * 300 + ".pdf", "/any/a%00b.pdf"])
def test_fetch_takes_links_as_pasted(server, tmp_path, path):
    """Spaces and letters straight from a browser, file names too long for the disk, encoded control characters."""
    assert fetch(server + path, tmp_path / "work").read_bytes() == SHEET.read_bytes()


def test_fetch_reports_a_download_that_was_cut_off(server, tmp_path):
    with pytest.raises(SheetError, match="could not download|was cut off"):
        fetch(f"{server}/cut", tmp_path / "work")


@pytest.mark.skipif(not shutil.which("pdfinfo"), reason="needs pdfinfo (nix develop)")
def test_a_whole_book_is_refused_before_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr("pianist.sheet.MAX_PAGES", 0)
    monkeypatch.setattr("pianist.sheet.read_omr", lambda *a: pytest.fail("read a book"))
    with pytest.raises(SheetError, match="sheet.pdf has 1 pages; give one song"):
        new_song(str(SHEET), tmp_path / "songs", "omr")


def test_fetch_rejects_what_is_not_a_sheet(server, tmp_path):
    with pytest.raises(SheetError, match="not a PDF or an image"):
        fetch(f"{server}/notes.txt", tmp_path / "work")
    with pytest.raises(SheetError, match="could not download"):
        fetch(f"{server}/missing.pdf", tmp_path / "work")
    with pytest.raises(SheetError, match="no such file"):
        fetch(str(tmp_path / "nope.pdf"), tmp_path / "work")


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="needs pdftoppm (nix develop)")
def test_pages_rasterizes_each_pdf_page(tmp_path):
    assert [p.name for p in pages(SHEET, tmp_path)] == ["page-1.png"]
    assert pages(tmp_path / "page-1.png", tmp_path) == [tmp_path / "page-1.png"]  # an image is already a page


@pytest.mark.skipif(not shutil.which("homr"), reason="needs homr (nix develop)")
def test_new_song_from_a_pdf_with_optical_music_recognition(tmp_path):
    shutil.copy(SHEET, tmp_path / "AmazingGrace.pdf")
    song_dir, notes = new_song(str(tmp_path / "AmazingGrace.pdf"), tmp_path / "songs", "omr")
    assert song_dir == tmp_path / "songs" / "amazing-grace"
    assert (song_dir / "input" / "sheet.pdf").read_bytes() == SHEET.read_bytes()
    data = tomllib.loads((song_dir / "input" / "song.toml").read_text(encoding="utf-8"))
    assert data["parts"]["song"]["melody"] == [bar.rstrip("-") for bar in SAMPLE["parts"]["verse"]["melody"]]  # no ties from OMR
    assert any("comes from the file name" in n for n in notes)
    with pytest.raises(SheetError, match="this sheet was already read into"):
        new_song(str(tmp_path / "AmazingGrace.pdf"), tmp_path / "songs", "omr")


def test_a_sheet_read_before_is_refused_before_any_reading(tmp_path, monkeypatch):
    (tmp_path / "songs" / "amazing-grace" / "input").mkdir(parents=True)
    shutil.copy(SHEET, tmp_path / "songs" / "amazing-grace" / "input" / "sheet.pdf")  # the same sheet, already read
    shutil.copy(SHEET, tmp_path / "AmazingGrace.pdf")

    def must_not_read(*args, **kwargs):
        raise AssertionError("read the sheet although the song exists")

    monkeypatch.setattr("pianist.sheet.read_omr", must_not_read)
    with pytest.raises(SheetError, match="this sheet was already read into .*amazing-grace"):
        new_song(str(tmp_path / "AmazingGrace.pdf"), tmp_path / "songs", "omr")


def test_a_read_song_is_never_thrown_away(tmp_path, monkeypatch):
    """The title the reader finds may collide with another song, or not slugify at all: keep the work anyway."""
    (tmp_path / "songs" / "dem-thanh").mkdir(parents=True)
    shutil.copy(SHEET, tmp_path / "Silent.pdf")
    (tmp_path / "Silent2.pdf").write_bytes(SHEET.read_bytes() + b"\n% another sheet")
    titles = iter(["Đêm Thánh", "聖夜"])
    monkeypatch.setattr("pianist.sheet.read_omr", lambda sheet, work, title: (f'title = "{next(titles)}"\n', []))
    first, _ = new_song(str(tmp_path / "Silent.pdf"), tmp_path / "songs", "omr")
    second, _ = new_song(str(tmp_path / "Silent2.pdf"), tmp_path / "songs", "omr")
    assert first.name == "dem-thanh-2" and second.name == "silent2"


def test_missing_tools_and_broken_files_are_messages(tmp_path, monkeypatch):
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(SheetError, match="could not read broken.pdf as a PDF"):
        new_song(str(tmp_path / "broken.pdf"), tmp_path / "songs", "omr")
    monkeypatch.setenv("PATH", str(tmp_path))  # no poppler, no homr
    with pytest.raises(SheetError, match="pdfinfo is not installed"):
        new_song(str(tmp_path / "broken.pdf"), tmp_path / "songs", "omr")


def test_file_names_that_do_not_slugify_and_same_named_sheets_both_work(tmp_path, monkeypatch):
    monkeypatch.setattr("pianist.sheet.read_omr", lambda sheet, work, title: ('title = ""\n', []))
    (tmp_path / "a").mkdir()
    shutil.copy(SHEET, tmp_path / "a" / "聖夜.pdf")
    first, _ = new_song(str(tmp_path / "a" / "聖夜.pdf"), tmp_path / "songs", "omr")
    assert first.name == "song"  # no Latin letters to name the folder after
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "聖夜.pdf").write_bytes(SHEET.read_bytes() + b"\n% another sheet")
    second, _ = new_song(str(tmp_path / "b" / "聖夜.pdf"), tmp_path / "songs", "omr")
    assert second.name == "song-2"  # a different sheet with the same name gets its own folder
