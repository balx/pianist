"""ABC pitch text: octave shifts, voice extraction, key signatures and spelling MIDI notes as ABC."""

import re
from fractions import Fraction

PITCH_TEXT = r"[_^=]*[A-Ga-g][,']*"  # one ABC pitch: accidentals, letter, octave marks
PITCH = re.compile(r"([_^=]*)([A-Ga-g])([,']*)")
CHORD = re.compile(r"\[([^\]]+)\]")
NOTE = re.compile(rf"({PITCH_TEXT})([\d/]*)")  # pitch + optional length written inside a chord

LETTERS = "CDEFGAB"
NATURAL = [0, 2, 4, 5, 7, 9, 11]
# Sharps (+) or flats (-) in the signature, by ABC key name.
FIFTHS = {
    "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7, "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7,
    "Am": 0, "Em": 1, "Bm": 2, "F#m": 3, "C#m": 4, "G#m": 5, "D#m": 6, "A#m": 7, "Dm": -1, "Gm": -2, "Cm": -3, "Fm": -4, "Bbm": -5, "Ebm": -6, "Abm": -7,
}
MARK = {-2: "__", -1: "_", 0: "=", 1: "^", 2: "^^"}
ACCIDENTAL = {mark: alter for alter, mark in MARK.items()}


def pitch_class(name: str) -> int:
    """'C' 0, 'F#' 6, 'Bb' 10: a letter with an optional # or b."""
    return (NATURAL[LETTERS.index(name[0])] + {"#": 1, "b": -1, "": 0}[name[1:]]) % 12


PROTECTED = re.compile(r'("[^"]*"|![^!]*!|\{[^}]*\})')  # text annotations, decorations, grace notes


def outside(fn, grace=None):
    """Apply a bar transform to the notes only: text and decorations pass through, grace notes through grace (if given)."""

    def apply(bar: str) -> str:
        parts = PROTECTED.split(bar)
        return "".join(fn(p) if i % 2 == 0 else grace(p) if grace and p.startswith("{") else p for i, p in enumerate(parts))

    return apply


def octave(abc: str, n: int) -> str:
    """Move every ABC pitch in the string by n octaves."""

    def move(m):
        acc, letter, marks = m.groups()
        level = _level(letter, marks) + n
        return acc + (letter.lower() + "'" * (level - 1) if level >= 1 else letter.upper() + "," * -level)

    return PITCH.sub(move, abc)


def top_voice(bar: str) -> str:
    """Keep only the first (highest written) note of each chord: the melody."""
    return CHORD.sub(lambda m: "".join(NOTE.findall(m.group(1))[0]), bar)


def melody_in_octaves(bar: str) -> str:
    """[X Y] -> [Y' X' X]: melody doubled an octave up with the written harmony as the inner voice; X -> [X' X]."""

    def chord(m):
        notes = NOTE.findall(m.group(1))  # written melody first
        length = notes[0][1]
        up = [octave(p, 1) + length for p, _ in reversed(notes)]
        return "[" + "".join(up) + notes[0][0] + length + "]"

    parts = re.split(r"(\[[^\]]*\])", bar)
    return "".join(
        CHORD.sub(chord, p) if p.startswith("[") else PITCH.sub(lambda m: f"[{octave(m.group(0), 1)}{m.group(0)}]", p)
        for p in parts
    )


def _level(letter: str, marks: str) -> int:
    """Octave of an ABC pitch: 0 for C..B (middle C up), 1 for c..b, plus ' and minus , marks."""
    return (1 if letter.islower() else 0) + marks.count("'") - marks.count(",")


def accidentals(bar: str, key: str, explicit: bool) -> str:
    """Write every pitch's accidental out (explicit), or only the ones the key and the bar so far do not imply.

    Grace notes are left as written, but their accidentals carry on through the bar, as abc2midi plays them.
    """
    sig, seen = signature(key), {}

    def mark(m):
        acc, letter, marks = m.groups()
        place = (letter.upper(), _level(letter, marks))
        current = seen.get(place, sig[letter.upper()])
        alter = seen[place] = ACCIDENTAL[acc] if acc else current
        return (MARK[alter] if explicit or alter != current else "") + letter + marks

    def grace(g: str) -> str:
        PITCH.sub(mark, g)
        return g

    return outside(lambda notes: PITCH.sub(mark, notes), grace=grace)(bar)


