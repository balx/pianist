import copy
import tomllib
from pathlib import Path

import pytest

from pianist.notation import notes
from pianist.score import abc
from pianist.song import SongError, load, parse

SAMPLE = Path(__file__).resolve().parent.parent / "songs" / "amazing-grace"


def base():
    """The sample plus a second part that borrows the verse's chords, so multi-part features are covered too."""
    data = tomllib.loads((SAMPLE / "input" / "song.toml").read_text(encoding="utf-8"))
    data["parts"]["echo"] = {"chords_from": "verse", "melody": list(data["parts"]["verse"]["melody"])}
    data["sections"].insert(3, {"name": "echo", "part": "echo", "bars": [1, 4]})
    return data


def broken(edit):
    data = copy.deepcopy(base())
    edit(data)
    return data


def test_loads_the_sample_arrangement():
    song = load(SAMPLE)
    assert [s.name for s in song.sections] == ["intro", "verse1", "verse2", "coda"]
    assert [len(s.melody) for s in song.sections] == [4, 16, 16, 4]
    assert song.sections[0].melody[0] == "g4 bg"  # verse bar 13, melody alone an octave up
    assert song.sections[1].lh == ["flow"] * 8 + ["rise"] * 8
    assert (song.eighths, song.beat) == (6, 2)


def test_borrowed_chords_follow_the_slice():
    song = parse(base(), "x")
    assert song.sections[3].chords == ["G", "G7", "C", "G"]


