"""MusicXML (from optical music recognition) -> song data: the melody line as ABC bars, key, meter and a default form."""

import re
import xml.etree.ElementTree as ET
from fractions import Fraction

from .notation import (
    FIFTHS,
    PITCH_TEXT,
    BarSpeller,
    engrave,
    fmt_length,
    make_room,
    pitch_class,
)
from .song import METERS
from .songfile import default_form

BY_LENGTH = {eighths: meter for meter, (eighths, _) in METERS.items() if meter != "6/8"}  # no time signature: 6 eighths is 3/4


def major_of(fifths: int) -> str:
    return next(k for k, n in FIFTHS.items() if n == fifths and not k.endswith("m"))


def guess_key(fifths: int, last: int) -> str:
    """The key signature names a major key and its relative minor; the final melody note decides which."""
    major = major_of(fifths)
    minor = next(k for k, n in FIFTHS.items() if n == fifths and k.endswith("m"))
    return minor if last % 12 == pitch_class(minor[:-1]) else major


def fix_triplets(events: list[tuple], expected: Fraction) -> list[tuple] | None:
    """OMR often misses triplet brackets, so the bar overflows. Mark runs of 3 equal notes as triplets until it fits.

    Events are (eighths, text, ...); a marked run starts with "(3" and keeps its written lengths. None if nothing fits.
    """
    events = [tuple(e) for e in events]
    total = sum(e[0] for e in events)
    if total <= expected:
        return None
    i = 0
    while total > expected and i + 3 <= len(events):
        run = events[i : i + 3]
        if len({e[0] for e in run}) == 1 and run[0][1] != "z" and total - run[0][0] >= expected:
            events[i] = (run[0][0], "(3" + run[0][1], *run[0][2:])
            total -= run[0][0]
            i += 3
        else:
            i += 1
    return events if total == expected else None


