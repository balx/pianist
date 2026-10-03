"""Sheet -> song.toml with Claude: transcribe, fix what does not load, then compare the printed score with the sheet and correct.

Needs Anthropic credentials (ANTHROPIC_API_KEY). One song costs a few cents to a few tens of cents, printed at the end.
"""

import base64
import json
import tomllib
from pathlib import Path

import anthropic

from .song import parse

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-5-5"
PRICE = (4.0, 20.0)  # USD per million input / output tokens for MODEL
MEDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "song_toml": {"type": "string", "description": "the complete song.toml"},
            "notes": {"type": "array", "items": {"type": "string"}, "description": "what changed, or doubts about the reading; empty when nothing changed"},
        },
        "required": ["song_toml", "notes"],
        "additionalProperties": False,
    },
}
SYSTEM = """You transcribe sheet music into song.toml for pianist, which arranges a melody and its chord symbols for solo piano.

Here is a finished song.toml. Its comments document every field; follow its layout:

{example}

Transcribing:
- Melody bars are ABC with L:1/8, written against the key signature (an accidental only where the sheet has one). Join the eighths of one beat with no space (GG DB,) so they beam; separate beats with a space.
- Where the sheet has two written voices, write each beat as a chord with the melody note first: [ec].
- One chord-symbol entry per bar, as printed; when a symbol is carried over from the previous bar, repeat it. Several chords in a bar are space-separated ("G F E7"). Supported: m, 7, m7, maj7, dim, dim7, sus4 and /bass.
- No chord symbols but four-part harmony: name each chord from all the voices on the beat. Melody only: chords = "auto".
- Verses usually share one melody: transcribe it once. Keep the refrain as its own part. An upbeat before bar 1 goes in pickup under the part it leads into.
- Meters 2/4 3/4 4/4 6/8 9/8 12/8. Title and composer exactly as printed, with diacritics. Tempo from the sheet, else a natural tempo for the song.
- Form, unless the sheet suggests otherwise: an intro on the last line (melody alone, an octave up, lh "hold"), each part as written, then again in octaves building to an "arch", and a soft coda ("fade") on the last line. With a verse and a refrain: intro from the refrain, verse, verse in octaves, refrain in octaves, coda.
- Repeats, first and second endings and D.S./D.C.: write the music out in the order it is played.

Return the complete file every time."""


class ReaderError(Exception):
    pass


def _source(path: Path) -> dict:
    media = MEDIA.get(path.suffix.lower())
    if media is None:
        raise ReaderError(f"{path.name}: not a PDF or an image (png, jpg)")
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    kind = "document" if media == "application/pdf" else "image"
    return {"type": kind, "source": {"type": "base64", "media_type": media, "data": data}}


def _ask(client, messages: list, usage: list) -> tuple[str | None, list[str]]:
    """One request. Returns (song_toml, notes), or (None, []) when the reply holds no usable answer."""
    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": FORMAT},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM.format(example=(ROOT / "songs" / "amazing-grace" / "input" / "song.toml").read_text(encoding="utf-8")),
            messages=messages,
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise ReaderError("the Anthropic API rejected the credentials: set ANTHROPIC_API_KEY, or use --reader omr, or the new-song skill in Claude Code") from None
    except anthropic.RateLimitError:
        raise ReaderError("the Anthropic API is rate limiting this key; try again in a minute") from None
    except anthropic.APIStatusError as e:
        raise ReaderError(f"the Anthropic API returned {e.status_code}: {e.message}") from None
    except anthropic.APIConnectionError:
        raise ReaderError("could not reach the Anthropic API; check the network") from None
    except TypeError as e:  # the SDK raises a plain TypeError when it finds no credentials at all
        if "authentication" not in str(e):
            raise
        raise ReaderError("no Anthropic credentials: set ANTHROPIC_API_KEY, or use --reader omr, or the new-song skill in Claude Code") from None
    usage.append((message.usage.input_tokens, message.usage.output_tokens))
    if message.stop_reason == "refusal":
        raise ReaderError("Claude declined to read this sheet")
    if message.stop_reason == "max_tokens":
        raise ReaderError("Claude's answer was cut off (max_tokens); the sheet may be too long for one request")
    content = list(message.content)
    # After a server-side fallback the answer is the text after the last fallback block, and thinking blocks before it
    # must not be sent back. Everything else is echoed unchanged (append-only keeps thinking blocks valid).
    cut = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    messages.append({"role": "assistant", "content": [b for i, b in enumerate(content) if not (i < cut and b.type in ("thinking", "redacted_thinking"))]})
    texts = [b.text for b in content[cut + 1 :] if b.type == "text"]
    try:
        answer = json.loads(texts[-1])
        return str(answer["song_toml"]), [str(n) for n in answer["notes"]]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        return None, []


