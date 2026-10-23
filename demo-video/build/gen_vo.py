import json, soundfile as sf, numpy as np, sys
from kokoro_onnx import Kokoro
TTS='.'  # folder holding kokoro-v1.0.onnx + voices-v1.0.bin
k = Kokoro(f'{TTS}/kokoro-v1.0.onnx', f'{TTS}/voices-v1.0.bin')
voice = sys.argv[1] if len(sys.argv)>1 else 'af_heart'
speed = float(sys.argv[2]) if len(sys.argv)>2 else 1.0
script = json.load(open('script.json'))
durs = {}
for s in script:
    samples, sr = k.create(s['text'], voice=voice, speed=speed, lang='en-us')
    # trim leading/trailing silence lightly
    a = np.asarray(samples, dtype=np.float32)
    thr = 0.004
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx):
        a = a[max(0, idx[0]-int(0.05*sr)): min(len(a), idx[-1]+int(0.25*sr))]
    sf.write(f"audio/{s['id']}.wav", a, sr)
    durs[s['id']] = round(len(a)/sr, 3)
    print(s['id'], durs[s['id']])
json.dump(durs, open('audio/durations.json','w'), indent=1)
print('total', round(sum(durs.values()),1), 'sr', sr)
