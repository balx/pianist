"""Sheet -> song.toml without a person: MusicXML from optical music recognition, the default form, the song file writer."""

import tomllib
from pathlib import Path

import pytest

from pianist.musicxml import convert, fix_triplets, guess_key
from pianist.song import parse
from pianist.songfile import default_form, dump, slugify

ROOT = Path(__file__).resolve().parent.parent
HOMR = ROOT / "tests" / "fixtures" / "amazing-grace.homr.musicxml"  # homr 0.7.0's real output for songs/amazing-grace/input/sheet.pdf
SAMPLE = tomllib.loads((ROOT / "songs" / "amazing-grace" / "input" / "song.toml").read_text(encoding="utf-8"))


def test_homr_reading_of_the_sample_matches_the_hand_transcription_bar_for_bar():
    data, warnings = convert(HOMR.read_text(encoding="utf-8"), title="Amazing Grace")
    assert (data["key"], data["meter"]) == ("G", "3/4")
    song = data["parts"]["song"]
    assert song["pickup"] == SAMPLE["parts"]["verse"]["pickup"]
    assert song["melody"] == [bar.rstrip("-") for bar in SAMPLE["parts"]["verse"]["melody"]]  # homr reads no ties
    assert song["chords"] == "auto"  # nor chord symbols
    assert warnings == []  # the short last bar completes the upbeat: expected


def test_fix_triplets_turns_three_equal_notes_into_a_triplet_when_the_bar_overflows():
    events = [(2, "[BG]"), (1, "[AF]"), (1, "[AF]"), (1, "[FD]")]
    assert fix_triplets(events, 4) == [(2, "[BG]"), (1, "(3[AF]"), (1, "[AF]"), (1, "[FD]")]
    assert fix_triplets([(2, "A"), (2, "B")], 4) is None  # nothing to fix


@pytest.mark.parametrize("fifths, last, key", [(0, 69, "Am"), (0, 60, "C"), (1, 64, "Em"), (1, 67, "G"), (-2, 70, "Bb"), (-2, 67, "Gm")])
def test_guess_key_uses_the_final_note_to_pick_major_or_minor(fifths, last, key):
    assert guess_key(fifths, last) == key


def test_default_form_frames_one_part_with_intro_reprise_and_coda():
    sections = default_form({"song": 28})
    assert [s["name"] for s in sections] == ["intro", "song", "reprise", "coda"]
    assert sections[0]["bars"] == [25, 28] and sections[3]["bars"] == [25, 28]
    assert default_form({"song": 3})[0]["bars"] == [1, 3]  # short songs: the whole song is the intro


def test_default_form_plays_every_part_then_every_part_in_octaves():
    sections = default_form({"part1": 15, "part2": 16})
    assert [(s["name"], s["part"]) for s in sections] == [
        ("intro", "part2"), ("part1", "part1"), ("part2", "part2"), ("reprise part1", "part1"), ("reprise part2", "part2"), ("coda", "part2"),
    ]
    assert [s.get("shape", "flat") for s in sections] == ["flat", "flat", "flat", "flat", "arch", "fade"]


def test_a_short_bar_mid_score_starts_a_new_part_with_that_upbeat():
    """Like a hymn with refrain and verse: each opens on an upbeat, and the last bar completes the first upbeat."""
    full, held = [("G", 4, 4), ("B", 4, 2)], [("G", 4, 6)]
    bars = [[("D", 4, 2)], full, full, held, [("B", 4, 2)], full, full, full, [("G", 4, 4)]]
    data, warnings = convert(score(bars, fifths=1, time=(3, 4)))
    one, two = data["parts"]["part1"], data["parts"]["part2"]
    assert (one["pickup"], len(one["melody"])) == ("D2", 3)
    assert (two["pickup"], len(two["melody"])) == ("B2", 4)
    assert two["melody"][-1] == "G4 z2"
    assert warnings == ["song bar 4: only 2 eighths; read as the upbeat of part2 (a new part)"]
    assert one["melody"][-1] == "G6"  # held: room for the next part's upbeat
    song = parse(tomllib.loads(dump(data)), "x")  # and the arrangement builds: every upbeat finds room
    assert song.sections[0].melody[-1] == "g4 D2"


def test_dump_writes_a_song_file_that_parses_back():
    data, _ = convert(HOMR.read_text(encoding="utf-8"), title="Amazing Grace")
    text = dump(data)
    assert tomllib.loads(text) == data
    assert parse(tomllib.loads(text), "x").sections[1].chords[0] == "G"


@pytest.mark.parametrize("title, slug", [("Amazing Grace", "amazing-grace"), ("Đêm Thánh Vô Cùng!", "dem-thanh-vo-cung"), ("AmazingGrace", "amazing-grace")])
def test_slugify(title, slug):
    assert slugify(title) == slug


