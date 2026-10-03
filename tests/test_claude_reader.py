"""The Claude reader's loop: transcribe, fix what does not load, compare the printed score with the sheet, correct.

The API is replaced by a scripted client here (the only fake in the suite: an external, paid service);
test_reads_the_sample_sheet_live runs the real thing when ANTHROPIC_API_KEY is set.
"""

import json
import os
import shutil
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pianist.claude_reader import MODEL, ReaderError, read

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "songs" / "amazing-grace" / "input" / "sheet.pdf"
GOOD = (ROOT / "songs" / "amazing-grace" / "input" / "song.toml").read_text(encoding="utf-8")
WRONG = GOOD.replace('"G4 BG", "B4 A2", "G4 E2", "D4 D2"', '"G4 BG", "B4 A2", "G4 D2", "D4 D2"', 1)


def reply(song_toml, notes=(), stop="end_turn"):
    text = json.dumps({"song_toml": song_toml, "notes": list(notes)})
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)], usage=SimpleNamespace(input_tokens=1000, output_tokens=200), stop_details=None)


class Scripted:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **request):
        self.calls.append({**request, "messages": list(request["messages"])})
        return _Stream(self.replies.pop(0))


class _Stream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def test_loop_fixes_a_file_that_does_not_load_then_corrects_against_the_printed_score(tmp_path):
    client = Scripted([reply("title = "), reply(WRONG), reply(GOOD, ["bar 3: G E, not G D"]), reply(GOOD)])
    rendered = []

    def render(song_toml):
        rendered.append(song_toml)
        page = tmp_path / f"page{len(rendered)}.png"
        page.write_bytes(b"\x89PNG fake page")
        return [page]

    song_toml, notes = read(SHEET, client=client, render=render, log=lambda *_: None)
    assert song_toml == GOOD
    assert notes == ["bar 3: G E, not G D"]
    assert [c["model"] for c in client.calls] == [MODEL] * 4
    first = client.calls[0]
    assert first["messages"][0]["content"][0]["type"] == "document"  # the PDF goes in as a document
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert "did not load" in str(client.calls[1]["messages"][-1]["content"])
    assert client.calls[2]["messages"][-1]["content"][0]["type"] == "image"  # the printed score goes back as images
    assert rendered == [WRONG, GOOD]


def test_refusal_is_reported(tmp_path):
    client = Scripted([reply("", stop="refusal")])
    with pytest.raises(ReaderError, match="declined"):
        read(SHEET, client=client, render=lambda t: [], log=lambda *_: None)


def test_keeps_the_last_draft_after_repeated_unloadable_files(tmp_path):
    client = Scripted([reply("title = ")] * 3)
    song_toml, notes = read(SHEET, client=client, render=lambda t: [], log=lambda *_: None)
    assert song_toml == "title = "  # kept for the user to fix by hand
    assert any("still did not load" in n for n in notes)


def block(kind, text=""):
    return SimpleNamespace(type=kind, text=text, thinking="")


def test_reads_the_answer_after_a_fallback_and_echoes_only_what_the_api_accepts(tmp_path):
    full = json.dumps({"song_toml": GOOD, "notes": []})
    fallback = SimpleNamespace(stop_reason="end_turn", stop_details=None, usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                               content=[block("thinking"), block("text", full[:40]), block("fallback"), block("text", full)])
    client = Scripted([fallback, reply(GOOD)])
    song_toml, _ = read(SHEET, client=client, render=lambda t: [tmp_path / "p.png"] if (tmp_path / "p.png").write_bytes(b"x") else [], log=lambda *_: None)
    assert song_toml == GOOD
    echoed = client.calls[1]["messages"][1]["content"]
    assert [b.type for b in echoed] == ["text", "fallback", "text"]  # thinking before the final fallback is dropped


def test_a_reply_without_an_answer_is_asked_again(tmp_path):
    empty = SimpleNamespace(stop_reason="end_turn", stop_details=None, usage=SimpleNamespace(input_tokens=1, output_tokens=1), content=[block("thinking")])
    client = Scripted([empty, reply(GOOD)])
    song_toml, _ = read(SHEET, client=client, render=lambda t: [], log=lambda *_: None)
    assert song_toml == GOOD
    assert "no song_toml" in str(client.calls[1]["messages"][-1]["content"])


def test_images_are_sent_as_images(tmp_path):
    image = tmp_path / "sheet.png"
    shutil.copy(SHEET, image)  # content does not matter to the scripted client
    client = Scripted([reply(GOOD), reply(GOOD)])
    read(image, client=client, render=lambda t: [], log=lambda *_: None)
    assert client.calls[0]["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="live test: needs ANTHROPIC_API_KEY")
def test_reads_the_sample_sheet_live(tmp_path):
    from pianist.sheet import render_draft

    song_toml, _ = read(SHEET, render=lambda t: render_draft(t, tmp_path))
    data = tomllib.loads(song_toml)
    sample = tomllib.loads(GOOD)
    melody = [b for p in data["parts"].values() for b in p["melody"]]
    expected = sample["parts"]["verse"]["melody"]
    assert sum(bar in melody for bar in expected) >= 0.9 * len(expected)


def test_missing_credentials_give_a_clear_message(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no `ant auth login` profile either
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with pytest.raises(ReaderError, match="no Anthropic credentials"):
        read(SHEET, render=lambda t: [], log=lambda *_: None)  # the real SDK: it fails before any network call


class Flaky(Scripted):
    """Answers from the script, then the network fails."""

    def stream(self, **request):
        if not self.replies:
            import anthropic
            import httpx

            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
        return super().stream(**request)


def test_a_network_error_during_the_self_check_keeps_the_transcription(tmp_path):
    page = tmp_path / "p.png"
    page.write_bytes(b"x")
    logged = []
    song_toml, _ = read(SHEET, client=Flaky([reply(GOOD)]), render=lambda t: [page], log=logged.append)
    assert song_toml == GOOD
    assert any("could not reach the Anthropic API" in line for line in logged)
    assert any("requests" in line and "$" in line for line in logged)  # the cost line is still printed


def test_an_unexpected_failure_while_checking_a_reply_goes_back_to_claude(tmp_path):
    """Any error in pianist on a reply is a problem to fix, never the end of a paid reading."""
    def render(song_toml):
        if song_toml == WRONG:
            raise RuntimeError("abcm2ps crashed")
        page = tmp_path / "page.png"
        page.write_bytes(b"\x89PNG fake page")
        return [page]

    client = Scripted([reply(WRONG), reply(GOOD), reply(GOOD)])
    song_toml, _ = read(SHEET, client=client, render=render, log=lambda *_: None)
    assert song_toml == GOOD
    assert "abcm2ps crashed" in str(client.calls[1]["messages"][-1]["content"])
