"""songs/<slug>/input/song.toml -> a validated Song: the transcription plus how to arrange it."""

import re
import tomllib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .harmonize import harmonize
from .harmony import STYLES, split, voicing
from .notation import (
    accidentals,
    bar_length,
    make_room,
    melody_in_octaves,
    octave,
    outside,
    respell,
    signature,
    top_voice,
)

SOUNDFONTS = ("salamander", "upright")
METERS = {"2/4": (4, 2), "3/4": (6, 2), "4/4": (8, 2), "6/8": (6, 3), "9/8": (9, 3), "12/8": (12, 3)}  # (eighths per bar, per beat)
TRANSFORMS = {  # (bar, key) -> bar; text, decorations and grace notes are never rewritten, and every note keeps its pitch
    "none": lambda bar, key: bar,
    "top_voice_up": respell(outside(lambda bar: octave(top_voice(bar), 1), grace=lambda g: octave(g, 1))),  # melody alone, an octave up
    "octaves": respell(outside(melody_in_octaves)),
}
SHAPES = ("flat", "arch", "fade")


@dataclass(frozen=True)
class Section:
    name: str
    label: str
    melody: list[str]  # right hand, one ABC string per bar
    chords: list[str]  # one entry per bar; "G F E7" = changes inside the bar
    lh: list[str]  # left-hand style per bar
    dynamic: float  # velocity scale
    shape: str  # dynamic curve across the section


@dataclass(frozen=True)
class Song:
    slug: str
    title: str
    composer: str
    key: str
    meter: str
    tempo: int
    seed: int
    soundfont: str
    ritardando: list[float]  # BPM per beat through the last section
    sections: list[Section]
    pickup: str = ""  # ABC notes before the first full bar (anacrusis), from the opening section's part
    pickup_eighths: Fraction = Fraction(0)
    auto_chords: dict = None  # part name -> chords the harmonizer chose, for the user to review

    @property
    def eighths(self) -> int:
        return METERS[self.meter][0]

    @property
    def beat(self) -> int:
        """Eighths per beat: 2 in simple meters, 3 (a dotted quarter) in compound ones."""
        return METERS[self.meter][1]

    def bars(self):
        """(section index, bar index in section, section) for every bar of the arrangement."""
        for s, section in enumerate(self.sections):
            for i in range(len(section.melody)):
                yield s, i, section


class SongError(ValueError):
    pass


def _expand(lh, n: int, where: str) -> list[str]:
    """"flow" -> n x flow; ["flow*8", "rise*8"] -> 16 styles."""
    if isinstance(lh, str):
        lh = [f"{lh}*{n}"]
    if not isinstance(lh, list) or not all(isinstance(x, str) for x in lh):
        raise SongError(f"{where}: lh must be a style name or a list of them")
    out = []
    for item in lh:
        m = re.fullmatch(r"(\w+)(?:\*(\d+))?", item)
        if not m or m.group(1) not in STYLES:
            raise SongError(f"{where}: unknown left-hand style {item!r}; use {', '.join(STYLES)} (optionally style*count)")
        out += [m.group(1)] * int(m.group(2) or 1)
    if len(out) != n:
        raise SongError(f"{where}: lh covers {len(out)} bars but the section has {n}")
    return out


def _number(table: dict, key: str, default: float, where: str) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise SongError(f"{where}: {key!r} must be a number above 0")
    return value


def _require(table: dict, key: str, kind, where: str):
    if key not in table:
        raise SongError(f"{where}: missing {key!r}")
    if not isinstance(table[key], kind):
        raise SongError(f"{where}: {key!r} must be {kind.__name__}")
    return table[key]