def score(bars, fifths=0, time=(2, 4)):
    """A minimal MusicXML score: bars of (step, octave, eighths[, flags]) notes, "z" rests, or ("key", fifths) changes.

    flags: {"alter": 1, "chord": True (sounds with the note before), "tie": True, "grace": True, "voice": 2}.
    """
    out = [(f"<score-partwise><part id='P1'><measure><attributes><divisions>4</divisions><key><fifths>{fifths}</fifths></key>"
            f"<time><beats>{time[0]}</beats><beat-type>{time[1]}</beat-type></time></attributes>")]
    for i, bar in enumerate(bars):
        if i:
            out.append("<measure>")
        for item in bar:
            if item[0] == "key":
                out.append(f"<attributes><key><fifths>{item[1]}</fifths></key></attributes>")
            elif item[0] == "z":
                out.append(f"<note><rest/><duration>{item[1] * 2}</duration></note>")
            else:
                step, octave, eighths, flags = (*item, {}) if len(item) == 3 else item
                out.append(
                    "<note>" + ("<grace/>" if flags.get("grace") else "") + ("<chord/>" if flags.get("chord") else "")
                    + f"<pitch><step>{step}</step><alter>{flags.get('alter', 0)}</alter><octave>{octave}</octave></pitch>"
                    + f"<duration>{int(eighths * 2)}</duration>" + ("<tie type='start'/>" if flags.get("tie") else "")
                    + f"<voice>{flags.get('voice', 1)}</voice></note>"
                )
        out.append("</measure>")
    return "".join(out) + "</part></score-partwise>"


def test_a_key_change_keeps_the_first_key_and_says_where_it_changes():
    bars = [[("G", 4, 4)], [("F", 4, 4)], [("key", 0), ("C", 5, 4)], [("C", 5, 4)]]
    data, notes = convert(score(bars, fifths=1))
    assert data["key"] == "G"  # one key per song: the first signature, not the last
    assert any("key signature changes to C major" in n and "bar 3" in n for n in notes)


def test_key_comes_from_the_first_signature():
    bars = [[("G", 4, 4)], [("D", 4, 4)], [("key", 0), ("C", 5, 4)], [("G", 4, 4)]]
    data, _ = convert(score(bars, fifths=1))
    assert data["key"] == "G"
    assert data["parts"]["song"]["melody"][1] == "D4"


def test_a_short_bar_mid_score_is_reported_as_a_new_part():
    bars = [[("G", 4, 4)], [("A", 4, 4)], [("B", 4, 2)], [("C", 5, 4)], [("G", 4, 4)]]
    data, notes = convert(score(bars, fifths=1))
    assert list(data["parts"]) == ["part1", "part2"]
    assert "song bar 3: only 2 eighths; read as the upbeat of part2 (a new part)" in notes


def test_a_final_bar_of_rests_still_finds_the_key():
    data, _ = convert(score([[("G", 4, 4)], [("D", 4, 4)], [("z", 4)]], fifths=1))
    assert data["key"] == "G"


def test_a_score_of_rests_is_reported_not_crashed():
    with pytest.raises(ValueError, match="no notes"):
        convert(score([[("z", 4)], [("z", 4)]]))


def test_no_new_part_when_the_bar_before_cannot_make_room_for_its_upbeat():
    full = [("G", 4, 4), ("B", 4, 2)]  # ends on a quarter: an upbeat of a quarter cannot fit in it
    data, warnings = convert(score([full, full, [("B", 4, 2)], full, full], fifths=1, time=(3, 4)))
    assert list(data["parts"]) == ["song"]
    assert data["parts"]["song"]["melody"][2] == "B2 z4"
    assert any("bar 3" in w and "padded" in w for w in warnings)
    parse(tomllib.loads(dump(data)), "x")  # builds


def test_no_intro_or_reprise_when_the_last_bar_cannot_make_room_for_the_opening_upbeat():
    full = [("G", 4, 4), ("B", 4, 2)]
    data, _ = convert(score([[("D", 4, 2)], full, full, full, full], fifths=1, time=(3, 4)))
    assert [s["name"] for s in data["sections"]] == ["song", "coda"]
    assert parse(tomllib.loads(dump(data)), "x").pickup == "D2"  # the song opens on its upbeat


def test_notes_struck_together_become_one_chord_with_the_melody_first():
    data, _ = convert(score([[("G", 4, 2), ("B", 4, 2, {"chord": True}), ("A", 4, 2)], [("G", 4, 4)]], fifths=1))
    assert data["parts"]["song"]["melody"][0] == "[BG]2 A2"


def test_ties_accidentals_grace_notes_and_second_voices():
    bar = [("D", 5, 1, {"grace": True}), ("F", 4, 2, {"alter": 1}), ("F", 4, 2, {"tie": True}), ("C", 4, 4, {"voice": 2})]
    data, _ = convert(score([bar, [("F", 4, 2, {"alter": 1}), ("G", 4, 2)]], fifths=1))
    assert data["parts"]["song"]["melody"] == ["F2 =F2-", "F2 G2"]  # grace notes and the second voice are left out


def test_short_chords_carry_their_lengths_inside_the_brackets():
    bar = [("B", 4, 0.5), ("E", 4, 0.5, {"chord": True}), ("A", 4, 0.5), ("D", 4, 0.5, {"chord": True}), ("G", 4, 3)]
    data, _ = convert(score([bar, [("G", 4, 4)]]))
    assert data["parts"]["song"]["melody"][0] == "[B/E/][A/D/]G3"  # one beat, one beam


def test_a_bar_that_overflows_with_three_equal_notes_is_read_as_a_triplet():
    data, notes = convert(score([[("A", 4, 1), ("B", 4, 1), ("C", 5, 1), ("D", 5, 2)], [("G", 4, 4)]]))
    assert data["parts"]["song"]["melody"][0] == "(3ABc d2"
    assert notes == ["song bar 1: read as triplets (3 equal notes overflowed the bar)"]
