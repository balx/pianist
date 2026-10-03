"""End to end: python -m pianist, as a user runs it."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import mido
import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not shutil.which("abc2midi"), reason="needs the nix develop toolchain")


def build(song_dir, out, *args):
    return subprocess.run([sys.executable, "-m", "pianist", str(song_dir), "--out", str(out), *args], cwd=ROOT, capture_output=True, text=True, check=False)


def write_song(tmp_path, body):
    song = tmp_path / "songs" / "tiny"
    (song / "input").mkdir(parents=True)
    (song / "input" / "song.toml").write_text('title = "Tiny"\nkey = "G"\n' + body, encoding="utf-8")
    return song


THREE_FOUR = """meter = "3/4"
tempo = 80
[parts.verse]
melody = {verse}
chords = ["G", "C D7", "G"]
[[sections]]
name = "verse"
part = "verse"
"""


def test_builds_a_new_song_in_three_four(tmp_path):
    p = build(write_song(tmp_path, THREE_FOUR.format(verse='["B2 A2 G2", "E2 F2 A2", "G6"]')), tmp_path / "out", "--no-audio")
    assert p.returncode == 0, p.stderr
    assert "M:3/4" in (tmp_path / "out" / "tiny" / "score.abc").read_text(encoding="utf-8")


@pytest.mark.parametrize("verse", ['["B2 A2", "E2 F2 A2", "G6"]', '["B2 A2 G2", "E2 F2", "G6"]'], ids=["first-bar", "middle-bar"])
def test_rejects_bar_with_wrong_length(tmp_path, verse):
    p = build(write_song(tmp_path, THREE_FOUR.format(verse=verse)), tmp_path / "out", "--no-audio")
    assert p.returncode != 0
    assert "lasts 4 eighths but a 3/4 bar has 6" in p.stderr
    assert "Traceback" not in p.stderr


def test_reports_song_errors_without_traceback(tmp_path):
    p = build(write_song(tmp_path, THREE_FOUR.format(verse='["B2 A2 G2", "E2 F2 A2"]')), tmp_path / "out", "--no-audio")
    assert p.returncode != 0
    assert "2 melody bars but 3 chord entries" in p.stderr
    assert "Traceback" not in p.stderr


SIX_EIGHT = """meter = "6/8"
tempo = 60
[parts.verse]
pickup = "D"
melody = ["G2 B d2 B", "c3 A2 F", "G2 A B2 c", "d3 z2 D", "G2 B d2 B", "e3 c2 A", "B2 G A2 F", "G6"]
chords = "auto"
[[sections]]
name = "verse"
part = "verse"
"""


def test_six_eight_with_pickup_and_auto_chords(tmp_path):
    p = build(write_song(tmp_path, SIX_EIGHT), tmp_path / "out", "--no-audio")
    assert p.returncode == 0, p.stderr
    assert p.stdout.startswith('[parts.verse] chords = ["G", ')  # chosen chords, ready to paste back
    out = tmp_path / "out" / "tiny"
    abc = (out / "score.abc").read_text(encoding="utf-8")
    assert "M:6/8" in abc and "Q:3/8=60" in abc
    assert "[V:RH]\n%%MIDI chordattack 0\nD | " in abc and "[V:LH]\n%%MIDI chordattack 0\nz | " in abc  # pickup, left hand resting under it
    mid = mido.MidiFile(out / "piano.mid")
    first_tempo = next(m for m in mid.tracks[0] if m.type == "set_tempo")
    assert round(mido.tempo2bpm(first_tempo.tempo)) == 90  # 60 dotted quarters = 90 quarter notes
    t, first_bass = 0, None
    for m in mid.tracks[2]:
        t += m.time
        if m.type == "note_on" and m.velocity > 0:
            first_bass = t
            break
    # the bass enters on the first downbeat, one eighth (the pickup) in; abc2midi starts notes 1 tick late, humanize jitters them
    assert abs(first_bass - mid.ticks_per_beat // 2) <= mid.ticks_per_beat // 80 + 1


@pytest.mark.skipif(not os.environ.get("PIANIST_SF_UPRIGHT"), reason="needs the upright soundfont")
def test_loud_master_reaches_minus_16_lufs_without_clipping(tmp_path):
    p = build(write_song(tmp_path, THREE_FOUR.format(verse='["B2 A2 G2", "E2 F2 A2", "G6"]')), tmp_path / "out", "--soundfont", "upright", "--loud")
    assert p.returncode == 0, p.stderr
    mp3 = tmp_path / "out" / "tiny" / "tiny-upright-loud.mp3"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp3), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, check=False)
    summary = r.stderr[r.stderr.rindex("Summary:") :]
    loudness = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary).group(1))
    assert -16.3 <= loudness <= -15.7
    assert peak <= -1.3


METERS = [("2/4", 4, 2), ("3/4", 6, 2), ("4/4", 8, 2), ("6/8", 6, 3), ("9/8", 9, 3), ("12/8", 12, 3)]


@pytest.mark.parametrize("meter, eighths, beat", METERS, ids=[m for m, _, _ in METERS])
def test_every_meter_and_style_engraves(tmp_path, meter, eighths, beat):
    """The left hand, holds and the longest pickup must be printable; abcm2ps aborts on lengths like 5 or 9 eighths."""
    whole = "B6-B3" if eighths == 9 else f"B{eighths}"  # the melody is the user's text, so keep it printable
    pickup = {3: "D3", 5: "D4 D", 7: "D6 D", 8: "D8", 11: "D8 D3"}[eighths - 1]  # the longest upbeat: the rest under it is the tool's
    body = f"""meter = "{meter}"
