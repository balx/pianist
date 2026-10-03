"""songs/<slug>/input -> songs/<slug>/output: score.abc, score pages (SVG + PNG), raw.mid, piano.mid and the mastered mp3."""

import json
import os
import re
import subprocess
from pathlib import Path

from .humanize import humanize
from .score import abc
from .song import load

ROOT = Path(__file__).resolve().parent.parent


class BuildError(Exception):
    pass


def run(*cmd: str, cwd: Path) -> str:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise BuildError(f"{Path(cmd[0]).name} is not installed: run inside `nix develop`") from None
    if p.returncode != 0:
        raise BuildError(f"{Path(cmd[0]).name} failed:\n{p.stdout}{p.stderr}")
    return p.stdout + p.stderr


def soundfont(name: str) -> str:
    var = f"PIANIST_SF_{name.upper()}"
    path = os.environ.get(var)
    if not path or not Path(path).is_file():
        raise BuildError(f"${var} is not set to a .sf2 file; run inside `nix develop` (the default shell has both pianos)")
    return path


def build(song_dir: Path, out_root: Path | None, sf: str | None, audio: bool, loud: bool = False) -> Path:
    """Writes into song_dir/output, or into out_root/<slug> when out_root is given. Raises SongError or BuildError."""
    song = load(song_dir)
    for part, chords in song.auto_chords.items():  # so the user can review and edit them
        print(f"[parts.{part}] chords = {json.dumps(chords, ensure_ascii=False)}")
    out = out_root.resolve() / song.slug if out_root else Path(song_dir).resolve() / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "score.abc").write_text(abc(song), encoding="utf-8")
    log = run("abc2midi", "score.abc", "-o", "raw.mid", cwd=out)
    problems = [line for line in log.splitlines() if line.startswith(("Warning", "Error"))]
    if problems:
        raise BuildError("abc2midi found problems in the transcription:\n" + "\n".join(problems))
    for old in [*out.glob("score*.svg"), *out.glob("score*.png")]:  # a shorter score must not leave old pages behind
        old.unlink()
    # one SVG per page (-g overflows on long songs); scale 0.72 keeps the sample from ending on a lone system
    run("abcm2ps", "-v", "-s", "0.72", "-O", "score", "score.abc", cwd=out)
    for svg in sorted(out.glob("score*.svg")):
        svg.write_text(re.sub(r"<!-- CreationDate: .* -->\n", "", svg.read_text(encoding="utf-8")), encoding="utf-8")  # reproducible output
        run("rsvg-convert", "-b", "white", "-z", "2", "-o", svg.with_suffix(".png").name, svg.name, cwd=out)
    humanize(song, str(out / "raw.mid"), str(out / "piano.mid"))
    if not audio:
        return out / "piano.mid"
    name = sf or song.soundfont
    mp3 = out / f"{song.slug}-{name}{'-loud' if loud else ''}.mp3"
    print(run(str(ROOT / "render.sh"), soundfont(name), str(out / "piano.mid"), str(mp3), "loud" if loud else "full", cwd=out).strip())
    return mp3
