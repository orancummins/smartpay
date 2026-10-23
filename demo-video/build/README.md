# Re-rendering the SmartPay demo film

The film is a deterministic HTML "stage" (`stage.html`) with a `seek(t)` function, captured
frame-by-frame with Playwright and muxed with a generated voice-over.

```bash
pip install playwright kokoro-onnx soundfile scipy pillow   # plus the repo's requirements
# Kokoro model files (GitHub releases of thewh1teagle/kokoro-onnx):
#   kokoro-v1.0.onnx, voices-v1.0.bin  -> put them next to gen_vo.py or edit TTS= in it
# Inter variable font: fonts/inter/InterVariable.ttf (github.com/rsms/inter releases)

# 1. real data + screens (run from the smartpay repo root, dashboard on :9023)
python -m app.dashboard_server &
python capture_real.py          # writes real/*.json, real/*.png, real/widget_raw.html

# 2. narration -> timeline -> audio
python gen_vo.py af_heart 1.0   # audio/*.wav + audio/durations.json
python build_timeline.py        # timeline.json (scene starts + word cues)
python build_audio.py && ffmpeg -y -i audio/mix_raw.wav -af loudnorm=I=-16:TP=-1.5:LRA=11 audio/mix.wav

# 3. render
python -m http.server 9030 --bind 127.0.0.1 &
python render.py 2              # out/SmartPay-demo.mp4
```

Edit `script.json` to change the narration; cue phrases in `build_timeline.py` sync the
visuals to the words. `preview.py 12,30,85 tag` screenshots the stage at given seconds.