tempo = 70
[parts.verse]
pickup = "{pickup}"
melody = ["{whole}", "{whole}", "{whole}", "{whole}"]
chords = ["G", "C D7", "Em", "G"]
[[sections]]
name = "verse"
part = "verse"
lh = ["flow", "rise", "octave", "hold"]
"""
    p = build(write_song(tmp_path, body), tmp_path / "out", "--no-audio")
    assert p.returncode == 0, p.stderr


def long_form(tmp_path, repeats):
    song = tmp_path / "songs" / "long"
    (song / "input").mkdir(parents=True)
    text = (ROOT / "songs" / "amazing-grace" / "input" / "song.toml").read_text(encoding="utf-8")
    extra = "".join(f'\n[[sections]]\nname = "v{k}"\npart = "verse"\ntransform = "octaves"\n' for k in range(repeats))
    (song / "input" / "song.toml").write_text(text + extra, encoding="utf-8")
    return song


def test_long_song_prints_on_several_pages_and_leaves_no_stale_pages(tmp_path):
    out = tmp_path / "out"
    p = build(long_form(tmp_path, 6), out, "--no-audio")  # 40 + 6 x 16 = 136 bars
    assert p.returncode == 0, p.stderr
    pages = sorted(f.name for f in (out / "long").glob("score*.png"))
    assert len(pages) > 3 and (out / "long" / "piano.mid").exists()
    (tmp_path / "songs" / "long" / "input" / "song.toml").write_text((ROOT / "songs" / "amazing-grace" / "input" / "song.toml").read_text(encoding="utf-8"), encoding="utf-8")
    p = build(tmp_path / "songs" / "long", out, "--no-audio")
    assert p.returncode == 0, p.stderr
    assert len(list((out / "long").glob("score*.png"))) == len(list((out / "long").glob("score*.svg"))) < len(pages)


@pytest.mark.parametrize("name, message", [("scan.tiff", "not a PDF or an image"), ("songs/nope", "no input/song.toml")])
def test_cli_explains_inputs_it_cannot_use(tmp_path, name, message):
    target = tmp_path / name
    if target.suffix:
        target.write_bytes(b"II*\x00")
    p = build(target, tmp_path / "out", "--no-audio")
    assert p.returncode != 0 and message in p.stderr and "Traceback" not in p.stderr


def test_a_song_builds_into_its_own_output_folder(tmp_path):
    """songs/<slug>/input holds what you give (sheet, song.toml), songs/<slug>/output what pianist makes."""
    song = write_song(tmp_path, THREE_FOUR.format(verse='["B2 A2 G2", "E2 F2 A2", "G6"]'))
    p = subprocess.run([sys.executable, "-m", "pianist", str(song), "--no-audio"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    assert {f.name for f in (song / "output").iterdir()} == {"score.abc", "raw.mid", "piano.mid", "score001.svg", "score001.png"}


def test_a_missing_tool_is_named_not_a_traceback(tmp_path):
    env = {"PATH": str(tmp_path), "PYTHONPATH": str(ROOT)}  # nothing from nix develop on the PATH
    p = subprocess.run([sys.executable, "-m", "pianist", str(ROOT / "songs" / "amazing-grace"), "--out", str(tmp_path), "--no-audio"], env=env, capture_output=True, text=True, check=False)
    assert p.returncode != 0 and "abc2midi is not installed: run inside `nix develop`" in p.stderr and "Traceback" not in p.stderr


@pytest.mark.parametrize("bar", ["^F2 =f2 c4", "^F2 f2 F4", "{^F}G2 F2 G4", "[^Fd]2 f2 (3FfF z2", "^^C2 c2 _B,2 B2"])
def test_the_score_plays_the_pitches_pianist_reads(tmp_path, bar):
    """abc2midi must agree with notation.notes() on every accidental: they carry through the bar, per octave."""
    from pianist.notation import notes

    song = write_song(tmp_path, f'meter = "4/4"\ntempo = 60\n[parts.a]\nmelody = ["{bar}"]\nchords = ["C"]\n[[sections]]\nname = "a"\npart = "a"\n')
    p = build(song, tmp_path / "out", "--no-audio")
    assert p.returncode == 0, p.stderr
    played = [m.note for m in mido.MidiFile(tmp_path / "out" / "tiny" / "raw.mid").tracks[1] if m.type == "note_on" and m.velocity]
    expected = [n for _, _, ns in notes(bar, "G") for n in ns]
    assert played[len(played) - len(expected) :] == expected  # abc2midi also plays the grace notes first


def test_a_hand_that_only_rests_builds(tmp_path):
    song = write_song(tmp_path, 'meter = "4/4"\ntempo = 60\n[parts.a]\nmelody = ["z8", "G8"]\nchords = ["G", "G"]\n[[sections]]\nname = "a"\npart = "a"\n')
    p = build(song, tmp_path / "out", "--no-audio")
    assert p.returncode == 0, p.stderr
