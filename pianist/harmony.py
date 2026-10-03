"""Chord symbols -> left-hand piano figures in ABC."""

import re

from .notation import LETTERS, BarSpeller, engrave, fmt_length, pitch_class

CHORD_NAME = re.compile(r"([A-G])([#b]?)(m(?!aj)|dim|sus4)?(maj7|7)?(?:/([A-G])([#b]?))?$")
STYLES = ("flow", "rise", "octave", "hold")
RISE = [0, 1, 3, 2, 3, 1]  # bass, fifth, top, colour, top, fifth


def voicing(name: str) -> list[tuple[int, str]]:
    """(MIDI note, letter) for bass, fifth, colour (third an octave up) and top (seventh, or the octave).

    The bass sits between E2 and D#3 so every chord lands in the same comfortable register.
    """
    m = CHORD_NAME.match(name)
    if not m:
        raise ValueError(f"unknown chord {name!r}")
    letter, acc, quality, seventh, slash_letter, slash_acc = m.groups()
    root = 40 + (pitch_class(letter + acc) - 4) % 12
    third = {"m": 3, "dim": 3, "sus4": 5}.get(quality, 4)
    fifth = 6 if quality == "dim" else 7
    top = 9 if quality == "dim" and seventh == "7" else {"7": 10, "maj7": 11}.get(seventh, 12)  # dim7: diminished seventh
    step = LETTERS.index(letter)
    at = lambda n: LETTERS[(step + n) % 7]
    notes = [
        (root, letter),
        (root + fifth, at(4)),
        (root + 12 + third, at(3 if quality == "sus4" else 2)),
        (root + top, at(6) if seventh else letter),
    ]
    if slash_letter:
        notes[0] = (40 + (pitch_class(slash_letter + slash_acc) - 4) % 12, slash_letter)
    return notes


def split(eighths: int, k: int) -> list[int]:
    """Eighths per chord when k chords share a bar: equal shares, the first chord takes the remainder."""
    if eighths < k:
        raise ValueError(f"{k} chords do not fit in a bar of {eighths} eighths")
    return [eighths // k + (eighths % k if i == 0 else 0) for i in range(k)]


def left_hand(chords: str, style: str, eighths: int, beat: int, key: str) -> str:
    """One bar of left hand in ABC (L:1/8). Chord changes inside a bar get a shorter flowing figure.

    beat is the eighths per beat (2 in 2/4, 3/4, 4/4; 3 in 6/8, 9/8, 12/8) and sets how the figure is beamed.
    """
    if style not in STYLES:
        raise ValueError(f"unknown left-hand style {style!r}; use one of {', '.join(STYLES)}")
    spell = BarSpeller(key)
    names = chords.split()
    note = lambda name, i: spell(*voicing(name)[i])
    flow = lambda n: [0] + [1 if i % 2 == 0 else 2 for i in range(n - 1)]
    if len(names) > 1:
        return " ".join("".join(note(x, i) for i in flow(d)) for x, d in zip(names, split(eighths, len(names))))
    name = names[0]
    if style == "hold":
        dyad = f"[{note(name, 0)}{note(name, 1)}]"
        return "-".join(dyad + fmt_length(n) for n in engrave(eighths))  # tied when the bar is not one printable note
    if style == "rise":
        figure = [note(name, RISE[i % len(RISE)]) for i in range(eighths)]
    else:
        figure = [note(name, i) for i in flow(eighths)]
    if style == "octave":
        midi, letter = voicing(name)[0]
        figure[0] = f"[{figure[0]}{spell(midi + 12, letter)}]"
    group = beat if beat == 3 else 4 if eighths == 8 else eighths  # beam by dotted quarter, half bar in 4/4, else whole bar
    return " ".join("".join(figure[i : i + group]) for i in range(0, eighths, group))