def _write(events: list[tuple], beat: int) -> str:
    """Events (eighths, text, tied) -> one ABC bar, beamed by beat (no space inside a beat, rests apart)."""
    out, at, prev = "", Fraction(0), None
    in_triplet = 0
    for dur, text, tied in events:
        if text.startswith("(3"):
            in_triplet = 3
        real = dur * Fraction(2, 3) if in_triplet else dur
        if text.lstrip("(3").startswith("[") and dur < 1:  # short chord: lengths inside, like [B/E/]
            body = text[:-1].replace("]", "")
            token = "(3" * text.startswith("(3") + "[" + "".join(p + fmt_length(dur) for p in re.findall(PITCH_TEXT, body.lstrip("(3["))) + "]"
        else:
            token = "-".join(text + fmt_length(p) for p in engrave(dur)) if dur > 1 and len(engrave(dur)) > 1 else text + fmt_length(dur)
        token += "-" if tied else ""
        same_beat = prev is not None and int(at // beat) == int(prev // beat) and text != "z" and not out.endswith("z")
        out += ("" if same_beat or not out else " ") + token
        prev, at = at, at + real
        in_triplet = max(in_triplet - 1, 0)
    return out


def _measures(root) -> tuple[list, int | None, tuple | None, list]:
    """Voice 1 of the first part, bar by bar: [eighths, [(midi, letter)], tied] per note, chord or rest; no grace notes.

    Also the first key signature (fifths), the time signature, and later key changes as (score bar index, fifths).
    """
    part = root.find("part")
    if part is None:
        raise ValueError("the MusicXML has no part: the reader found no staff")
    divisions, fifths, time = 1, None, None
    changes, raw = [], []
    for measure in part.findall("measure"):
        bar = []
        for el in measure:
            if el.tag == "attributes":
                divisions = int(el.findtext("divisions", divisions))
                if el.find("key/fifths") is not None:
                    new = int(el.findtext("key/fifths"))
                    if fifths is None:
                        fifths = new
                    elif new != fifths:
                        changes.append((len(raw), new))
                if el.find("time/beats") is not None and time is None:
                    time = (int(el.findtext("time/beats")), int(el.findtext("time/beat-type")))
            elif el.tag == "note":
                if el.findtext("voice", "1") != "1" or el.find("grace") is not None:
                    continue
                pitch = el.find("pitch")
                note = []
                if pitch is not None:
                    step, octave, alter = pitch.findtext("step"), int(pitch.findtext("octave")), int(float(pitch.findtext("alter", "0")))
                    note = [(12 * (octave + 1) + pitch_class(step) + alter, step)]
                tied = any(t.get("type") == "start" for t in el.findall("tie"))
                if el.find("chord") is not None and bar:
                    bar[-1][1] += note
                    continue
                bar.append([Fraction(int(el.findtext("duration")), divisions) * 2, note, tied])
        if bar:
            raw.append(bar)
    if not raw:
        raise ValueError("the reader found no notes")
    return raw, fifths, time, changes


def _meter(time: tuple | None, lengths: list[Fraction]) -> str:
    meter = f"{time[0]}/{time[1]}" if time else None
    if meter not in METERS:  # not read, or not supported: go by the most common bar length
        common = max(set(lengths), key=lengths.count)
        meter = BY_LENGTH.get(int(common)) if common == int(common) else None
    if meter is None:
        raise ValueError(f"time signature {time} is not supported ({' '.join(METERS)})")
    return meter


def _spell(raw: list, key: str, eighths: int) -> tuple[list, list, list]:
    """Bars of (eighths, ABC text, tied) events, the length of each bar, and the score bars repaired as triplets."""
    bars, lengths, triplets = [], [], []
    for n, b in enumerate(raw, 1):
        spell = BarSpeller(key)
        events = []
        for dur, pitches, tied in b:
            written = [spell(m, letter) for m, letter in sorted(pitches, reverse=True)]  # melody (highest) first
            text = "z" if not written else written[0] if len(written) == 1 else "[" + "".join(written) + "]"
            events.append((dur, text, tied))
        fixed = fix_triplets(events, Fraction(eighths))
        if fixed:
            events = fixed
            triplets.append(n)
        bars.append(events)
        lengths.append(Fraction(eighths) if fixed else sum(e[0] for e in events))
    return bars, lengths, triplets


def _parts(bars: list, lengths: list, meter: str, opening: str | None, opening_len: Fraction) -> tuple[list, dict, list]:
    """Splits the bars into parts at short bars mid-score (the next part's upbeat) and pads the other short bars.

    Returns the parts ({"pickup", "melody"}), where each score bar went (score bar -> (part index, bar in part; 0 = its
    upbeat)) and what was repaired ((score bar, message with {part<i>} placeholders)).
    """
    eighths, beat = METERS[meter]
    found = [{"pickup": opening, "melody": []}]
    place, issues = {}, []
    for n, (events, total) in enumerate(zip(bars, lengths), 1):
        last = n == len(bars)
        upbeat = total < eighths and not last and found[-1]["melody"]  # a short bar mid-score: the upbeat of the next part,
        if upbeat and make_room(found[-1]["melody"][-1], total) is None:  # if the bar before can make room to play it in
            issues.append((n, f"read as {total} eighths; padded with a rest (an upbeat, but the bar before ends on too short a note to lead into it)"))
            upbeat = False
        if upbeat:
            found.append({"pickup": _write(events, beat), "melody": []})
            place[n] = (len(found) - 1, 0)
            issues.append((n, f"only {total} eighths; read as the upbeat of {{part{len(found) - 1}}} (a new part)"))
            continue
        if total < eighths:
            events = events + [(Fraction(eighths) - total, "z", False)]
            if not (last and opening and total + opening_len == eighths):  # a last bar completing the opening upbeat is expected
                issues.append((n, f"read as {total} eighths; padded with a rest"))
        elif total > eighths:
            issues.append((n, f"read as {total} eighths, more than a {meter} bar; check it against the sheet"))
        found[-1]["melody"].append(_write(events, beat))
        place[n] = (len(found) - 1, len(found[-1]["melody"]))
    return found, place, issues


def convert(xml: str, title: str = "") -> tuple[dict, list[str]]:
    """MusicXML text -> (song data for song.toml, warnings about bars that needed repair)."""
    root = ET.fromstring(xml)
    raw, fifths, time, changes = _measures(root)
    meter = _meter(time, [sum(e[0] for e in b) for b in raw])
    eighths, beat = METERS[meter]
    final = next((e[1] for b in reversed(raw) for e in reversed(b) if e[1]), None)
    if final is None:
        raise ValueError("the reader found no notes, only rests")
    key = guess_key(fifths or 0, max(m for m, _ in final))  # one key per song: the first signature
    bars, lengths, triplets = _spell(raw, key, eighths)

    opening, opening_len = None, Fraction(0)
    if len(bars) > 1 and lengths[0] < eighths:  # a short first bar is an upbeat
        opening, opening_len = _write(bars.pop(0), beat), lengths.pop(0)
        triplets = [t - 1 for t in triplets]
        changes = [(n - 1, f) for n, f in changes]
    found, place, issues = _parts(bars, lengths, meter, opening, opening_len)
    names = ["song"] if len(found) == 1 else [f"part{i}" for i in range(1, len(found) + 1)]

    def where(n: int) -> str:
        """Score bar n as counted on the sheet, plus where it lives in song.toml when there are several parts."""
        p, k = place.get(n, (0, 0))
        return str(n) if len(names) == 1 or k == 0 else f"{n} ({names[p]} bar {k})"

    def bars_text(ns: list[int]) -> str:
        return f"song bar{'s' if len(ns) > 1 else ''} {', '.join(where(n) for n in ns)}"

    notes = []
    if triplets:
        notes.append(f"{bars_text(triplets)}: read as triplets (3 equal notes overflowed the bar)")
    for n, message in issues:
        notes.append(f"{bars_text([n])}: " + message.format(**{f"part{i}": name for i, name in enumerate(names)}))
    for n, new in changes:
        notes.append(f"{bars_text([n + 1])}: the key signature changes to {major_of(new)} major (or its relative minor); "
                     f"pianist keeps one key per song ({key}), so the bars after it are written with accidentals - check them")
    parts = {name: ({"pickup": f["pickup"]} if f["pickup"] else {}) | {"melody": f["melody"], "chords": "auto"} for name, f in zip(names, found)}
    data = {
        "title": title or root.findtext("work/work-title", "Untitled"),
        "composer": "",
        "key": key,
        "meter": meter,
        "tempo": 50 if beat == 3 else 72,
        "seed": 1,
        "soundfont": "salamander",
        "parts": parts,
        # The intro and the reprise lead into the first part, so its upbeat must fit at the end of the song's last bar.
        "sections": default_form({name: len(p["melody"]) for name, p in parts.items()}, frame=not opening or make_room(found[-1]["melody"][-1], opening_len) is not None),
    }
    return data, notes
