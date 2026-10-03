"""The performance humanize() shapes from abc2midi's flat MIDI: tempo, dynamics, voicing, rolls, pedal, timing."""

import dataclasses
import itertools
import shutil
import subprocess

import mido
import pytest

from pianist.humanize import humanize, scale_at
from pianist.score import abc
from pianist.song import parse

pytestmark = pytest.mark.skipif(not shutil.which("abc2midi"), reason="needs the nix develop toolchain")
TPB, EIGHTH = 480, 240


def song_of(melody, chords, sections, meter="4/4", tempo=60, **extra):
    data = {"title": "T", "key": "C", "meter": meter, "tempo": tempo, "parts": {"a": {"melody": melody, "chords": chords}}, "sections": sections}
    data["parts"]["a"] |= extra.pop("part", {})
    return parse(data | extra, "t")


def perform(tmp_path, song):
    (tmp_path / "score.abc").write_text(abc(song), encoding="utf-8")
    subprocess.run(["abc2midi", "score.abc", "-o", "raw.mid"], cwd=tmp_path, check=True, capture_output=True)
    humanize(song, str(tmp_path / "raw.mid"), str(tmp_path / "piano.mid"))
    return mido.MidiFile(tmp_path / "piano.mid")


def timed(track):
    return zip(itertools.accumulate(m.time for m in track), track)


def sounding(track):
    """(start, ticks it sounds, pitch, velocity) per note_on, as a synthesizer plays it: a note_off stops whatever is sounding."""
    open_, out = {}, []
    for t, m in timed(track):
        if m.type == "note_on" and m.velocity > 0:
            if m.note in open_:  # struck again while sounding
                start, vel = open_.pop(m.note)
                out.append((start, t - start, m.note, vel))
            open_[m.note] = (t, m.velocity)
        elif m.type in ("note_on", "note_off") and m.note in open_:
            start, vel = open_.pop(m.note)
            out.append((start, t - start, m.note, vel))
    return sorted(out)


def test_tempo_breathes_at_phrase_ends_and_follows_the_ritardando(tmp_path):
    song = song_of(["C8"] * 8, ["C"] * 8, [{"name": "a", "part": "a"}, {"name": "end", "part": "a", "bars": [7, 8]}], ritardando=[50, 40])
    bar, beat = 8 * EIGHTH, 2 * EIGHTH
    tempo = [(t, round(mido.tempo2bpm(m.tempo))) for t, m in timed(perform(tmp_path, song).tracks[0]) if m.type == "set_tempo"]
    assert tempo == [
        (0, 60),
        (4 * bar - beat, 54), (4 * bar, 60),  # a breath on the last beat of the 4-bar phrase
        (8 * bar - beat, 48), (8 * bar, 60),  # a longer one at the section's end
        (8 * bar, 50), (8 * bar + beat, 40),  # then the ritardando, one tempo per beat
    ]


def test_compound_meters_count_dotted_quarters_and_the_pickup_shifts_the_bar_grid(tmp_path):
    sections = [{"name": "a", "part": "a"}, {"name": "end", "part": "a", "bars": [3, 4]}]
    song = song_of(["C6"] * 4, ["C"] * 4, sections, meter="6/8", tempo=40, ritardando=[30], part={"pickup": "G"})
    tempo = [(t, round(mido.tempo2bpm(m.tempo))) for t, m in timed(perform(tmp_path, song).tracks[0]) if m.type == "set_tempo"]
    four_bars = EIGHTH + 4 * 6 * EIGHTH  # after the one-eighth pickup
    assert tempo == [(0, 60), (four_bars - 3 * EIGHTH, 48), (four_bars, 60), (four_bars, 45)]  # 40 dotted quarters = 60 quarters


def test_section_shapes_scale_the_dynamics():
    sections = [{"name": "arch", "part": "a", "shape": "arch", "dynamic": 1.0}, {"name": "fade", "part": "a", "shape": "fade", "dynamic": 0.5}]
    song = song_of(["C8"] * 8, ["C"] * 8, sections)
    arch = [scale_at(song, 0, i) for i in range(8)]
    assert arch[0] == 1.0 and max(arch) == arch[3] == pytest.approx(1.12)  # builds to the last phrase, then eases off
    assert arch[-1] < arch[3]
    assert [round(scale_at(song, 1, i), 3) for i in (0, 7)] == [0.5, 0.4]  # fades by a fifth


def test_the_melody_sings_over_its_doubling_and_the_bass_accents_the_downbeat(tmp_path):
    song = song_of(["[ec]4 [ec]4"] * 2, ["C"] * 2, [{"name": "a", "part": "a"}])
    mid = perform(tmp_path, song)
    rh = sounding(mid.tracks[1])
    melody = [v for _, _, n, v in rh if n == 76]
    inner = [v for _, _, n, v in rh if n == 72]
    assert min(melody) > max(inner) + 20
    lh = sounding(mid.tracks[2])
    mean = lambda vs: sum(vs) / len(vs)
    assert mean([v for t, _, _, v in lh if t % (8 * EIGHTH) < 20]) > mean([v for t, _, _, v in lh if t % (8 * EIGHTH) >= 20]) + 3


def test_fuller_chords_on_the_beat_roll_from_the_bottom(tmp_path):
    song = song_of(["[gec]8"] * 2, ["C"] * 2, [{"name": "a", "part": "a"}])
    starts = {n: t for t, _, n, _ in sounding(perform(tmp_path, song).tracks[1]) if t < 4 * EIGHTH}
    assert starts[72] < starts[76] < starts[79]


def test_the_pedal_lifts_at_every_harmony_change(tmp_path):
    song = song_of(["C8", "C8"], ["C", "F G"], [{"name": "a", "part": "a"}])
    mid = perform(tmp_path, song)
    for track in mid.tracks[1:]:
        pedal = [(t, m.value) for t, m in timed(track) if m.type == "control_change" and m.control == 64]
        changes = [0, 8 * EIGHTH, 12 * EIGHTH]
        assert pedal[:-1] == [p for c in changes for p in ((max(0, c - TPB // 40), 0), (c + TPB // 16, 118))]
        assert pedal[-1][1] == 0  # released after the last note


def test_repeated_notes_are_never_cut_short(tmp_path):
    song = song_of(["C2 C2 C2 C2"] * 8, ["C"] * 8, [{"name": "a", "part": "a"}])
    for seed in range(1, 6):
        mid = perform(tmp_path, dataclasses.replace(song, seed=seed))
        for track in mid.tracks[1:]:
            short = [n for n in sounding(track) if n[1] < EIGHTH * 3 // 4]  # timing moves a note a few ticks at most
            assert short == [], f"seed {seed}"


def test_the_same_seed_gives_the_same_performance(tmp_path):
    song = song_of(["C2 E2 G4"] * 2, ["C"] * 2, [{"name": "a", "part": "a"}])
    perform(tmp_path, song)
    first = (tmp_path / "piano.mid").read_bytes()
    perform(tmp_path, song)
    assert (tmp_path / "piano.mid").read_bytes() == first


def test_the_notes_of_a_chord_sound_together(tmp_path):
    song = song_of(["[ec]2 [dB]2 [ec]4"] * 4, ["C"] * 4, [{"name": "a", "part": "a"}])
    starts = {}
    for t, _, n, _ in sounding(perform(tmp_path, song).tracks[1]):
        starts.setdefault(round(t / EIGHTH), set()).add(t)
    assert all(len(ticks) == 1 for ticks in starts.values())