def test_default_ritardando_eases_down_to_half_tempo_over_the_last_section():
    assert load(SAMPLE).ritardando == [77, 73, 70, 67, 63, 60, 57, 53, 50, 47, 43, 40]


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d["parts"]["verse"]["chords"].pop(), "part verse: 16 melody bars but 15 chord entries"),
        (lambda d: d["parts"]["verse"]["chords"].__setitem__(0, "Hm"), "part verse bar 1: unknown chord 'Hm'"),
        (lambda d: d["sections"][0].__setitem__("part", "chorus"), "section intro: part 'chorus' not defined"),
        (lambda d: d["sections"][0].__setitem__("bars", [13, 17]), r"section intro: bars \[13, 17\] outside part verse \(1..16\)"),
        (lambda d: d["sections"][1].__setitem__("lh", ["flow*8", "rise*7"]), "section verse1: lh covers 15 bars but the section has 16"),
        (lambda d: d["sections"][1].__setitem__("lh", "stride"), "section verse1: unknown left-hand style 'stride"),
        (lambda d: d["sections"][4].__setitem__("shape", "arch"), "section coda: shape 'arch' needs"),
        (lambda d: d.__setitem__("meter", "5/4"), "meter '5/4' not supported"),
        (lambda d: d.__setitem__("meter", "2/4"), r"part verse bar 1: 'G4 BG' lasts 6 eighths but a 2/4 bar has 4"),
        (lambda d: d["parts"]["verse"]["melody"].__setitem__(5, "B4 A"), r"part verse bar 6: 'B4 A' lasts 5 eighths"),
        (lambda d: d["parts"]["verse"]["melody"].__setitem__(0, "G4 | BG"), "part verse bar 1: cannot read"),
        (lambda d: d["parts"]["verse"].__setitem__("pickup", "D6"), "part verse: pickup lasts 6 eighths; it must be shorter than a 3/4 bar"),
        (lambda d: d["parts"]["verse"].__setitem__("pickup", "D2 E2"), r"section verse1: no room for its pickup at the end of section intro"),
        (lambda d: d["sections"][0].__setitem__("bars", [2]), r"section intro: bars must be \[first, last\] bar numbers"),
        (lambda d: d["sections"][1].__setitem__("dynamic", "soft"), "section verse1: 'dynamic' must be a number"),
        (lambda d: d.__setitem__("seed", "x"), "song: 'seed' must be int"),
        (lambda d: d["parts"]["verse"]["melody"].__setitem__(0, 6), "part verse bar 1: must be ABC text"),
        (lambda d: d["sections"][1].__setitem__("lh", 3), "section verse1: lh must be a style name or a list of them"),
        (lambda d: d.__setitem__("ritardando", ["slow"]), "song: ritardando must be a list of numbers"),
        (lambda d: d["parts"]["verse"]["melody"].__setitem__(0, "^_G4 BG"), "part verse bar 1: cannot read"),
        (lambda d: d["parts"]["verse"]["chords"].__setitem__(0, "G C D7 Em C G D"), "part verse bar 1: 7 chords do not fit"),
        (lambda d: d["parts"]["verse"].__setitem__("chords", "Gm"), r"part verse: chords must be a list \(one entry per bar\) or \"auto\""),
        (lambda d: d.__setitem__("key", "H"), "unknown key 'H'"),
        (lambda d: d.__setitem__("soundfont", "rhodes"), "soundfont 'rhodes' unknown"),
        (lambda d: d.pop("title"), "song: missing 'title'"),
        (lambda d: d["sections"][1].__setitem__("name", "intro"), "section names must be unique"),
        (lambda d: d["parts"]["echo"].__setitem__("chords_from", "bridge"), "chords_from 'bridge' is not a part"),
        (lambda d: d.__setitem__("pickup", "D2"), r"song: pickup belongs to the part it leads into"),
        (lambda d: d["parts"]["verse"]["chords"].__setitem__(0, " "), "part verse bar 1: empty chord entry"),
        (lambda d: d["parts"].__setitem__("verse", 5), r"part verse: must be a table \(\[parts.verse\]\)"),
        (lambda d: d.__setitem__("sections", [5]), r"section 1: must be a table"),
        (lambda d: d["parts"]["echo"].__setitem__("chords_from", ["verse"]), "part echo: 'chords_from' must be str"),
        (lambda d: d["sections"][0].__setitem__("transform", ["octaves"]), "section intro: 'transform' must be text"),
        (lambda d: d["sections"][0].__setitem__("label", 3), "section intro: 'label' must be text"),
        (lambda d: d["sections"][0].__setitem__("label", 'Verse "1"'), "section intro: label .* cannot hold"),
        (lambda d: d.__setitem__("composer", 1779), "song: 'composer' must be text"),
        (lambda d: d.__setitem__("tempo", 0), "song: 'tempo' must be above 0"),
        (lambda d: d.__setitem__("ritardando", [60, 0]), "song: ritardando must be a list of numbers above 0"),
        (lambda d: d["sections"][1].__setitem__("dynamic", 0), "section verse1: 'dynamic' must be a number above 0"),
        (lambda d: d["parts"]["verse"]["melody"].__setitem__(0, '"x\nK:Eb"G4 BG'), "part verse bar 1: a bar is one line"),
    ],
)
def test_rejects_broken_song(edit, message):
    with pytest.raises(SongError, match=message):
        parse(broken(edit), "x")


@pytest.mark.parametrize("text, message", [('title = "unterminated\n', "Illegal character"), ('title = "T"\n', "missing 'key'")])
def test_errors_name_the_song_file_once(tmp_path, text, message):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "song.toml").write_text(text, encoding="utf-8")
    with pytest.raises(SongError, match=message) as e:
        load(tmp_path)
    assert str(e.value).startswith(f"{tmp_path / 'input' / 'song.toml'}: ") and str(e.value).count("song.toml") == 1


def test_the_slug_is_the_folder_name_even_for_a_relative_path(monkeypatch):
    monkeypatch.chdir(SAMPLE)
    assert load(".").slug == "amazing-grace"


@pytest.mark.parametrize("field", ["title", "composer"])
def test_text_from_the_sheet_cannot_add_score_directives(field):
    data = base()
    data[field] = "Hymn\nK:Eb 100%"
    lines = abc(parse(data, "x")).splitlines()
    assert [line for line in lines if line.startswith("K:")] == ["K:G"]
    assert any(line.startswith(("T:Hymn K:Eb 100\\%", "C:Hymn K:Eb 100\\%")) for line in lines)



def test_the_score_prints_a_held_chord_once():
    data = {"title": "T", "key": "C", "meter": "4/4", "tempo": 60,
            "parts": {"a": {"melody": ["c8"], "chords": ["F F Dm7 G7"]}}, "sections": [{"name": "a", "part": "a"}]}
    assert '"^F Dm7 G7"c8' in abc(parse(data, "x"))

