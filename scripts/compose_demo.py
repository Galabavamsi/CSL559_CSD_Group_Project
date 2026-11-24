"""Turn the clips recorded by record_demo.py into one captioned MP4.

Each clip is set on a 1280x720 page with its title and, beside it, the caption that record_demo.py noted for that
moment. A title card comes before each part. Needs ffmpeg with libx264 and freetype (the imageio-ffmpeg package
ships one) and a TrueType font.

Usage:  python scripts/compose_demo.py <the directory record_demo.py wrote>
"""
import json
import pathlib
import subprocess
import sys
import textwrap

import imageio_ffmpeg

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/f2h-demo")
WORK = OUT / "compose"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONTS = [p for pattern in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf")
         for p in pathlib.Path("/usr/share/fonts").rglob(pattern)]
BOLD = [p for pattern in ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "NotoSans-Bold.ttf")
        for p in pathlib.Path("/usr/share/fonts").rglob(pattern)]
FONT, FONT_BOLD = str(FONTS[0]), str((BOLD or FONTS)[0])
PAPER, INK, GREEN, MUTED = "0xFBF7F0", "0x1F2A1F", "0x2E7D32", "0x6B6F66"
# clip -> (part number and title, what is real about it, is it a phone-shaped recording)
CLIPS = {
    "1-farmer": ("1. The farmer lists produce", "Real API. The sign-in code is read from the server's log.", True),
    "2-hub-intake": ("2. The hub takes the lot in", "Real API, on the receiver's phone at the dock.", True),
    "3-customer": ("3. The customer orders", "Real API. Payment is a stand-in: no money moves.", True),
    "4-hub-picking": ("4. The hub picks and packs", "Real API, on the picker's phone screen.", True),
    "5-farmer-result": ("5. The farmer sees the grade", "Real API.", True),
    "6-customer-packed": ("6. The customer's order is packed", "Real API.", True),
    "7-agent-delivers": ("7. A delivery agent takes it to the door", "Real API. The code is read off the customer's phone.", True),
    "8-customer-delivered": ("8. The customer's order is delivered", "Real API.", True),
    "9-demo-data": ("9. On demo data", "DEMO DATA, not the backend: the same screens with made-up orders.", True),
}


def run(args: list[str]) -> None:
    done = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"ffmpeg failed:\n{done.stderr[-1500:]}")


def duration(path: pathlib.Path) -> float:
    done = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    hours, minutes, seconds = done.stderr.split("Duration: ")[1].split(",")[0].split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def text_file(name: str, text: str, width: int) -> str:
    path = WORK / f"{name}.txt"
    path.write_text("\n".join(textwrap.wrap(text, width)), encoding="utf-8")
    return str(path)


def draw(textfile: str, x: int, y: int, size: int, colour: str, font: str = FONT, when: str = "") -> str:
    enable = f":enable='{when}'" if when else ""
    return f"drawtext=fontfile={font}:textfile={textfile}:x={x}:y={y}:fontsize={size}:fontcolor={colour}:line_spacing=10{enable}"


def title_card(name: str, heading: str, body: str, seconds: float = 3.0) -> pathlib.Path:
    out = WORK / f"{name}.mp4"
    filters = ",".join([draw(text_file(f"{name}-h", heading, 44), 110, 250, 46, GREEN, FONT_BOLD),
                        draw(text_file(f"{name}-b", body, 62), 110, 360, 28, INK)])
    run(["-f", "lavfi", "-i", f"color=c={PAPER}:s=1280x720:d={seconds}:r=25", "-vf", filters,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    return out


def captioned(clip: str, captions: list[list]) -> pathlib.Path:
    title, real, phone = CLIPS[clip]
    source, out = OUT / "video" / f"{clip}.webm", WORK / f"{clip}.mp4"
    length = duration(source)
    if phone:       # the phone on the left, words on the right
        filters = [f"scale=-2:680,pad=1280:720:80:20:color={PAPER}",
                   draw(text_file(f"{clip}-t", title, 40), 470, 90, 30, GREEN, FONT_BOLD),
                   draw(text_file(f"{clip}-r", real, 46), 470, 150, 20, MUTED)]
        x, y, width, size = 470, 250, 36, 30
    else:           # the desk screen on top, words underneath
        filters = [f"scale=928:580,pad=1280:720:176:12:color={PAPER}",
                   draw(text_file(f"{clip}-t", f"{title}  ({real})", 96), 176, 602, 18, GREEN, FONT_BOLD)]
        x, y, width, size = 176, 636, 68, 24
    for n, (start, text) in enumerate(captions):
        end = captions[n + 1][0] if n + 1 < len(captions) else length
        filters.append(draw(text_file(f"{clip}-{n}", text, width), x, y, size, INK,
                            when=f"between(t\\,{start}\\,{end})"))
    run(["-i", str(source), "-vf", ",".join(filters), "-r", "25", "-c:v", "libx264", "-preset", "medium",
         "-crf", "23", "-pix_fmt", "yuv420p", "-an", str(out)])
    return out


def main() -> None:
    WORK.mkdir(exist_ok=True)
    captions = json.loads((OUT / "captions.json").read_text())
    parts = [title_card("0-opening", "JustInTimeFarm2Home",
                        "One lot of tomatoes, from a farm near Bhilai to a customer's order, on the real backend. "
                        "Recorded on 23 November 2026. Delivery is not built yet and is not shown.", 5.0)]
    for clip, (title, real, _phone) in CLIPS.items():
        if not (OUT / "video" / f"{clip}.webm").exists():
            continue
        parts.append(title_card(f"{clip}-card", title, real))
        parts.append(captioned(clip, captions.get(clip, [])))
    listing = WORK / "parts.txt"
    listing.write_text("".join(f"file '{part}'\n" for part in parts))
    final = OUT / "farm2home-demo.mp4"
    run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(final)])
    print(f"{final}: {duration(final):.0f} s, {final.stat().st_size / 1e6:.1f} MB, {len(parts)} parts")


if __name__ == "__main__":
    main()
