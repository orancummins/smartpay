"""Mix narration (placed at each scene's vo_start) over a soft generative pad.

The pad is synthesised here so the film has no external music dependency: slow
chords in D major built from a few sine harmonics with gentle detune, low-passed,
and ducked under the voice.
"""
import json, numpy as np, soundfile as sf
from scipy.signal import resample_poly, butter, sosfilt

SR = 48000
tl = json.load(open("timeline.json"))
total = tl["total"] + 0.5
N = int(total * SR)

# ---------- narration ----------
voice = np.zeros(N, dtype=np.float32)
for s in tl["scenes"]:
    a, sr = sf.read(f"audio/{s['id']}.wav", dtype="float32")
    if a.ndim > 1: a = a.mean(axis=1)
    a = resample_poly(a, SR, sr).astype(np.float32)
    i = int(s["vo_start"] * SR)
    voice[i:i+len(a)] += a[:max(0, N-i)]
# gentle high-shelf presence + de-rumble
sos = butter(2, 80, "hp", fs=SR, output="sos"); voice = sosfilt(sos, voice).astype(np.float32)
voice *= 1.0

# ---------- pad ----------
def note(f): return 440.0 * 2 ** ((f - 69) / 12)
# chords as MIDI numbers (D major family), 10 s each, looping
CHORDS = [
    [50, 57, 61, 66],  # D
    [47, 54, 59, 62],  # Bm
    [43, 50, 59, 62],  # G
    [45, 52, 57, 61],  # A
    [50, 57, 62, 66],  # Dsus-ish
    [47, 54, 57, 62],  # Bm7
    [43, 50, 55, 59],  # G
    [45, 49, 52, 57],  # A
]
CH_LEN = 9.0
t = np.arange(N, dtype=np.float64) / SR
pad = np.zeros(N, dtype=np.float64)
rng = np.random.default_rng(7)
n_ch = int(np.ceil(total / CH_LEN)) + 1
for k in range(n_ch):
    chord = CHORDS[k % len(CHORDS)]
    t0, t1 = k * CH_LEN, (k + 1) * CH_LEN
    i0, i1 = int(max(0, t0 - 2.5) * SR), int(min(total, t1 + 2.5) * SR)
    if i0 >= N: break
    seg = t[i0:i1]
    # crossfade envelope: 2.5 s raised-cosine in/out
    env = np.ones_like(seg)
    a_in = np.clip((seg - (t0 - 2.5)) / 2.5, 0, 1); a_out = np.clip(((t1 + 2.5) - seg) / 2.5, 0, 1)
    env = (0.5 - 0.5 * np.cos(np.pi * a_in)) * (0.5 - 0.5 * np.cos(np.pi * a_out))
    for j, m in enumerate(chord):
        f = note(m)
        amp = 0.55 if j == 0 else 0.42
        for h, ha in ((1, 1.0), (2, 0.28), (3, 0.09)):
            det = rng.uniform(-0.25, 0.25)
            ph = rng.uniform(0, 2*np.pi)
            lfo = 1 + 0.06 * np.sin(2*np.pi*(0.07 + 0.02*j)*seg + ph)
            pad[i0:i1] += amp * ha * env * lfo * np.sin(2*np.pi*(f*h + det)*seg + ph)
    # sub root an octave down, pure sine, quiet
    pad[i0:i1] += 0.35 * env * np.sin(2*np.pi*note(chord[0]-12)*seg)
# soften: low-pass 2.2 kHz, then gentle slow shimmer
sos = butter(2, 2200, "lp", fs=SR, output="sos"); pad = sosfilt(sos, pad)
pad /= np.max(np.abs(pad)) + 1e-9
# fade in / out
fade_in = np.clip(t / 2.5, 0, 1); fade_out = np.clip((total - 0.2 - t) / 4.5, 0, 1)
pad *= fade_in * fade_out

# ---------- ducking under voice ----------
env = np.abs(voice)
win = int(0.25 * SR)
kernel = np.ones(win) / win
env = np.convolve(env, kernel, mode="same")
env = np.convolve(env, kernel, mode="same")  # smoother
duck = 1 - 0.55 * np.clip(env / 0.03, 0, 1)   # up to -7 dB under speech
pad *= duck

MUSIC_GAIN = 0.075   # ≈ -22.5 dBFS peak before ducking: a bed, not a track
mix = voice * 1.0 + (pad * MUSIC_GAIN).astype(np.float32)
# soft limiter
mix = np.tanh(mix * 1.15) / np.tanh(1.15)
stereo = np.stack([mix, mix], axis=1).astype(np.float32)
sf.write("audio/mix_raw.wav", stereo, SR)
sf.write("audio/pad_only.wav", (pad * MUSIC_GAIN).astype(np.float32), SR)
print("voice rms %.3f peak %.3f | pad peak %.3f | mix peak %.3f | len %.1fs" % (
    np.sqrt(np.mean(voice**2)), np.max(np.abs(voice)), np.max(np.abs(pad*MUSIC_GAIN)), np.max(np.abs(mix)), total))
