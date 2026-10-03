# pianist

Turns a song sheet (PDF, image or link) into an expressive solo piano recording: a printed two-staff score, a humanized MIDI performance (phrase breathing, dynamics, melody voicing, rolled chords, pedal) and a mastered mp3.

```
songs/<slug>/input/  sheet ─► reader ─► song.toml
songs/<slug>/output/ score.abc ─► abc2midi ─► raw.mid ─► humanize ─► piano.mid ─► fluidsynth + reverb + gain ─► mp3
                         └─► abcm2ps ─► score00N.svg/.png, one per page (check them against the sheet)
```

## Use

Everything runs inside the Nix dev shell: the tools, the OMR models and two pinned piano soundfonts. The first run downloads about 1.2 GB, almost all of it the Salamander grand; `nix develop .#ci` is a lighter start with every tool and only the 55 MB upright (then use `--soundfont upright`).

```sh
nix develop
python3 -m pianist https://example.org/sheet.pdf   # read the sheet with Claude -> songs/<slug>/ -> mp3
python3 -m pianist scan.jpg --reader omr           # read it offline with optical music recognition
python3 -m pianist scan.jpg --songs ~/my-songs     # create the song folder somewhere other than songs/
python3 -m pianist songs/amazing-grace            # (re)build a song -> songs/amazing-grace/output/amazing-grace-salamander.mp3
python3 -m pianist songs/amazing-grace --soundfont upright
python3 -m pianist songs/amazing-grace --loud     # -16 LUFS for playlists and video beds -> ...-salamander-loud.mp3
python3 -m pianist songs/amazing-grace --no-audio # score and MIDI only
python3 -m pianist songs/amazing-grace --out /tmp # write into /tmp/amazing-grace/ instead of the song's output/
```

Developing: `python3 -m pytest -q` (in parallel) and `ruff check`, both run by CI. `CLAUDE.md` has the rules a change must keep.

## Three ways to read a sheet

A song is one folder: `songs/<slug>/input/` holds what you give (the sheet) and the `song.toml` transcription a reader writes from it; `songs/<slug>/output/` holds what pianist makes from that. The `song.toml` stays editable: fix a note, rerun `python3 -m pianist songs/<slug>`.

| | Command | Reads | Needs |
|---|---|---|---|
| **Claude (API)** | `python3 -m pianist <sheet>` | Melody, both voices, ties, chord symbols, title and composer, verse and refrain; then prints the score, compares it with the sheet and corrects itself (2 rounds) | `ANTHROPIC_API_KEY`; a few cents to a few tens of cents per song (printed) |
| **Claude Code skill** | `/new-song <sheet>` in Claude Code | The same, with Claude Code as the reader: it starts from the OMR draft and corrects it against the sheet | A Claude Code session; no API key |
| **OMR (offline)** | `python3 -m pianist <sheet> --reader omr` | The melody line note for note on clean engraved sheets ([homr](https://github.com/liebharc/homr) 0.7); no ties, no chord symbols (`chords = "auto"`), title from the file name, parts split at mid-score upbeats | Nothing beyond `nix develop` |

On the sample sheet, OMR reads every bar right except the two ties; `tests/test_omr.py` holds it to that.

## What it can play

Any song written as a melody: a lead sheet, a hymnal page, a melody-only sheet.

- **Meters:** 2/4, 3/4, 4/4, 6/8, 9/8 and 12/8, with upbeats.
- **Keys:** any major or minor key, one per song.
- **Chords:** m, 7, m7, maj7, dim, dim7, sus4 and /bass. When the sheet has none, `chords = "auto"` harmonizes the melody with the key's own chords; on the sample it agrees with the printed chords on about half the bars, so review what it picks.
- **Left hand:** generated from the chords. A written piano accompaniment is not read.
- **Not supported yet:** key or meter changes inside a song, and swing.

## Sample: Amazing Grace

| | |
|---|---|
| `input/` | `sheet.pdf` (a lead sheet engraved for this repo), `sheet.abc` (its source), `song.toml` (the transcription and arrangement; its comments document every field) |
| `output/` | `score00N.png`/`.svg` (printed score, one per page), `score.abc`, `raw.mid` (as written), `piano.mid` (performance), `amazing-grace-salamander.mp3`, `amazing-grace-upright.mp3` |

Both live in `songs/amazing-grace/`. `tests/test_samples.py` fails when the committed output no longer matches what the code produces; rebuilds are byte-identical, so after an intended change, regenerate and review the diff:

```sh
python3 -m pianist songs/amazing-grace
python3 -m pianist songs/amazing-grace --soundfont upright
```

## Your songs

`songs/` is ignored by git except for the sample, so the sheets and transcriptions you add stay on your machine. Most songs are under copyright: share their sheets, transcriptions and recordings only with permission.

## Loudness

By default the mp3 keeps the arrangement's whole dynamic range: one plain gain, as loud as the -1.5 dBTP peak allows (about -20 LUFS for the sample). `--loud` masters to -16 LUFS instead, with a gentle peak limiter on the loudest chords, so the track sits level with other music.

## Licenses and credits

- **pianist** is MIT licensed (`LICENSE`).
- **The sample** (Amazing Grace): the melody "New Britain" (1829) and John Newton's words (1779) are in the public domain. The engraved sheet, the chord symbols, the arrangement, the scores and MIDI in its `output/`, and `amazing-grace-upright.mp3` are dedicated to the public domain (CC0). `amazing-grace-salamander.mp3` uses the Salamander Grand Piano: when you share it, credit "Salamander Grand Piano V3 by Alexander Holm, CC BY 3.0".
- **homr** (the OMR reader) is AGPL-3.0. pianist runs it as a separate program and does not include it; `nix/homr.nix` builds it from its PyPI release with its published models. If you redistribute homr itself, its license applies.
- **Pianos**, fetched from freepats.zenvoid.org and pinned by hash in `flake.nix`:

  | name | samples | license |
  |------|---------|---------|
  | `salamander` | Salamander Grand Piano V3 (Yamaha C5) by Alexander Holm | CC BY 3.0: credit it when you publish a recording |
  | `upright` | Upright Piano KW | CC0 |
