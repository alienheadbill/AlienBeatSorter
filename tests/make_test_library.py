"""Generate a synthetic test library with known BPM/key.

Usage: python tests/make_test_library.py OUTPUT_FOLDER

Synthetic audio is cleaner than real beats, so results here are a best
case. The real test is your own tagged files (see the accuracy report).
"""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
rng = np.random.default_rng(7)

NOTE_PC = {"C": 0, "C#": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6,
           "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env(n, a=0.005, d=0.3):
    t = np.arange(n) / SR
    e = np.minimum(t / a, 1.0) * np.exp(-t / d)
    return e


def kick(n):
    t = np.arange(n) / SR
    f = 50 + 120 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.001, 0.25)


def snare(n):
    return rng.standard_normal(n) * env(n, 0.001, 0.12) * 0.6


def hat(n):
    x = rng.standard_normal(n)
    x = np.diff(x, prepend=0)
    return x * env(n, 0.0005, 0.03) * 0.25


def tone(freq, n, kind="saw", d=0.8):
    t = np.arange(n) / SR
    if kind == "sine":
        w = np.sin(2 * np.pi * freq * t)
    else:  # soft saw: a few harmonics
        w = sum(np.sin(2 * np.pi * freq * h * t) / h for h in range(1, 6))
    return w * env(n, 0.01, d)


def add(buf, x, start):
    end = min(len(buf), start + len(x))
    if start < len(buf):
        buf[start:end] += x[: end - start]


MINOR_PROGS = [
    [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")],  # i VI III VII (ambiguous)
    [(0, "min"), (8, "maj"), (5, "min"), (7, "maj")],   # i VI iv V
    [(0, "min"), (0, "min"), (8, "maj"), (10, "maj")],  # i i VI VII
    [(0, "min"), (5, "min"), (0, "min"), (7, "min")],   # i iv i v
]
MAJOR_PROGS = [
    [(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")],   # I V vi IV
    [(0, "maj"), (5, "maj"), (0, "maj"), (7, "maj")],   # I IV I V
    [(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")],   # I vi IV V
]
_prog_counter = [0]


def chords_for(key_pc, mode):
    # scale degrees as (semitone offset of root, chord quality)
    progs = MINOR_PROGS if mode == "minor" else MAJOR_PROGS
    prog = progs[_prog_counter[0] % len(progs)]
    _prog_counter[0] += 1
    out = []
    for off, q in prog:
        root = 48 + (key_pc + off) % 12
        third = 4 if q == "maj" else 3
        out.append([root, root + third, root + 7, root + 12])
    return out


def make(bpm, key, mode, bars, drums=True, music=True, halftime=False):
    beat = 60.0 / bpm
    n = int(bars * 4 * beat * SR) + SR
    buf = np.zeros(n)
    pc = NOTE_PC[key]
    chords = chords_for(pc, mode)
    for bar in range(bars):
        for b in range(4):
            s = int((bar * 4 + b) * beat * SR)
            if drums:
                if b in ((0,) if halftime else (0, 2)):
                    add(buf, kick(int(0.4 * SR)), s)
                if halftime and b == 2 and bar % 2 == 1:
                    add(buf, kick(int(0.4 * SR)) * 0.8, s + int(beat * SR / 2))
                if b == (2 if halftime else 1) or (not halftime and b == 3):
                    add(buf, snare(int(0.25 * SR)), s)
                for h in range(4 if halftime else 2):
                    add(buf, hat(int(0.08 * SR)), s + int(h * beat * SR / (4 if halftime else 2)))
        if music:
            ch = chords[bar % 4]
            s = int(bar * 4 * beat * SR)
            for m in ch:
                add(buf, tone(midi_hz(m), int(4 * beat * SR), "saw", 2.0) * 0.12, s)
            # 808-ish bass on chord root
            add(buf, tone(midi_hz(ch[0] - 12), int(2 * beat * SR), "sine", 1.0) * 0.5, s)
            # pluck melody on scale tones
            for e in range(8):
                note = ch[(e * 3) % 4] + 12
                add(buf, tone(midi_hz(note), int(0.4 * beat * SR), "saw", 0.15) * 0.08,
                    s + int(e * beat * SR / 2))
    buf /= np.max(np.abs(buf)) + 1e-9
    return (buf * 0.8).astype(np.float32)


def main(out):
    out = Path(out)
    (out / "Beats").mkdir(parents=True, exist_ok=True)
    (out / "Loops" / "Drums").mkdir(parents=True, exist_ok=True)
    (out / "Loops" / "Melodic").mkdir(parents=True, exist_ok=True)
    (out / "One Shots" / "Kicks").mkdir(parents=True, exist_ok=True)
    (out / "One Shots" / "808s").mkdir(parents=True, exist_ok=True)

    beats = [
        (140, "A", "minor", True, "Midnight {b}bpm Am"),
        (140, "C#", "minor", False, "Ghost_C#min_{b}"),
        (150, "F#", "minor", True, "Rage Type Beat ({b} BPM, F#m)"),
        (92, "C", "minor", False, "boom bap {b} Cm"),
        (85, "Eb", "major", False, "lofi_{b}bpm_Ebmaj"),
        (128, "G", "major", False, "house idea {b} bpm G major"),
        (100, "D", "minor", False, "afro {b}bpm Dm"),
        (160, "B", "minor", True, "drill {b} Bm"),
        (75, "F", "major", False, "rnb slow {b}bpm F"),
        (174, "E", "minor", False, "dnb {b}bpm Em"),
        (120, "Bb", "major", False, "pop thing {b} Bb"),
        (110, "Ab", "major", False, "untitled beat 7"),     # untagged
        (135, "G", "minor", False, "Late Night"),           # untagged
    ]
    for bpm, key, mode, ht, name in beats:
        y = make(bpm, key, mode, bars=24, halftime=ht)
        sf.write(out / "Beats" / (name.format(b=bpm) + ".wav"), y, SR)

    for bpm in (90, 140, 170):
        y = make(bpm, "C", "minor", bars=4, music=False)
        sf.write(out / "Loops" / "Drums" / f"drum loop {bpm}bpm.wav", y, SR)
    for bpm, key, mode in ((140, "A", "minor"), (95, "F", "major")):
        y = make(bpm, key, mode, bars=8, drums=False)
        short = key + ("m" if mode == "minor" else "")
        sf.write(out / "Loops" / "Melodic" / f"keys loop {bpm} {short}.wav", y, SR)

    sf.write(out / "One Shots" / "Kicks" / "Kick 01.wav", kick(int(0.5 * SR)).astype(np.float32), SR)
    sf.write(out / "One Shots" / "Kicks" / "Kick 808 hard.wav", kick(int(0.4 * SR)).astype(np.float32), SR)
    sf.write(out / "One Shots" / "808s" / "808 Boom C.wav",
             (tone(midi_hz(36), int(1.5 * SR), "sine", 0.8) * 0.8).astype(np.float32), SR)
    # a file in a format we read, plus a non-audio file that must be ignored
    sf.write(out / "Beats" / "flac test 90bpm Gm.flac", make(90, "G", "minor", 12), SR)
    (out / "Beats" / "notes.txt").write_text("not audio")
    print("wrote test library to", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_library")
