#!/usr/bin/env bash
# Ingest a recorded demo video: transcript with timestamps + frame contact sheets.
# Usage: bash demo/ingest.sh path/to/recording.mov [outdir]
# Output: <outdir>/audio.wav, transcript.txt (timed sentences), words.txt (timed words),
#         frames/fNNN.jpg (one every 5 s: file N is at (N-1)*5 s), sheet-N.jpg (contact sheets,
#         one frame every 10 s, 4 across x 5 down, so sheet N tile (r,c) is at ((N-1)*20 + r*4 + c)*10 s).
set -euo pipefail
src="${1:?video path}"
out="${2:-demo/work/$(basename "${src%.*}")}"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$out/frames"
echo "== audio"
ffmpeg -y -loglevel error -i "$src" -vn -ac 1 -ar 16000 "$out/audio.wav"
echo "== transcript (faster-whisper, local)"
uvx --with faster-whisper --with numpy python -I "$here/transcribe.py" "$out/audio.wav" "$out"
echo "== frames every 5 s (f001 = 0 s, f002 = 5 s, ...)"
ffmpeg -y -loglevel error -i "$src" -vf "fps=1/5,scale=640:-2" "$out/frames/f%03d.jpg"
echo "== contact sheets (every 10 s, 4x5 per sheet)"
ffmpeg -y -loglevel error -i "$src" -vf "fps=1/10,scale=480:-2,tile=4x5" "$out/sheet-%d.jpg"
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$src")
echo "== done: ${dur}s  ->  $out"
ls "$out"
