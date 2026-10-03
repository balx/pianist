"""songs/amazing-grace/output is the committed example output for the example input songs/amazing-grace/input.

Regenerate it after any change that alters output, and review the diff:
    python3 -m pianist songs/amazing-grace
    python3 -m pianist songs/amazing-grace --soundfont upright
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "songs" / "amazing-grace" / "output"
pytestmark = pytest.mark.skipif(not shutil.which("abc2midi"), reason="needs the nix develop toolchain")
STALE = "songs/amazing-grace/output is stale: regenerate it (see this module's docstring)"


def build(cwd, *args):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, "-m", "pianist", str(ROOT / "songs" / "amazing-grace"), *args], cwd=cwd, env=env, capture_output=True, text=True, check=False)


def test_sample_score_and_midi_are_current(tmp_path):
    p = build(ROOT, "--out", str(tmp_path), "--no-audio")
    assert p.returncode == 0, p.stderr
    out = tmp_path / "amazing-grace"
    for name in ("score.abc", "raw.mid", "piano.mid"):
        assert (out / name).read_bytes() == (SAMPLE / name).read_bytes(), f"{name}: {STALE}"
    pages = sorted(p.name for p in out.glob("score*.svg"))
    assert pages == ["score001.svg", "score002.svg"]  # one per page, no lone coda page
    assert pages == sorted(p.name for p in SAMPLE.glob("score*.svg")), f"score pages: {STALE}"
    for page in pages:
        assert (out / page).read_bytes() == (SAMPLE / page).read_bytes(), f"{page}: {STALE}"  # no timestamps: rebuilds are byte-identical
    expected = {"piano.mid", "raw.mid", "score.abc", "amazing-grace-salamander.mp3", "amazing-grace-upright.mp3"}
    assert {p.name for p in SAMPLE.iterdir()} == expected | set(pages) | {p.replace(".svg", ".png") for p in pages}


def decode(mp3: Path, wav: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), str(wav)], check=True)


def rms(*sox_inputs: str) -> float:
    p = subprocess.run(["sox", *sox_inputs, "-n", "stat"], capture_output=True, text=True, check=True)
    return float(re.search(r"RMS\s+amplitude:\s+([\d.]+)", p.stderr).group(1))


@pytest.mark.skipif(not os.environ.get("PIANIST_SF_UPRIGHT"), reason="needs the upright soundfont")
def test_sample_mp3_is_current_with_relative_out_dir(tmp_path):
    p = build(tmp_path, "--soundfont", "upright", "--out", "rel")  # relative --out, run from another directory
    assert p.returncode == 0, p.stderr
    new, old = tmp_path / "new.wav", tmp_path / "old.wav"
    decode(tmp_path / "rel" / "amazing-grace" / "amazing-grace-upright.mp3", new)
    decode(SAMPLE / "amazing-grace-upright.mp3", old)
    # Byte-identical on the platform that rendered the sample; other platforms differ only at rounding level.
    assert rms("-m", "-v", "1", str(new), "-v", "-1", str(old)) < 0.01 * rms(str(old)), f"mp3: {STALE}"