def _problem(song_toml: str | None, render) -> tuple[str | None, list[Path]]:
    """Why the file does not load or build (None if it does), and the printed score pages."""
    if song_toml is None:
        return "your reply had no song_toml answer", []
    try:
        parse(tomllib.loads(song_toml), "draft")
        return None, render(song_toml)
    except Exception as e:  # noqa: BLE001 - whatever is wrong with a reply goes back to Claude to fix; a paid draft is never lost to it
        return str(e) or type(e).__name__, []


def read(sheet: Path, *, client=None, render, rounds: int = 2, log=print) -> tuple[str, list[str]]:
    """Transcribe the sheet; render(song_toml) -> score PNG pages (raising if it does not build)."""
    client = client or anthropic.Anthropic()  # credentials are checked on the first request, in _ask
    usage: list = []
    try:
        return _read(client, Path(sheet), render, rounds, log, usage)
    finally:
        if usage:
            tokens_in, tokens_out = map(sum, zip(*usage))
            log(f"{len(usage)} requests, {tokens_in} input + {tokens_out} output tokens, about ${(tokens_in * PRICE[0] + tokens_out * PRICE[1]) / 1e6:.2f}")


def _read(client, sheet: Path, render, rounds: int, log, usage: list) -> tuple[str, list[str]]:
    messages = [{"role": "user", "content": [_source(sheet), {"type": "text", "text": "Transcribe this sheet into song.toml."}]}]
    log(f"reading {Path(sheet).name} with {MODEL} ...")
    song_toml, notes = _ask(client, messages, usage)
    draft = song_toml
    for attempt in range(3):
        problem, pages = _problem(song_toml, render)
        draft = song_toml if song_toml is not None else draft
        if problem is None:
            break
        if attempt == 2:
            if draft is None:
                raise ReaderError(f"Claude gave no transcription after 3 tries ({problem})")
            log(f"keeping the last draft; it still does not load: {problem}")
            return draft, [f"the transcription still did not load after 3 tries: {problem} - fix song.toml by hand"]
        log(f"fixing: {problem}")
        messages.append({"role": "user", "content": f"That song.toml did not load: {problem}\nReturn the complete, corrected file."})
        try:
            song_toml, notes = _ask(client, messages, usage)
        except ReaderError as e:
            if draft is None:
                raise
            log(f"keeping the last draft: {e}")  # paid for; the user can fix it by hand
            return draft, [f"the transcription did not load ({problem}) and the fix failed ({e}) - fix song.toml by hand"]
    all_notes = list(notes)
    for _ in range(rounds):  # self-check: the printed score against the sheet
        if not pages:
            break
        images = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(p.read_bytes()).decode("ascii")}} for p in pages]
        messages.append({"role": "user", "content": images + [{"type": "text", "text": (
            "These pages are your song.toml as pianist prints it. Compare them with the original sheet bar by bar: "
            "pitches, rhythms, accidentals, ties, triplets and chord symbols. Return the file unchanged with empty notes if "
            "everything matches; otherwise return the corrected file and list each fix in notes."
        )}]})
        log("checking the printed score against the sheet ...")
        try:
            fixed, notes = _ask(client, messages, usage)
        except ReaderError as e:
            log(f"keeping the current version, unchecked: {e}")
            all_notes.append(f"the check against the sheet did not finish ({e}); compare the score with the sheet yourself")
            break
        if fixed is None or (fixed == song_toml and not notes):
            break
        problem, new_pages = _problem(fixed, render)
        if problem is not None:
            log(f"keeping the previous version: the correction did not load ({problem})")
            break
        song_toml, pages = fixed, new_pages
        all_notes += notes
    return song_toml, all_notes