def respell(transform):
    """A bar transform that may move or drop notes, made safe for accidentals: every pitch keeps its sound."""
    return lambda bar, key: accidentals(transform(accidentals(bar, key, True)), key, False)


def signature(key: str) -> dict[str, int]:
    """Letter -> alteration (+1 sharp, -1 flat) that the key signature applies."""
    if key not in FIFTHS:
        raise ValueError(f"unknown key {key!r}; use one of {', '.join(FIFTHS)}")
    n = FIFTHS[key]
    order = "FCGDAEB" if n > 0 else "BEADGCF"
    return {letter: (1 if n > 0 else -1) if letter in order[: abs(n)] else 0 for letter in LETTERS}


class BarSpeller:
    """Spells MIDI notes as ABC within one bar, writing an accidental only where the key and earlier notes need one."""

    def __init__(self, key: str):
        self.sig = signature(key)
        self.seen: dict[tuple[str, int], int] = {}  # accidentals carry to the end of the bar, per letter and octave

    def __call__(self, midi: int, letter: str) -> str:
        step = LETTERS.index(letter)
        octave_no = (midi - NATURAL[step]) // 12 - 1
        acc = midi - 12 * (octave_no + 1) - NATURAL[step]  # 0..11
        if acc > 2:  # a flat: Cb4 sounds as B3 but is written in octave 4
            octave_no, acc = octave_no + 1, acc - 12
        if acc < -2:
            raise ValueError(f"cannot spell MIDI {midi} as {letter}")
        current = self.seen.get((letter, octave_no), self.sig[letter])
        mark = "" if acc == current else MARK[acc]
        self.seen[(letter, octave_no)] = acc
        level = octave_no - 4  # C4 (middle C) is "C", C5 is "c"
        return mark + (letter.lower() + "'" * (level - 1) if level >= 1 else letter + "," * -level)


TOKEN = re.compile(
    r"""(?P<skip>\s+|"[^"]*"|![^!]*!|\{[^}]*\}|[.~)\-])"""
    r"""|\((?P<tuplet>\d)"""
    r"""|(?P<slur>\()"""
    r"""|(?P<broken>[<>]+)"""
    r"""|(?P<chord>\[[^\]]+\])(?P<chord_len>[\d/]*)"""
    rf"""|(?P<note>{PITCH_TEXT}|[zx])(?P<note_len>[\d/]*)"""
)
TUPLET_SPACE = {2: 3, 3: 2, 4: 3, 6: 2, 8: 3}  # (p: p notes in the time of q (simple meters)


def length(text: str) -> Fraction:
    """ABC length suffix -> multiple of the unit note: "" 1, "3" 3, "/" 1/2, "//" 1/4, "3/2" 3/2."""
    m = re.fullmatch(r"(\d*)((?:/\d*)*)", text)
    if not m:
        raise ValueError(f"bad note length {text!r}")
    value = Fraction(int(m.group(1) or 1))
    for part in re.findall(r"/(\d*)", m.group(2)):
        value /= int(part or 2)
    return value


