"""python3 -m pianist SHEET-or-SONG [--reader claude|omr] [--soundfont NAME] [--loud] [--no-audio]

SHEET is a PDF, an image or a link: it is read into songs/<slug>/input/song.toml first, then built.
SONG is a songs/<slug>/ folder: it is built as is (after you edit its song.toml, for example).
A song folder holds input/ (the sheet and song.toml) and output/, where the build writes score.abc,
score*.svg/.png (to check against the sheet), raw.mid, piano.mid and <slug>-<soundfont>[-loud].mp3.
"""

import argparse
import sys
from pathlib import Path

from .build import ROOT, BuildError, build
from .sheet import SheetError, is_sheet, new_song
from .song import SOUNDFONTS, SongError


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="pianist", description="A sheet (PDF, image or link) or a song folder -> expressive solo piano.")
    ap.add_argument("source", help="a sheet (.pdf .png .jpg or http(s) link) or a songs/<slug> folder")
    ap.add_argument("--reader", choices=("claude", "omr"), default="claude", help="how a sheet is read: claude (needs ANTHROPIC_API_KEY) or omr (offline, melody only)")
    ap.add_argument("--songs", type=Path, default=ROOT / "songs", help="where a new song folder is created")
    ap.add_argument("--soundfont", choices=SOUNDFONTS, help="override the song's soundfont")
    ap.add_argument("--loud", action="store_true", help="master to -16 LUFS with a peak limiter (default keeps the full dynamics)")
    ap.add_argument("--no-audio", action="store_true", help="stop after piano.mid (no soundfont needed)")
    ap.add_argument("--out", type=Path, help="write into OUT/<slug> instead of the song's output/ folder")
    a = ap.parse_args(argv)
    song_dir = Path(a.source)
    if song_dir.is_file() and not is_sheet(a.source):
        raise SystemExit(f"{a.source}: not a PDF or an image (png, jpg), and not a song folder")
    if is_sheet(a.source):
        try:
            song_dir, notes = new_song(a.source, a.songs, a.reader)
        except SheetError as e:
            raise SystemExit(str(e))
        for note in notes:
            print(f"note: {note}")
        print(f"wrote {song_dir}/input/song.toml; edit it and run `python3 -m pianist {song_dir}` to rebuild")
    elif not (song_dir / "input" / "song.toml").is_file():
        raise SystemExit(f"{song_dir}: no input/song.toml here; give a song folder, or a sheet (PDF, image or link)")
    try:
        print(build(song_dir, a.out, a.soundfont, not a.no_audio, a.loud))
    except (SongError, BuildError) as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    sys.exit(main())
