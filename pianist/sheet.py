"""A sheet (PDF, image or link) -> a new songs/<slug>/input/ holding sheet.<ext> and a song.toml written by a reader."""

import http.client
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .build import build
from .claude_reader import ReaderError, read
from .musicxml import convert
from .songfile import dump, slugify

SHEETS = {".pdf", ".png", ".jpg", ".jpeg"}
MAGIC = {b"%PDF": ".pdf", b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg"}  # what the bytes are, whatever the server says
MAX_BYTES = 64 * 1024 * 1024
MAX_PAGES = 20  # one song; a whole hymnal would take OMR (or Claude) a very long time
USER_AGENT = "Mozilla/5.0 (pianist; +https://github.com/)"  # many sheet sites refuse Python's default agent


class SheetError(Exception):
    pass


def is_sheet(arg: str) -> bool:
    return arg.startswith(("http://", "https://")) or Path(arg).suffix.lower() in SHEETS


def title_from(source: str) -> str:
    """A title from the file name: 'AmazingGrace.pdf' -> 'Amazing Grace'."""
    stem = Path(urllib.parse.unquote(urllib.parse.urlparse(source).path if "://" in source else source)).stem
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", re.sub(r"[_-]+", " ", stem)).strip()


def direct(url: str) -> str:
    """The file behind a share link that opens a viewer page (Google Drive, GitHub)."""
    if drive := re.match(r"https://(?:drive|docs)\.google\.com/(?:file/d/|open\?(?:.*&)?id=)([\w-]+)", url):
        return f"https://drive.google.com/uc?export=download&id={drive[1]}"
    return re.sub(r"^(https://github\.com/[^/]+/[^/]+)/blob/", r"\1/raw/", url)


def _utf8(header: str) -> str:
    """http.client reads headers as latin-1; servers send file names as UTF-8 bytes ('Đêm' arrives as 'Ä\x90Ãªm')."""
    try:
        return header.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return header


def fetch(source: str, work: Path) -> Path:
    """Copy or download the sheet into work/, keeping its name; returns its path there."""
    work.mkdir(parents=True, exist_ok=True)
    if "://" not in source:
        path = Path(source)
        if not path.is_file():
            raise SheetError(f"{source}: no such file")
        if path.suffix.lower() not in SHEETS:
            raise SheetError(f"{source}: not a PDF or an image (png, jpg)")
        return Path(shutil.copy(path, work / f"{path.stem}{path.suffix.lower()}"))
    try:
        url = urllib.parse.quote(source, safe=":/?#[]@!$&'()*+,;=%~")  # spaces and letters as pasted from a browser
        request = urllib.request.Request(direct(url), headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as r:
            body = r.read(MAX_BYTES + 1)
            size = r.headers.get("Content-Length", "")
            name = _utf8(r.headers.get_filename() or "") or source
    except (OSError, ValueError, http.client.HTTPException) as e:  # OSError covers URLError and timeouts
        raise SheetError(f"could not download {source}: {e}") from None
    if len(body) > MAX_BYTES:
        raise SheetError(f"{source} is larger than {MAX_BYTES // 2**20} MB; that is not one song sheet")
    if size.isdigit() and len(body) < int(size):
        raise SheetError(f"the download of {source} was cut off ({len(body)} of {size} bytes); try again")
    ext = next((e for magic, e in MAGIC.items() if body.startswith(magic)), None)
    if ext is None:
        page = body.lstrip()[:1] == b"<"  # a login or viewer page
        raise SheetError(f"{source} opened a web page, not the sheet: is the file shared publicly?" if page else f"{source} is not a PDF or an image (png, jpg)")
    path = work / f"{re.sub(r'[^\w -]', '', title_from(name))[:80].strip() or 'sheet'}{ext}"
    path.write_bytes(body)
    return path


def check_pages(sheet: Path) -> None:
    """A PDF holds one song: refuse a whole book before any slow or paid reading."""
    if sheet.suffix != ".pdf":
        return
    p = _tool(["pdfinfo", str(sheet)])
    count = re.search(r"^Pages:\s+(\d+)", p.stdout, re.MULTILINE)
    if p.returncode != 0 or not count:
        raise SheetError(f"could not read {sheet.name} as a PDF: {p.stderr.strip()[-500:]}")
    if int(count.group(1)) > MAX_PAGES:
        raise SheetError(f"{sheet.name} has {count.group(1)} pages; give one song (at most {MAX_PAGES} pages), for example by splitting the PDF")


def pages(sheet: Path, work: Path) -> list[Path]:
    """The sheet as page images: a PDF is rasterized at 300 dpi, an image is its own page."""
    if sheet.suffix != ".pdf":
        return [sheet]
    p = _tool(["pdftoppm", "-r", "300", "-png", str(sheet), str(work / "page")])
    if p.returncode != 0:
        raise SheetError(f"could not turn {sheet.name} into page images: {p.stderr.strip()[-500:]}")
    return sorted(work.glob("page-*.png"))


def _tool(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    except FileNotFoundError:
        raise SheetError(f"{cmd[0]} is not installed: run inside `nix develop`") from None


def _homr(page: Path) -> subprocess.CompletedProcess:
    """homr on one page image. On Apple Silicon its encoder runs on the GPU (CoreML; ignored elsewhere), about 1.35x faster,
    once the compiled model is cached: in the user's cache, as homr's default is next to the model, in the read-only Nix store."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pianist" / "homr-coreml"
    return _tool(["homr", "--coreml-encoder", str(page)], env=os.environ | {"HOMR_COREML_MODEL_CACHE_DIR": str(cache)})


def read_omr(sheet: Path, work: Path, title: str) -> tuple[str, list[str]]:
    """Optical music recognition with homr, pages in parallel; the measures of all pages joined into one score."""
    score = None
    images = pages(sheet, work)
    # The first page alone fills the CoreML cache (parallel homrs racing to create it fall back to the CPU). Each homr then
    # already uses ~6 cores and ~1.5 GB, so 4 at once is about 1.6x faster than one at a time; more only adds memory.
    runs = [_homr(images[0])]
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs += pool.map(_homr, images[1:])
    for page, p in zip(images, runs):
        xml = page.with_suffix(".musicxml")
        if p.returncode != 0 or not xml.exists():
            raise SheetError(f"homr could not read {page.name}:\n{p.stderr[-2000:]}")
        root = ET.parse(xml).getroot()
        if score is None:
            score = root
        elif root.find("part") is not None:
            score.find("part").extend(root.find("part").findall("measure"))
    try:
        data, notes = convert(ET.tostring(score, encoding="unicode"), title=title)
    except ValueError as e:
        raise SheetError(f"the recognized music could not be used: {e}") from None
    notes.append(f'title "{title}" comes from the file name, composer is empty and chords are "auto": edit song.toml to fix them')
    return dump(data), notes


def render_draft(song_toml: str, work: Path) -> list[Path]:
    """Build a draft song.toml without audio and return its score pages; SongError or BuildError if it does not build."""
    draft = work / "draft"
    shutil.rmtree(draft, ignore_errors=True)
    (draft / "input").mkdir(parents=True)
    (draft / "input" / "song.toml").write_text(song_toml, encoding="utf-8")
    build(draft, work / "out", None, audio=False)
    return sorted((work / "out" / "draft").glob("score*.png"))


def _folder(songs: Path, title: str, source: Path) -> Path:
    """songs/<slug of the title>, never an existing folder: a song that has been read is never thrown away."""
    slug = slugify(title) or slugify(title_from(source.name)) or "song"
    folder, n = songs / slug, 2
    while folder.exists():
        folder, n = songs / f"{slug}-{n}", n + 1
    return folder


def new_song(source: str, songs: Path, reader: str, log=lambda *a: print(*a, flush=True)) -> tuple[Path, list[str]]:
    """Read the sheet with the chosen reader and write songs/<slug>/input/{sheet.<ext>, song.toml}."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        sheet = fetch(source, work)
        data = sheet.read_bytes()
        same = next((p.parent.parent for p in Path(songs).glob("*/input/sheet.*") if p.read_bytes() == data), None)
        if same:  # checked before any (slow or paid) reading
            raise SheetError(f"this sheet was already read into {same}: build it with `python3 -m pianist {same}`")
        check_pages(sheet)
        if reader == "omr":
            song_toml, notes = read_omr(sheet, work, title_from(sheet.name))
        else:
            try:
                song_toml, notes = read(sheet, render=lambda t: render_draft(t, work), log=log)
            except ReaderError as e:
                raise SheetError(str(e)) from None
        try:
            title = str(tomllib.loads(song_toml).get("title", ""))
        except tomllib.TOMLDecodeError:
            title = ""  # an unloadable draft is kept too; the build reports what is wrong with it
        song_dir = _folder(Path(songs), title, sheet)
        (song_dir / "input").mkdir(parents=True)
        shutil.copy(sheet, song_dir / "input" / f"sheet{sheet.suffix}")
        (song_dir / "input" / "song.toml").write_text(song_toml, encoding="utf-8")
    return song_dir, notes