def section_pitches(bar, transform, key="C"):
    data = {"title": "T", "key": key, "meter": "4/4", "tempo": 60, "parts": {"a": {"melody": [bar], "chords": ["C"]}},
            "sections": [{"name": "a", "part": "a", "transform": transform}]}
    return [n for _, _, n in notes(parse(data, "x").sections[0].melody[0], key)]


@pytest.mark.parametrize(
    "bar, transform, pitches",
    [
        ("^GA Bc de fg", "octaves", [(80, 68), (81, 69), (83, 71), (84, 72), (86, 74), (88, 76), (89, 77), (91, 79)]),
        ("[e^c]2 c2 C4", "top_voice_up", [(88,), (85,), (72,)]),
        ("[^^Ce]2 C2 _B4", "octaves", [(88, 74, 62), (74, 62), (82, 70)]),
    ],
    ids=["octaves", "top-voice", "double-sharp"],
)
def test_transforms_keep_every_pitch(bar, transform, pitches):
    assert section_pitches(bar, transform) == pitches


def test_an_upbeat_keeps_its_pitch_at_the_end_of_the_bar_before():
    data = {"title": "T", "key": "C", "meter": "4/4", "tempo": 60,
            "parts": {"a": {"pickup": "F2", "melody": ["^F2 G6"] * 2, "chords": ["C"] * 2}},
            "sections": [{"name": "one", "part": "a", "bars": [2, 2]}, {"name": "two", "part": "a"}]}
    song = parse(data, "x")
    assert song.sections[0].melody[-1] == "^F2 G4 =F2"  # F natural, not the F# earlier in the bar


def test_an_upbeat_after_another_section_goes_at_the_end_of_its_last_bar():
    song = load(SAMPLE)
    assert (song.pickup, song.pickup_eighths) == ("", 0)  # the song opens with the intro, not the verse
    assert song.sections[0].melody[-1] == "g4 D2"  # the intro's closing rest gives way to the verse's upbeat
    assert song.sections[1].melody[-1] == "G4 [dD]2"  # verse 2 is in octaves, and so is its upbeat


def test_an_upbeat_of_the_opening_section_is_an_anacrusis():
    song = parse(broken(lambda d: d["sections"].pop(0)), "x")  # verse1 opens the song
    assert (song.pickup, song.pickup_eighths) == ("D2", 2)


def test_auto_chords_are_filled_in_and_reported():
    song = parse(broken(lambda d: d["parts"]["verse"].__setitem__("chords", "auto")), "x")
    assert song.auto_chords["verse"] == song.sections[1].chords
    assert song.sections[1].chords[:4] == ["G", "G", "C", "D"]
    assert song.sections[0].chords == song.auto_chords["verse"][12:16]  # the intro is the verse's last line


@pytest.mark.parametrize(
    "bar, transform",
    [("^F2 =f2 c4", "top_voice_up"), ("^F2 =f2 c4", "octaves"), ("{^F}G2 =F2 G4", "top_voice_up"), ("{^F}G2 =F2 G4", "octaves")],
)
def test_transforms_keep_naturals_in_other_octaves_and_after_grace_notes(bar, transform):
    plain = [tuple(n + 12 for n in p) for p in section_pitches(bar, "none")]
    got = section_pitches(bar, transform)
    assert [p[0] for p in got] == [p[0] for p in plain]  # the melody, an octave up, still F#, F natural, ...


def test_the_upbeat_tidy_keeps_a_natural_in_another_octave():
    data = {"title": "T", "key": "C", "meter": "4/4", "tempo": 60,
            "parts": {"a": {"melody": ["^F2 =f2 c4"], "chords": ["C"]}, "b": {"pickup": "c", "melody": ["c8"], "chords": ["C"]}},
            "sections": [{"name": "a", "part": "a"}, {"name": "b", "part": "b"}]}
    bar = parse(data, "x").sections[0].melody[-1]
    assert [n for _, _, ns in notes(bar, "C") for n in ns] == [66, 77, 72, 72]  # F#, F natural an octave up, the upbeat
