"""Chord symbols for a melody that has none: the key's own chords, scored against the melody, linked by common progressions."""

from fractions import Fraction

from .notation import LETTERS, NATURAL, notes, pitch_class

# (scale step, semitones above the tonic, quality); index 0 is the tonic chord, 3 and 4 are V and V7.
MAJOR = [(0, 0, ""), (1, 2, "m"), (2, 4, "m"), (4, 7, ""), (4, 7, "7"), (3, 5, ""), (5, 9, "m")]  # I ii iii V V7 IV vi
MINOR = [(0, 0, "m"), (2, 3, ""), (3, 5, "m"), (4, 7, ""), (4, 7, "7"), (5, 8, ""), (6, 10, "")]  # i III iv V V7 VI VII
TONIC, DOMINANTS = 0, (3, 4)
# Bonus for moving from one chord to the next, by scale step of the roots: strong motion falls a fifth (V->I, ii->V).
FALLING_FIFTH = 0.6
STAY = 0.2


def chords_of(key: str) -> list[tuple[str, frozenset[int], int]]:
    """(name, pitch classes, scale step of the root) for the chords the harmonizer may use in this key."""
    minor = key.endswith("m")
    tonic = key[:-1] if minor else key
    step0, pc0 = LETTERS.index(tonic[0]), pitch_class(tonic)
    out = []
    for step, semis, quality in MINOR if minor else MAJOR:
        letter = LETTERS[(step0 + step) % 7]
        pc = (pc0 + semis) % 12
        acc = {1: "#", 11: "b", 0: ""}[(pc - NATURAL[LETTERS.index(letter)]) % 12]
        third = 3 if quality == "m" else 4
        tones = {pc, (pc + third) % 12, (pc + 7) % 12} | ({(pc + 10) % 12} if quality == "7" else set())
        out.append((letter + acc + quality, frozenset(tones), step))
    return out


def fit(melody, start: Fraction, end: Fraction, beat: int, tones: frozenset[int]) -> float:
    """How well a chord fits the written notes between start and end.

    Chord tones count and other notes cost; strong beats weigh more, and the melody note counts double an inner voice.
    """
    score = 0.0
    for at, dur, midis in melody:
        overlap = min(at + dur, end) - max(at, start)
        if overlap <= 0:
            continue
        weight = 2.0 if at == start else 1.5 if (at - start) % beat == 0 else 1.0
        for v, midi in enumerate(midis):
            score += float(overlap) * weight * (1.0 if v == 0 else 0.5) * (1.0 if midi % 12 in tones else -0.7)
    return score


def harmonize(bars: list[str], key: str, eighths: int, beat: int) -> list[str]:
    """One chord-symbol entry per bar ("C" or "C G" for a change at the half bar in 4/4 and 12/8)."""
    palette = chords_of(key)
    halves = eighths in (8, 12)
    span = eighths // 2 if halves else eighths
    segments = []  # (bar index, melody notes, start, end)
    for b, bar in enumerate(bars):
        melody = notes(bar, key)
        for s in range(2 if halves else 1):
            segments.append((b, melody, Fraction(s * span), Fraction((s + 1) * span)))
    n = len(segments)

    def local(k: int, c: int) -> float:
        b, melody, start, end = segments[k]
        name, tones, _ = palette[c]
        score = fit(melody, start, end, beat, tones)
        if name.endswith("7"):
            score -= 0.4  # a plain V unless the melody sings the seventh
        if k == 0 and c == TONIC:
            score += 1.0
        if k == n - 1:
            score += 3.0 if c == TONIC else -3.0
        if k == n - 2 and c in DOMINANTS:
            score += 1.0
        if end == span * (2 if halves else 1) and b % 4 == 3 and k < n - 1 and (c == TONIC or c in DOMINANTS):
            score += 0.8  # phrase ends on a full or half cadence
        return score

    def move(a: int, c: int) -> float:
        if a == c:
            return STAY
        if (palette[a][2] - palette[c][2]) % 7 == 4:
            return FALLING_FIFTH + (0.4 if a == 4 and c == TONIC else 0)  # V7 -> I resolves best
        return 0.0

    best = [[local(0, c) for c in range(len(palette))]]
    back = []
    for k in range(1, n):
        row, links = [], []
        for c in range(len(palette)):
            a = max(range(len(palette)), key=lambda a: best[-1][a] + move(a, c))
            row.append(best[-1][a] + move(a, c) + local(k, c))
            links.append(a)
        best.append(row)
        back.append(links)
    path = [max(range(len(palette)), key=lambda c: best[-1][c])]
    for links in reversed(back):
        path.append(links[path[-1]])
    names = [palette[c][0] for c in reversed(path)]

    out = []
    for b in range(len(bars)):
        bar = names[b * 2 : b * 2 + 2] if halves else [names[b]]
        out.append(bar[0] if len(set(bar)) == 1 else " ".join(bar))
    return out
