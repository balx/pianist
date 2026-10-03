---
name: new-song
description: Turn a sheet (PDF, image or link) into songs/<slug>/ (input/song.toml, output/ score and mp3) as an expressive solo piano recording, with you (the agent) reading the sheet - no Anthropic API key needed. Use when the user gives a song sheet (lead sheet, hymn, melody-only or 4-part) and wants it played on piano.
---

# New song from a sheet

The only input is the sheet: a PDF, a png/jpg, or a link to one. Ask nothing up front; use these defaults and mention them at the end:

- **Piano**: `salamander` (concert grand). `upright` is warmer and more intimate.
- **Form**: intro (the last line, melody alone an octave up, `lh = "hold"`), each part as written, then again in octaves building to `shape = "arch"`, coda on the last line (`shape = "fade"`), as in the sample. With a verse and a refrain: intro from the refrain, verse, verse in octaves, refrain in octaves, coda.
- **Mastering**: full dynamics. `--loud` gives -16 LUFS for playlists and video beds.

## 1. Draft with optical music recognition

```sh
nix develop -c python3 -m pianist "<sheet or link>" --reader omr --no-audio
```

This copies the sheet into `songs/<slug>/input/`, writes a draft `input/song.toml` and prints the score to `songs/<slug>/output/score00N.png`. The draft's melody is usually right note for note. It has no chord symbols (`"auto"`), no ties, a title from the file name, parts named `part1`, `part2` (a new part starts at each mid-score upbeat) and notes about bars it repaired. If it fails, write `song.toml` from scratch in step 2 (create `songs/<slug>/input/` and copy the sheet there as `sheet.<ext>`).

## 2. Correct it against the sheet

Read the sheet itself (open the PDF or image). Study the sample first: `songs/amazing-grace/input/song.toml` documents every field, and `songs/amazing-grace/output/` is what it produces.

- **Title and composer** exactly as printed, with diacritics. Rename the folder to match: `songs/<slug>` with `<slug>` the title in kebab case without diacritics (`dem-thanh-vo-cung` for Đêm Thánh Vô Cùng).
- **Parts**: name them for what they are (`refrain`, `verse`); label sections `Đk:`, `1.`, `2.` as the sheet does. Verses that share one melody are one part.
- **Melody**: compare every bar. Bars are ABC with `L:1/8`, written against the key signature (`^G` only where the sheet has an accidental). Join the eighths of one beat with no space (`GG DB,`); separate beats with a space. Add ties (`d4-`) across bar lines where the sheet has them. Where the sheet has two written voices, write each as a chord with the melody note first: `[ec]`.
- **Upbeats**: an upbeat leading into a part goes in `pickup = "..."` under that part. The build places it before bar 1 when the song opens with that part, otherwise at the end of the previous section, shortening its last note.
- **Chords**: one entry per bar, as printed; repeat a symbol carried over from the previous bar; several in a bar are space-separated (`"G F E7"`). Supported: m, 7, m7, maj7, dim, dim7, sus4 and /bass.
- **No chord symbols on the sheet**: with 4-part harmony, name each chord from all the voices on the beat. With a melody only, keep `chords = "auto"`, build once, paste the printed `[parts.<name>] chords = [...]` list into `song.toml` and adjust it: the harmonizer uses only the key's own chords, so add colour where the melody invites it (a secondary dominant such as A7 before Dm).
- Meters 2/4, 3/4, 4/4, 6/8, 9/8, 12/8 (`tempo` counts dotted quarters in compound meters).

## 3. Check, then render

1. `nix develop -c python3 -m pianist songs/<slug> --no-audio`. Fix every error; they name the part and bar.
2. Open the `songs/<slug>/output/score00N.png` pages next to the sheet and compare bar by bar: pitches, rhythms, accidentals, ties, chord symbols. Fix and rebuild until they match.
3. `nix develop -c python3 -m pianist songs/<slug>` renders `songs/<slug>/output/<slug>-salamander.mp3`. Tell the user the path, the loudness line it prints, and the defaults you used.
4. Ask the user to listen. Typical tweaks: `tempo`, section `dynamic`, `lh` styles (`flow`, `rise`, `octave`, `hold`), `ritardando`, `soundfont`.
5. `songs/` is git-ignored apart from the sample: the user's songs stay local unless they choose to share them (most songs are under copyright).
