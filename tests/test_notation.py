from fractions import Fraction as F

import pytest

from pianist.notation import (
    BarSpeller,
    bar_length,
    engrave,
    length,
    make_room,
    melody_in_octaves,
    notes,
    octave,
    outside,
    signature,
    top_voice,
)


def test_octave_moves_every_pitch_and_keeps_accidentals_and_lengths():
    assert octave("A,,E,^C2", 1) == "A,E^c2"
    assert octave("c'a", -1) == "cA"


def test_top_voice_keeps_first_written_note_with_its_length():
    assert top_voice("[gd]2 (3[gd][gB][dG]") == "g2 (3ggd"
    assert top_voice("[B/E/][B/D/]") == "B/B/"


def test_melody_in_octaves_doubles_melody_above_written_harmony():
    assert melody_in_octaves("[ec]3 E") == "[c'e'e]3 [eE]"
    assert melody_in_octaves("[B/E/]") == "[e/b/B/]"


@pytest.mark.parametrize("key, sharps, flats", [("Am", "", ""), ("G", "F", ""), ("Em", "F", ""), ("Bb", "", "BE"), ("F#m", "FCG", "")])
def test_signature(key, sharps, flats):
    sig = signature(key)
    assert {k for k, v in sig.items() if v == 1} == set(sharps)
    assert {k for k, v in sig.items() if v == -1} == set(flats)


def test_signature_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown key 'H'"):
        signature("H")


def test_speller_writes_accidentals_against_key_and_bar():
    spell = BarSpeller("Am")
    assert spell(61, "C") == "^C"
    assert spell(61, "C") == "C"  # still sharp from earlier in the bar
    assert spell(60, "C") == "=C"  # natural must be restored
    assert spell(49, "C") == "^C,"  # other octave: its own accidental
    assert BarSpeller("G")(54, "F") == "F,"  # F# is in the signature
    assert BarSpeller("G")(53, "F") == "=F,"
    assert BarSpeller("Am")(59, "C") == "_C"  # Cb4
    assert BarSpeller("Am")(72, "C") == "c"  # C5


@pytest.mark.parametrize("text, value", [("", 1), ("3", 3), ("/", F(1, 2)), ("//", F(1, 4)), ("3/2", F(3, 2)), ("/4", F(1, 4))])
def test_length(text, value):
    assert length(text) == value


def test_notes_reads_chords_tuplets_rests_and_accidentals():
    assert notes("[gd]2 (3[gd][gB][dG]", "C") == [(0, 2, (79, 74)), (2, F(2, 3), (79, 74)), (F(8, 3), F(2, 3), (79, 71)), (F(10, 3), F(2, 3), (74, 67))]
    assert notes("[GD]2 z G", "C") == [(0, 2, (67, 62)), (2, 1, ()), (3, 1, (67,))]
    assert [m for _, _, m in notes("^C C =C F", "G")] == [(61,), (61,), (60,), (66,)]  # F# from the key
    assert [(s, d) for s, d, _ in notes("A>B c2", "Am")] == [(0, F(3, 2)), (F(3, 2), F(1, 2)), (2, 2)]


@pytest.mark.parametrize("bar, eighths", [("G G D B,", 4), ("[dB]3 [d/G/][d/F/]", 4), ("\"^Intro\"!p!{g}A2-A2", 4), ("(3ABc d", 3), ("z6", 6)])
def test_bar_length(bar, eighths):
    assert bar_length(bar, "Am") == eighths


def test_notes_rejects_unreadable_abc():
    with pytest.raises(ValueError, match="cannot read"):
        notes("A2 | B2", "Am")


@pytest.mark.parametrize("n, parts", [(1, [1]), (5, [4, 1]), (7, [6, 1]), (9, [6, 3]), (11, [8, 3]), (12, [12]), (F(5, 2), [2, F(1, 2)]), (F(1, 2), [F(1, 2)])])
def test_engrave_splits_lengths_a_score_can_print(n, parts):
    assert engrave(n) == parts


def test_notes_rejects_impossible_accidental():
    with pytest.raises(ValueError, match="cannot read"):
        notes("^_G4", "Am")


def test_transforms_leave_text_decorations_and_grace_notes_alone():
    bar = '"^rit."!fermata!B2 A2 {a}G2'
    assert outside(melody_in_octaves)(bar) == '"^rit."!fermata![bB]2 [aA]2 {a}[gG]2'
    assert outside(lambda b: octave(top_voice(b), 1), grace=lambda g: octave(g, 1))(bar) == '"^rit."!fermata!b2 a2 {a\'}g2'


def test_make_room_shortens_the_last_note_for_a_pickup():
    assert make_room("a4", 1) == "a3"
    assert make_room("[gdB]4", 2) == "[gdB]2"
    assert make_room("G6", 1) == "G4-G"  # 5 eighths cannot be one printed note
    assert make_room("B2 z4", 1) == "B2 z3"
    assert make_room("A2 E2", 2) is None  # nothing would be left of the last note
    assert make_room("b2 z2", 2) == "b2"  # a rest can give way to the upbeat entirely
    assert make_room("(3ABc d", F(1, 2)) == "(3ABc d/"


@pytest.mark.parametrize("bar, midi", [("[^^Ce]2", (62, 76)), ("[__ec]2", (74, 72)), ("^^C2", (62,))])
def test_double_accidentals_read_the_same_inside_and_outside_chords(bar, midi):
    assert notes(bar, "C")[0][2] == midi
    assert octave(bar, 1).count("^^") + octave(bar, 1).count("__") == 1  # moved with its accidental