def _text(table: dict, key: str, default: str, where: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise SongError(f"{where}: {key!r} must be text in quotes")
    return value


def _label(sec: dict, name: str, where: str) -> str:
    label = _text(sec, "label", name, where)
    if '"' in label or "%" in label:
        raise SongError(f"{where}: label {label!r} cannot hold \" or %")
    return label


def _check_bar(bar: str, where: str, key: str, meter: str, expected: Fraction | None) -> Fraction:
    try:
        got = bar_length(bar, key)
    except ValueError as e:
        raise SongError(f"{where}: {e}") from None
    if expected is not None and got != expected:
        raise SongError(f"{where}: {bar!r} lasts {got} eighths but a {meter} bar has {expected}")
    return got


def _parts(data: dict, key: str, meter: str) -> tuple[dict, dict]:
    """The validated [parts.*] tables (chords = "auto" filled in), and the chords the harmonizer chose per part."""
    eighths, beat = METERS[meter]
    parts = _require(data, "parts", dict, "song")
    auto = {}
    for name, part in parts.items():
        if not isinstance(part, dict):
            raise SongError(f"part {name}: must be a table ([parts.{name}])")
        if "chords_from" in part and _require(part, "chords_from", str, f"part {name}") not in parts:
            raise SongError(f"part {name}: chords_from {part['chords_from']!r} is not a part")
        melody = _require(part, "melody", list, f"part {name}")
        for i, bar in enumerate(melody, 1):
            if not isinstance(bar, str):
                raise SongError(f"part {name} bar {i}: must be ABC text in quotes, not {bar!r}")
            _check_bar(bar, f"part {name} bar {i}", key, meter, Fraction(eighths))
        if "pickup" in part:
            up = _require(part, "pickup", str, f"part {name}")
            got = _check_bar(up, f"part {name} pickup", key, meter, None)
            if not 0 < got < eighths:
                raise SongError(f"part {name}: pickup lasts {got} eighths; it must be shorter than a {meter} bar ({eighths})")
        chords = part.get("chords")
        if chords == "auto":
            part["chords"] = auto[name] = harmonize(melody, key, eighths, beat)
        elif chords is not None and not (isinstance(chords, list) and all(isinstance(c, str) for c in chords)):
            raise SongError(f'part {name}: chords must be a list (one entry per bar) or "auto"')
    for name, part in parts.items():
        chords = parts[part.get("chords_from", name)].get("chords")
        melody = part["melody"]
        if chords is None:
            raise SongError(f"part {name}: needs chords (a list, or \"auto\") or chords_from")
        if len(chords) != len(melody):
            raise SongError(f"part {name}: {len(melody)} melody bars but {len(chords)} chord entries")
        for i, c in enumerate(chords, 1):
            if not c.split():
                raise SongError(f"part {name} bar {i}: empty chord entry; repeat the chord that carries over")
            try:
                split(eighths, len(c.split()))
                for x in c.split():
                    voicing(x)
            except ValueError as e:
                raise SongError(f"part {name} bar {i}: {e}") from None
    return parts, auto


def _sections(data: dict, parts: dict, key: str) -> tuple[list[Section], list[tuple[int, str, Fraction]]]:
    """The arrangement, and the upbeats that lead into its sections: (section index, pickup as played there, length)."""
    sections, upbeats = [], []
    for k, sec in enumerate(_require(data, "sections", list, "song"), 1):
        if not isinstance(sec, dict):
            raise SongError(f"section {k}: must be a table ([[sections]])")
        name = _require(sec, "name", str, f"section {k}")
        where = f"section {name}"
        part_name = _require(sec, "part", str, where)
        if part_name not in parts:
            raise SongError(f"{where}: part {part_name!r} not defined")
        part = parts[part_name]
        melody, chords = part["melody"], parts[part.get("chords_from", part_name)]["chords"]
        bars = sec.get("bars", [1, len(melody)])
        if not (isinstance(bars, list) and len(bars) == 2 and all(isinstance(b, int) for b in bars)):
            raise SongError(f"{where}: bars must be [first, last] bar numbers, not {bars!r}")
        first, last = bars
        if not 1 <= first <= last <= len(melody):
            raise SongError(f"{where}: bars [{first}, {last}] outside part {part_name} (1..{len(melody)})")
        transform = _text(sec, "transform", "none", where)
        if transform not in TRANSFORMS:
            raise SongError(f"{where}: transform {transform!r} unknown; use {', '.join(TRANSFORMS)}")
        shape = sec.get("shape", "flat")
        n = last - first + 1
        if shape not in SHAPES or (shape == "arch" and n < 6) or (shape == "fade" and n < 2):
            raise SongError(f"{where}: shape {shape!r} needs one of {', '.join(SHAPES)}; arch >= 6 bars, fade >= 2")
        sections.append(
            Section(
                name=name,
                label=_label(sec, name, where),
                melody=[TRANSFORMS[transform](b, key) for b in melody[first - 1 : last]],
                chords=chords[first - 1 : last],
                lh=_expand(sec.get("lh", "flow"), n, where),
                dynamic=float(_number(sec, "dynamic", 1.0, where)),
                shape=shape,
            )
        )
        if first == 1 and "pickup" in part:  # the part's upbeat leads into this section
            upbeats.append((len(sections) - 1, TRANSFORMS[transform](part["pickup"], key), bar_length(part["pickup"], key)))
    if len({s.name for s in sections}) != len(sections):
        raise SongError("song: section names must be unique")
    if not sections:
        raise SongError("song: no sections")
    return sections, upbeats


def _place_upbeats(sections: list[Section], upbeats: list, key: str) -> tuple[str, Fraction]:
    """Puts each upbeat at the end of the section before it, shortening its last note; returns the opening anacrusis."""
    pickup, pickup_eighths = "", Fraction(0)
    for s, up, room in upbeats:
        if s == 0:  # the song opens with this part: an anacrusis before bar 1
            pickup, pickup_eighths = up, room
            continue
        prev = sections[s - 1]
        bar = make_room(prev.melody[-1], room)
        if bar is None:
            raise SongError(
                f"section {sections[s].name}: no room for its pickup at the end of section {prev.name}; "
                f"end that bar on a note or rest longer than {room} eighths, outside any tuplet"
            )
        prev.melody[-1] = accidentals(f"{bar} {accidentals(up, key, True)}", key, False)  # the upbeat's accidentals now share the bar
    return pickup, pickup_eighths


def parse(data: dict, slug: str) -> Song:
    key = _require(data, "key", str, "song")
    try:
        signature(key)
    except ValueError as e:
        raise SongError(f"song: {e}") from None
    meter = _require(data, "meter", str, "song")
    if meter not in METERS:
        raise SongError(f"song: meter {meter!r} not supported; use {', '.join(METERS)}")
    soundfont = data.get("soundfont", "salamander")
    if soundfont not in SOUNDFONTS:
        raise SongError(f"song: soundfont {soundfont!r} unknown; use {', '.join(SOUNDFONTS)}")
    if "pickup" in data:
        raise SongError("song: pickup belongs to the part it leads into: move it under [parts.<name>]")

    parts, auto = _parts(data, key, meter)
    sections, upbeats = _sections(data, parts, key)
    pickup, pickup_eighths = _place_upbeats(sections, upbeats, key)

    tempo = _require(data, "tempo", int, "song")  # beats per minute: quarter notes, or dotted quarters in compound meters
    if tempo <= 0:
        raise SongError("song: 'tempo' must be above 0")
    eighths, beat = METERS[meter]
    beats = len(sections[-1].melody) * eighths // beat
    ritardando = data.get("ritardando") or [round(tempo * (1 - 0.5 * (k + 1) / beats)) for k in range(beats)]
    if not (isinstance(ritardando, list) and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in ritardando)):
        raise SongError("song: ritardando must be a list of numbers above 0 (BPM per beat)")
    return Song(
        slug=slug,
        title=_require(data, "title", str, "song"),
        composer=_text(data, "composer", "", "song"),
        key=key,
        meter=meter,
        tempo=tempo,
        seed=_require(data, "seed", int, "song") if "seed" in data else 1,
        soundfont=soundfont,
        ritardando=ritardando,
        sections=sections,
        pickup=pickup,
        pickup_eighths=pickup_eighths,
        auto_chords=auto,
    )


def load(song_dir: Path) -> Song:
    """songs/<slug>/input/song.toml -> Song; the slug is the folder's name. Errors name the file."""
    path = Path(song_dir) / "input" / "song.toml"
    try:
        return parse(tomllib.loads(path.read_text(encoding="utf-8")), Path(song_dir).resolve().name)
    except (tomllib.TOMLDecodeError, SongError) as e:
        raise SongError(f"{path}: {e}") from None
