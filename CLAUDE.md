# pianist

A sheet (PDF, image, link) -> `songs/<slug>/input/song.toml` -> score, humanized MIDI and mp3 in `songs/<slug>/output/`. README.md has the user's view; `songs/amazing-grace/input/song.toml` documents every song field.

## Run everything in the dev shell

- `nix develop -c python3 -m pytest -q` and `nix develop -c ruff check`; CI runs both in `.#ci` (tools + upright piano only).
- Tools (abc2midi, abcm2ps, fluidsynth, homr, ...) exist only there. Do not pip-install anything; add Python packages to `flake.nix`.

## Rules a change must keep

- Output is reproducible: a rebuild of the sample is byte-identical (seeded randomness, no timestamps in SVGs, float render). `tests/test_samples.py` fails when the committed `songs/amazing-grace/output/` is stale. After a change that alters output, or `nix flake update`, regenerate it and review the diff, listening to the mp3 when the performance changed:
  `python3 -m pianist songs/amazing-grace && python3 -m pianist songs/amazing-grace --soundfont upright`
- `songs/` is git-ignored except the sample: never commit other songs (most are under copyright).
- Errors a user can cause are messages, never tracebacks: `SongError` (song.toml), `BuildError` (tools), `SheetError` (reading a sheet), `ReaderError` (Claude API). Only `__main__.py` turns them into an exit.
- Text from a sheet or song.toml reaches the ABC score: title and composer go through `score.text()`, labels and bars are validated in `song.py` / `notation.notes()`. Keep it that way: a line break there would add score directives.
- Bar transforms must keep every pitch: wrap them in `notation.respell` (ABC accidentals carry through the bar).
- humanize.py works on abc2midi's MIDI: notes start 1 tick late (`on_grid`), and the score sets `%%MIDI chordattack 0` per voice so chord notes start together.
- The Claude reader (`claude_reader.py`) is tested with a scripted fake client; the live test runs only with `ANTHROPIC_API_KEY`. A paid draft must never be lost to an error.
- Tests run in parallel (`pytest.ini`): write only under `tmp_path`.
