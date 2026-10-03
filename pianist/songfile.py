"""Writing song.toml for a new song: the file writer, the default arrangement form, and the folder name."""

import json
import re
import unicodedata


def slugify(title: str) -> str:
    """'Đêm Thánh Vô Cùng' -> 'dem-thanh-vo-cung'; 'AmazingGrace' -> 'amazing-grace'."""
    title = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title).replace("Đ", "D").replace("đ", "d")
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")


def default_form(parts: dict[str, int], frame: bool = True) -> list[dict]:
    """parts: name -> bars, in score order. Intro (the last line, melody alone up high), every part as written,
    every part again fuller in octaves (building on the last), and a soft coda on the last line.
    frame=False leaves out the intro and the reprise (when nothing may come before the first part's upbeat)."""
    names, one = list(parts), len(parts) == 1
    last = names[-1]
    tail = [max(1, parts[last] - 3), parts[last]]
    sections = [{"name": "intro", "label": "Intro", "part": last, "bars": tail, "transform": "top_voice_up", "lh": "hold", "dynamic": 0.6}] if frame else []
    sections += [{"name": p, "label": "1." if one else p, "part": p, "lh": "flow", "dynamic": 0.8} for p in names]
    sections += [] if not frame else [
        {"name": "reprise" if one else f"reprise {p}", "label": "2." if one else f"{p} (octaves)", "part": p, "transform": "octaves",
         "lh": "octave", "dynamic": 1.0, "shape": "arch" if p == last and parts[p] >= 6 else "flat"}
        for p in names
    ]
    coda = [max(2, tail[0]), tail[1]] if tail[1] > 1 else tail  # never from bar 1: that would replay the part's upbeat
    k = coda[1] - coda[0] + 1
    sections.append({"name": "coda", "label": "Coda", "part": last, "bars": coda, "lh": [f"flow*{k - 1}", "hold"] if k > 1 else "hold", "dynamic": 0.66, "shape": "fade" if k > 1 else "flat"})
    return sections


def _value(v) -> str:
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # a JSON string is a valid TOML basic string
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list) and len(v) > 4 and all(isinstance(x, str) for x in v):  # melody and chords: 4 bars a line
        rows = [", ".join(_value(x) for x in v[i : i + 4]) for i in range(0, len(v), 4)]
        return "[\n" + "".join(f"  {r},\n" for r in rows) + "]"
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    raise TypeError(f"cannot write {v!r} to song.toml")


def dump(data: dict) -> str:
    """The song as song.toml text, laid out like songs/amazing-grace/input/song.toml."""
    lines = [f"{k} = {_value(v)}" for k, v in data.items() if k not in ("parts", "sections")]
    for name, part in data["parts"].items():
        lines += ["", f"[parts.{name}]"] + [f"{k} = {_value(v)}" for k, v in part.items()]
    for section in data["sections"]:
        lines += ["", "[[sections]]"] + [f"{k} = {_value(v)}" for k, v in section.items()]
    return "\n".join(lines) + "\n"
