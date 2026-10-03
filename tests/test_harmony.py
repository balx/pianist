import pytest

from pianist.harmony import left_hand, split, voicing
from pianist.notation import BarSpeller

# The hand-picked voicing table that voicing() replaced: bass, fifth, colour, top.
ORIGINAL = {
    "Am": "A,, E, C A,", "A7": "A,, E, ^C G,", "Dm": "D, A, F D", "G": "G,, D, B, G,", "E": "E,, B,, ^G, E,",
    "E7": "E,, B,, ^G, D,", "C": "C, G, E C", "F": "F,, C, A, F,", "Em7": "E,, B,, G, D,",
}


@pytest.mark.parametrize("name", ORIGINAL)
def test_voicing_reproduces_original_table(name):
    spelled = [BarSpeller("Am")(*n) for n in voicing(name)]
    assert " ".join(spelled) == ORIGINAL[name]


def test_voicing_qualities_and_slash_bass():
    midi = lambda name: [m for m, _ in voicing(name)]
    assert midi("Cmaj7") == [48, 55, 64, 59]
    assert midi("Bdim") == [47, 53, 62, 59]
    assert midi("Dsus4") == [50, 57, 67, 62]
    assert midi("C/E") == [40, 55, 64, 60]
    assert [l for _, l in voicing("F#m")] == ["F", "C", "A", "F"]
    with pytest.raises(ValueError, match="unknown chord 'Hm'"):
        voicing("Hm")


def test_split_gives_first_chord_the_remainder():
    assert split(4, 2) == [2, 2]
    assert split(4, 3) == [2, 1, 1]
    assert split(6, 4) == [3, 1, 1, 1]
    with pytest.raises(ValueError, match="do not fit"):
        split(4, 5)


@pytest.mark.parametrize(
    "chords, style, expected",
    [
        ("Am", "flow", "A,,E,CE,"),
        ("Am", "rise", "A,,E,A,C"),
        ("A7", "octave", "[A,,A,]E,^CE,"),
        ("Am", "hold", "[A,,E,]4"),
        ("C E7", "flow", "C,G, E,,B,,"),
        ("G F E7", "octave", "G,,D, F,, E,,"),
    ],
)
def test_left_hand_two_four(chords, style, expected):
    assert left_hand(chords, style, 4, 2, "Am") == expected


def test_left_hand_other_meters_fill_the_bar_and_beam_by_beat():
    assert left_hand("G", "flow", 6, 2, "G") == "G,,D,B,D,B,D,"  # 3/4: one beam
    assert left_hand("G", "rise", 8, 2, "G") == "G,,D,G,B, G,D,G,,D,"  # 4/4: half bars
    assert left_hand("G", "hold", 6, 2, "G") == "[G,,D,]6"
    assert left_hand("G", "flow", 6, 3, "G") == "G,,D,B, D,B,D,"  # 6/8: dotted quarters
    assert left_hand("G", "octave", 12, 3, "G") == "[G,,G,]D,B, D,B,D, B,D,B, D,B,D,"
    assert left_hand("C D7", "flow", 6, 3, "G") == "C,G,E D,A,F"  # F# from the key signature


def test_left_hand_restores_natural_after_accidental_in_same_bar():
    assert left_hand("A7 Am", "flow", 8, 2, "Am") == "A,,E,^CE, A,,E,=CE,"


def test_dim7_has_a_diminished_seventh():
    assert voicing("Bdim7") == [(47, "B"), (53, "F"), (62, "D"), (56, "A")]  # top is Ab
    assert voicing("G#dim7")[3] == (53, "F")
    assert BarSpeller("C")(*voicing("Bdim7")[3]) == "_A,"


def test_hold_is_tied_when_the_bar_is_not_one_printable_note():
    assert left_hand("D", "hold", 9, 3, "D") == "[D,A,]6-[D,A,]3"
    assert left_hand("D", "hold", 12, 3, "D") == "[D,A,]12"
