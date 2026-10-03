#!/usr/bin/env bash
# render.sh <soundfont.sf2> <in.mid> <out.mp3> [full|loud]: dry render -> room reverb -> mastering -> mp3.
#   full (default): one linear gain, the arrangement's whole dynamic range kept.
#   loud: -16 LUFS for playlists and video beds; a peak limiter tames the loudest chords.
# Needs fluidsynth, sox, ffmpeg (all in `nix develop`). Output is byte-identical run to run on one platform.
set -euo pipefail
sf=$1 mid=$2 out=$3 mode=${4:-full}
case $mode in full | loud) ;; *) echo "render.sh: mode must be full or loud, not '$mode'" >&2; exit 2 ;; esac
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# float output: no dither, so the render is reproducible
fluidsynth -ni -F "$tmp/dry.wav" -O float -r 48000 -g 0.45 -o synth.polyphony=512 -o synth.reverb.active=0 -o synth.chorus.active=0 "$sf" "$mid" >/dev/null 2>&1
sox -V1 "$tmp/dry.wav" "$tmp/wet.wav" reverb 42 55 90 100 18 -2 pad 0 3
# trim trailing silence, with a short fade so the cut is inaudible
pre="areverse,silenceremove=start_periods=1:start_threshold=-65dB,afade=t=in:d=0.05,areverse"
measure() {  # integrated loudness and true peak of wet.wav after the given filters
  json=$(ffmpeg -hide_banner -i "$tmp/wet.wav" -af "$pre,$1loudnorm=I=-16:TP=-1.5:print_format=json" -f null - 2>&1 | sed -n '/{/,/}/p')
  i=$(echo "$json" | grep '"input_i"' | sed -E 's/.*: "([^"]+)".*/\1/')
  tp=$(echo "$json" | grep '"input_tp"' | sed -E 's/.*: "([^"]+)".*/\1/')
}
measure ""
if [ "$mode" = full ]; then  # one plain gain: as close to -16 LUFS as the -1.5 dBTP peak allows
  # (loudnorm's own linear mode silently switches to dynamic compression when the peak would overshoot)
  gain=$(awk -v i="$i" -v tp="$tp" 'BEGIN { a = -16 - i; b = -1.5 - tp; printf "%.2f", (a < b ? a : b) }')
  master="volume=${gain}dB"
else  # gain to -16 LUFS; a limiter at 4x the sample rate (so it sees true peaks) holds them at -1.5 dBTP
  limit() { echo "volume=$1dB,aresample=192000,alimiter=limit=0.841:attack=5:release=50:level=disabled,aresample=48000"; }
  gain=$(awk -v i="$i" 'BEGIN { printf "%.2f", -16 - i }')
  measure "$(limit "$gain"),"  # the limiter takes some loudness away: measure once more and make it up
  gain=$(awk -v g="$gain" -v i="$i" 'BEGIN { printf "%.2f", g - 16 - i }')
  master=$(limit "$gain")
fi
ffmpeg -v error -y -i "$tmp/wet.wav" -af "$pre,$master" -c:a libmp3lame -b:a 256k "$out"
ffmpeg -hide_banner -i "$out" -af ebur128=peak=true -f null - 2>&1 | grep -E '^ +(I|LRA|Peak):' | tr -s ' ' | tr '\n' ' '
echo "gain: ${gain} dB"
