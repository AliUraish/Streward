"""Transcribe a wav locally with faster-whisper. Writes transcript.txt (timed segments) and words.txt."""
import subprocess, sys
import numpy as np
from faster_whisper import WhisperModel

wav, out = sys.argv[1], sys.argv[2]
model = WhisperModel("small", device="cpu", compute_type="int8")
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], check=True, capture_output=True).stdout
audio = np.frombuffer(raw, dtype=np.float32)   # decode with ffmpeg; sidesteps the PyAV version mismatch
segments, info = model.transcribe(audio, word_timestamps=True, vad_filter=True)
seg_lines, word_lines = [], []
for s in segments:
    seg_lines.append(f"{s.start:7.2f} {s.end:7.2f}  {s.text.strip()}")
    for w in s.words or []:
        word_lines.append(f"{w.start:7.2f} {w.end:7.2f}  {w.word.strip()}")
open(f"{out}/transcript.txt", "w").write("\n".join(seg_lines) + "\n")
open(f"{out}/words.txt", "w").write("\n".join(word_lines) + "\n")
print(f"language {info.language}  segments {len(seg_lines)}  words {len(word_lines)}")
print("\n".join(seg_lines))
