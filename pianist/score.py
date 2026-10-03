"""Song -> two-staff ABC score (the source for both the printed score and the MIDI)."""

from itertools import groupby

from .harmony import left_hand
from .notation import engrave, fmt_length
from .song import Song


def text(s: str) -> str:
    """Free text on one ABC line: no line breaks, which would start new header fields, and % escaped (a comment)."""
    return " ".join(s.split()).replace("%", "\\%")


def abc(song: Song) -> str:
    rh, lh = [], []
    for _, i, section in song.bars():
        label = f'"^{text(section.label)}"' if i == 0 else ""
        shown = " ".join(c for c, _ in groupby(section.chords[i].split()))  # "F F Dm7 G7" times the changes; print "F Dm7 G7"
        rh.append(f'{label}"^{shown}"{section.melody[i]}')  # annotations, so abc2midi doesn't play the chords
        lh.append(left_hand(section.chords[i], section.lh[i], song.eighths, song.beat, song.key))
    lines = lambda b: " |\n".join(" | ".join(b[i : i + 4]) for i in range(0, len(b), 4)) + " |]"
    rh_text, lh_text = lines(rh), lines(lh)
    if song.pickup:  # the anacrusis sits before the first full bar; the left hand rests under it
        rest = " ".join("z" + fmt_length(n) for n in engrave(song.pickup_eighths))
        rh_text, lh_text = f"{song.pickup} | {rh_text}", f"{rest} | {lh_text}"
    tempo = f"3/8={song.tempo}" if song.beat == 3 else f"1/4={song.tempo}"
    composer = f"{song.composer} - piano arrangement" if song.composer else "piano arrangement"
    return f"""X:1
T:{text(song.title)}
C:{text(composer)}
M:{song.meter}
L:1/8
Q:{tempo}
K:{song.key}
%%propagate-accidentals octave
%%score {{RH | LH}}
V:RH clef=treble
V:LH clef=bass
%%MIDI program 0
[V:RH]
%%MIDI chordattack 0
{rh_text}
[V:LH]
%%MIDI chordattack 0
{lh_text}
"""