def notes(bar: str, key: str) -> list[tuple[Fraction, Fraction, tuple[int, ...]]]:
    """(start, duration, MIDI notes) for one bar of ABC, in eighths (L:1/8); a rest has no notes.

    Chord notes keep their written order, so the melody note comes first. Accidentals follow ABC rules: the key signature,
    then any accidental earlier in the bar on the same letter and octave.
    """
    if re.search(r"[\n\r%]", bar):
        raise ValueError(f"a bar is one line of ABC without %: {bar!r}")
    sig = signature(key)
    seen: dict[tuple[str, int], int] = {}
    out: list[list] = []
    at, pos, tuplet, broken = Fraction(0), 0, None, None

    def pitch(token: str) -> int | None:
        acc, letter, marks = PITCH.fullmatch(token).groups()
        if acc and acc not in ACCIDENTAL:
            raise ValueError(f"cannot read accidental {acc!r} in bar {bar!r}")
        level = _level(letter, marks)
        place = (letter.upper(), level)
        if acc:
            seen[place] = ACCIDENTAL[acc]
        alter = seen.get(place, sig[letter.upper()])
        return 60 + 12 * level + NATURAL[LETTERS.index(letter.upper())] + alter

    while pos < len(bar):
        m = TOKEN.match(bar, pos)
        if not m:
            raise ValueError(f"cannot read {bar[pos:]!r} in bar {bar!r}")
        pos = m.end()
        if m.group("skip") or m.group("slur"):
            if (m.group("skip") or "").startswith("{"):  # a grace note's accidental carries on through the bar
                for g in PITCH.finditer(m.group("skip")):
                    pitch(g.group(0))
            continue
        if m.group("tuplet"):
            p = int(m.group("tuplet"))
            tuplet = [Fraction(TUPLET_SPACE.get(p, 2), p), p]
            continue
        if m.group("broken"):
            broken = m.group("broken")
            continue
        if m.group("chord"):
            inner = NOTE.findall(m.group("chord")[1:-1])
            if not inner:
                raise ValueError(f"empty chord in bar {bar!r}")
            midi = tuple(pitch(p_) for p_, _ in inner)
            dur = length(inner[0][1]) * length(m.group("chord_len"))
        else:
            token = m.group("note")
            midi = () if token in "zx" else (pitch(token),)
            dur = length(m.group("note_len"))
        if tuplet:
            dur *= tuplet[0]
            tuplet[1] -= 1
            if tuplet[1] == 0:
                tuplet = None
        if broken and out:
            k = Fraction(1, 2 ** len(broken))
            prev = out[-1]
            grow = prev[1] * (1 - k) if broken[0] == ">" else -prev[1] * (1 - k)
            prev[1] += grow
            at += grow
            dur -= grow
            broken = None
        out.append([at, dur, midi])
        at += dur
    return [tuple(n) for n in out]


def bar_length(bar: str, key: str) -> Fraction:
    """Total length of one bar of ABC, in eighths."""
    return sum((d for _, d, _ in notes(bar, key)), Fraction(0))


ENGRAVE = {1: [1], 2: [2], 3: [3], 4: [4], 5: [4, 1], 6: [6], 7: [6, 1], 8: [8], 9: [6, 3], 10: [8, 2], 11: [8, 3], 12: [12]}


def engrave(n: Fraction) -> list[Fraction]:
    """Split a length in eighths into values a score prints as single notes: 5 -> 4 + 1, 9 -> 6 + 3."""
    whole, part = int(n), Fraction(n) - int(n)
    out = []
    while whole > 12:
        out.append(12)
        whole -= 12
    out += ENGRAVE.get(whole, [])
    return [Fraction(x) for x in out] + ([part] if part else [])


def fmt_length(n: Fraction) -> str:
    """ABC length suffix for n eighths (L:1/8), as written by hand: "", "2", "3/2", "/", "//"."""
    n = Fraction(n)
    short = {1: "", Fraction(1, 2): "/", Fraction(1, 4): "//"}
    return short[n] if n in short else str(n.numerator) if n.denominator == 1 else f"{n.numerator}/{n.denominator}"


def make_room(bar: str, room: Fraction) -> str | None:
    """Shorten the bar's last note, chord or rest by room eighths, to make space for an upbeat.

    A rest exactly room long gives way entirely. None when it is not possible: the last note is not longer than room,
    or sits in a tuplet or broken rhythm.
    """
    last, pos, in_tuplet, broken = None, 0, 0, False
    while pos < len(bar):
        m = TOKEN.match(bar, pos)
        if not m:
            return None
        pos = m.end()
        if m.group("tuplet"):
            in_tuplet = int(m.group("tuplet"))
        elif m.group("broken"):
            broken, last = True, None
        elif m.group("note") or m.group("chord"):
            last = None if in_tuplet or broken else m
            in_tuplet, broken = max(in_tuplet - 1, 0), False
    if last is None:
        return None
    if last.group("chord"):
        if any(n for _, n in NOTE.findall(last.group("chord")[1:-1])):
            return None  # lengths written inside the chord
        text, dur = last.group("chord"), length(last.group("chord_len"))
    else:
        text, dur = last.group("note"), length(last.group("note_len"))
    rest = text in ("z", "x")
    if dur < room or (dur == room and not rest):
        return None
    if dur == room:
        return (bar[: last.start()] + bar[last.end() :]).strip()
    joint = " " if rest else "-"  # rests sit side by side, notes are tied
    return bar[: last.start()] + joint.join(text + fmt_length(n) for n in engrave(dur - room)) + bar[last.end() :]
