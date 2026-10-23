"""Compute the scene timeline from the real narration durations.

Each scene starts, waits `lead` seconds, plays its voice-over, then holds `tail`
seconds. Named cues inside a scene are located by the character offset of a phrase
in the narration text (TTS pacing is close enough to linear for sync purposes).
"""
import json

script = {s["id"]: s["text"] for s in json.load(open("script.json"))}
durs = json.load(open("audio/durations.json"))

# (scene id, lead, tail, {cue name: phrase in narration})
SCENES = [
    ("s1_title", 1.4, 1.4, {
        "meet": "Meet SmartPay", "payment": "Payment intelligence", "built": "built to live",
        "yourai": "Your AI knows", "smartpay": "SmartPay knows"}),
    ("s2_alex", 0.6, 0.9, {
        "alex": "This is Alex", "three": "Three banks", "nine": "nine accounts", "seven": "seven cards",
        "twelve": "twelve months", "connected": "all connected", "habit": "Like most of us",
        "sapphire": "The Sapphire", "double": "the Double Cash", "rarely": "And habit is rarely"}),
    ("s3_how", 0.6, 0.9, {
        "mcp": "SmartPay runs", "chatgpt": "ChatGPT understands", "tools": "calls SmartPay's",
        "engine": "A deterministic", "infers": "It infers", "tests": "tests every", "compares": "and compares",
        "nollm": "No language model", "evidence": "and every number"}),
    ("s4a_ask", 0.8, 0.4, {
        "inside": "Here's what it feels", "asks": "Alex asks", "plans": "ChatGPT plans it", "flights": "flights, hotel",
        "total": "Seven thousand", "hands": "Then it hands"}),
    ("s4b_widget", 0.3, 0.5, {
        "arrives": "The answer arrives", "live": "live SmartPay", "five": "Five hundred", "compared": "compared with",
        "every": "And for every line", "reached": "the card Alex would", "recommends": "the card SmartPay",
        "channel": "and the channel"}),
    ("s4c_detail", 0.3, 1.0, {
        "bags": "Three hundred and sixty", "aadv": "with the AAdvantage", "hotel": "A hundred dollars off",
        "tenx": "at ten times", "offers": "Real Mastercard card-linked", "eye": "and the Orlando Eye",
        "tie": "And where two cards", "funds": "Mastercard funds", "says": "and says so"}),
    ("s5_honesty", 0.6, 0.9, {
        "traceable": "Every figure", "guaranteed": "Guaranteed value", "never": "is never merged",
        "source": "Every rule carries", "channel": "Channel rules", "readonly": "SmartPay is read-only",
        "never_moves": "It never moves", "golf": "Even the Priceless", "sixteen": "sixteen rounds"}),
    ("s6_dashboard", 0.6, 0.9, {
        "behind": "Behind the conversation", "amount": "One thousand", "computed": "computed by",
        "every": "Every question", "lands": "lands here", "priceless": "alongside Priceless"}),
    ("s7_wallet", 0.6, 0.9, {
        "onemore": "And one more thing", "ask": "Ask SmartPay", "forecasts": "it forecasts", "tests": "and tests every",
        "flags": "Here, it flags", "funded": "and a funded offer", "mastercard": "For Mastercard",
        "portfolio": "portfolio performance", "flipper": "and Flipper", "funds": "that funds offers"}),
    ("s8_close", 0.8, 4.5, {
        "smartpay": "SmartPay.", "right": "The right card", "accepted": "From accepted", "chosen": "to chosen"}),
]

t = 0.0
timeline = {"scenes": [], "fps": 30}
for sid, lead, tail, cues in SCENES:
    text = script[sid]
    vo = durs[sid]
    start = t
    vo_start = start + lead
    end = vo_start + vo + tail
    cue_times = {}
    for name, phrase in cues.items():
        idx = text.find(phrase)
        assert idx >= 0, (sid, phrase)
        cue_times[name] = round(vo_start + vo * idx / len(text), 3)
    timeline["scenes"].append({
        "id": sid, "start": round(start, 3), "vo_start": round(vo_start, 3), "vo_dur": vo,
        "end": round(end, 3), "cues": cue_times,
    })
    t = end
timeline["total"] = round(t, 3)
json.dump(timeline, open("timeline.json", "w"), indent=1)
for s in timeline["scenes"]:
    print(f"{s['id']:14s} {s['start']:7.2f} -> {s['end']:7.2f}  vo {s['vo_dur']:5.1f}")
print("total", timeline["total"])
