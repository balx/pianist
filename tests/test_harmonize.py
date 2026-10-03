import tomllib
from pathlib import Path

import pytest

from pianist.harmonize import chords_of, harmonize
from pianist.harmony import voicing

SAMPLE = tomllib.loads((Path(__file__).resolve().parent.parent / "songs" / "amazing-grace" / "input" / "song.toml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "key, names",
    [
        ("C", ["C", "Dm", "Em", "G", "G7", "F", "Am"]),
        ("Am", ["Am", "C", "Dm", "E", "E7", "F", "G"]),
        ("F#m", ["F#m", "A", "Bm", "C#", "C#7", "D", "E"]),
        ("Bb", ["Bb", "Cm", "Dm", "F", "F7", "Eb", "Gm"]),
    ],
)
def test_palette_is_the_keys_own_chords(key, names):
    assert [name for name, _, _ in chords_of(key)] == names
    for name in names:
        voicing(name)  # every chord it may choose can be voiced


def test_four_four_changes_at_the_half_bar_and_cadences():
    assert harmonize(["c2 e2 g2 e2", "f2 a2 g2 f2", "e2 d2 c2 d2", "c8"], "C", 8, 2) == ["C", "Dm G7", "C F", "C"]


def test_six_eight_follows_the_melody():
    assert harmonize(["G2 B c", "d3 B G2", "A3 F D2"], "G", 6, 3) == ["G", "G", "D"]


def test_agreement_with_the_samples_printed_chords():
    """Measured, not tuned: the harmonizer only knows the key's chords and favours falling fifths, so it agrees with
    the printed chords on about half the bars by root; it misses colour (Em, G7) and the D7 -> G approach to the end."""
    verse = SAMPLE["parts"]["verse"]
    auto = harmonize(verse["melody"], "G", 6, 2)
    assert auto[0] == "G" and auto[-1] == "G"
    root = lambda chord: chord.split()[0].rstrip("7").rstrip("m")
    assert sum(root(a) == root(b) for a, b in zip(auto, verse["chords"])) == 9
