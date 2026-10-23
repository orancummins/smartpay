"""Render the stage deterministically: seek(t) per frame, pipe JPEG frames to ffmpeg.

Workers split the frame range; each produces an H.264 segment, then the segments
are concatenated and muxed with the audio mix.
"""
import asyncio, json, os, subprocess, sys, time
from multiprocessing import Process
from playwright.async_api import async_playwright

FPS = 30
TL = json.load(open("timeline.json"))
TOTAL = TL["total"]
NFRAMES = int(TOTAL * FPS)
OUT = "out"
os.makedirs(OUT, exist_ok=True)

async def worker(idx, f0, f1):
    seg = f"{OUT}/seg_{idx:02d}.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-vcodec", "mjpeg", "-i", "-",
        "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), seg,
    ], stdin=subprocess.PIPE)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--font-render-hinting=none", "--disable-gpu-vsync"])
        pg = await b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        await pg.goto("http://127.0.0.1:9030/stage.html", wait_until="load")
        await pg.wait_for_function("window.READY === true", timeout=120000)
        await pg.evaluate("document.fonts.ready")
        await pg.evaluate("seek(0)")
        await pg.wait_for_timeout(300)
        t_start = time.time()
        for f in range(f0, f1):
            t = f / FPS
            await pg.evaluate(f"seek({t})")
            data = await pg.screenshot(type="jpeg", quality=94)
            ff.stdin.write(data)
            if (f - f0) % 300 == 0:
                el = time.time() - t_start
                print(f"[w{idx}] frame {f}/{f1} ({(f-f0)/max(el,1e-6):.1f} fps)", flush=True)
        await b.close()
    ff.stdin.close(); ff.wait()
    print(f"[w{idx}] done {seg}", flush=True)

def run(idx, f0, f1):
    asyncio.run(worker(idx, f0, f1))

if __name__ == "__main__":
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    bounds = [round(i * NFRAMES / nw) for i in range(nw + 1)]
    procs = [Process(target=run, args=(i, bounds[i], bounds[i+1])) for i in range(nw)]
    for p in procs: p.start()
    for p in procs: p.join()
    with open(f"{OUT}/concat.txt", "w") as fh:
        for i in range(nw): fh.write(f"file 'seg_{i:02d}.mp4'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{OUT}/concat.txt", "-c", "copy", f"{OUT}/video_only.mp4"], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{OUT}/video_only.mp4", "-i", "audio/mix.wav",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", f"{OUT}/SmartPay-demo.mp4"], check=True)
    print("FINAL", f"{OUT}/SmartPay-demo.mp4")
