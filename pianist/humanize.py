"""abc2midi's flat MIDI -> an expressive performance: tempo breathing, phrase dynamics, voicing, rolled chords, pedal."""

import random
from itertools import accumulate, pairwise

import mido

from .harmony import split
from .song import Song


def scale_at(song: Song, s: int, i: int) -> float:
    """Velocity scale for bar i of section s."""
    section = song.sections[s]
    n, scale = len(section.melody), section.dynamic
    if section.shape == "arch":  # build towards the last phrase, ease off over it
        peak, ease = n - 5, n - 4
        scale *= 1 + 0.12 * min(i, peak) / peak - (0.1 * (i - ease) / 3 if i >= ease else 0)
    if section.shape == "fade":
        scale *= 1 - 0.2 * i / (n - 1)
    return scale


def humanize(song: Song, src: str, dst: str) -> None:
    random.seed(song.seed)
    mid = mido.MidiFile(src)
    tpb = mid.ticks_per_beat
    eighth = tpb // 2
    bar = song.eighths * eighth
    beat = song.beat * eighth
    start = int(song.pickup_eighths * eighth)  # first full bar
    qpm = lambda bpm: bpm * song.beat / 2  # song tempo (per beat) -> MIDI tempo (per quarter note)
    plan = list(song.bars())
    n = len(plan)
    bar_at = lambda t: plan[min(max((t - start) // bar, 0), n - 1)]
    on_grid = lambda t, unit: (t - start) % unit <= 2  # abc2midi starts notes a tick late

    changes = []  # harmony changes, for the pedal
    for b, (s, i, section) in enumerate(plan):
        at = 0
        for d in split(song.eighths, len(section.chords[i].split())):
            changes.append(start + b * bar + at)
            at += d * eighth

    # Tempo: a breath on the last beat of every 4-bar phrase, longer at section ends, ritardando through the last section.
    # ponytail: phrases are fixed at 4 bars; add a per-section phrase length when a song needs 3- or 5-bar phrases
    last = len(song.sections[-1].melody)
    tempo = [(0, qpm(song.tempo))]
    for b, (s, i, section) in enumerate(plan[: n - last]):
        end = i == len(section.melody) - 1
        if i % 4 == 3 or end:
            tempo += [(start + b * bar + bar - beat, qpm(song.tempo * (0.8 if end else 0.9))), (start + (b + 1) * bar, qpm(song.tempo))]
    tempo += [(start + (n - last) * bar + k * beat, qpm(bpm)) for k, bpm in enumerate(song.ritardando)]

    out = mido.MidiFile(ticks_per_beat=tpb)
    for ti, track in enumerate(mid.tracks):
        events = [[t, m] for t, m in zip(accumulate(m.time for m in track), track)]
        if ti == 0:
            events = [e for e in events if e[1].type != "set_tempo"]
            events += [[t, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))] for t, bpm in tempo]
        rh, left = ti == 1, ti == 2  # abc2midi: track 0 tempo, then one track per voice (%%score RH | LH)
        if rh or left:
            lead = -tpb // 60 if rh else 0  # the melody arrives a touch before the accompaniment
            groups, shift = {}, {}  # notes struck together; id(note_on) -> ticks it moves
            for e in events:
                if e[1].type == "note_on" and e[1].velocity > 0:
                    groups.setdefault(e[0], []).append(e)
            for t, group in groups.items():
                s, i, _ = bar_at(t)
                scale = scale_at(song, s, i)
                group.sort(key=lambda e: e[1].note)
                for j, (_, m) in enumerate(group):
                    if rh:
                        base = 78 if j == len(group) - 1 else 48  # melody sings over doubling and inner voice
                    else:
                        base = (58 if j == 0 else 42) + (5 if on_grid(t, bar) else 0)
                    m.velocity = max(16, min(112, int(base * scale + random.uniform(-3, 3))))
                roll = rh and len(group) >= 3 and on_grid(t, beat)  # roll fuller chords on the beat, bottom to top
                late = lead + random.randint(-tpb // 80, tpb // 80)  # one timing per chord, so its notes sound together
                for j, e in enumerate(group):
                    shift[id(e)] = late + (j * tpb // 40 if roll else 0)
            sounding, played = {}, {}  # pitch -> note_ons not yet ended; pitch -> [(note_on, note_off)]
            for e in events:
                m = e[1]
                if m.type == "note_on" and m.velocity > 0:
                    e[0] = max(0, e[0] + shift[id(e)])
                    sounding.setdefault(m.note, []).append(e)
                elif m.type in ("note_on", "note_off") and sounding.get(m.note):
                    on = sounding[m.note].pop(0)
                    e[0] = max(on[0] + 1, e[0] + shift[id(on)])  # the end moves with the start: the note keeps its length
                    played.setdefault(m.note, []).append((on, e))
            for notes in played.values():  # a repeated note must not be stopped by the end of the one before it
                for (prev, off), (on, _) in pairwise(notes):
                    off[0] = max(prev[0] + 1, min(off[0], on[0]))
            # pedal, for both hands: lift at each harmony change, catch it just after
            channel = next((m.channel for _, m in events if m.type == "note_on"), None)
            if channel is None:  # a hand that only rests
                channel = 0 if rh else 1
            pedal = lambda value, channel=channel: mido.Message("control_change", control=64, value=value, channel=channel)
            for c in changes:
                events += [[max(0, c - tpb // 40), pedal(0)], [c + tpb // 16, pedal(118)]]
            events.append([max(e[0] for e in events) + 3 * tpb, pedal(0)])
        # at the same tick: lift the pedal, then end notes, then start new ones
        order = lambda m: 0 if m.type == "control_change" and m.value == 0 else 1 if m.type == "note_off" or (m.type == "note_on" and m.velocity == 0) else 2
        events.sort(key=lambda e: (e[0], order(e[1])))
        new, prev = mido.MidiTrack(), 0
        for t, m in events:
            if m.type != "end_of_track":
                new.append(m.copy(time=t - prev))
                prev = t
        out.tracks.append(new)
    out.save(dst)
