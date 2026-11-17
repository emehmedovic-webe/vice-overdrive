"""VICE OVERDRIVE: Demo ohne Netzwerk, API-Schlüssel oder Upload."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

CONFIG = {
    "project": "VICE OVERDRIVE",
    "mode": "demo",
    "budget_eur": 0,
    "publish_enabled": False,
    "youtube_channel": "@viceoverdrive6",
    "tiktok_channel": "@viceoverdrive",
    "twitch_watchlist": [
        "montanablack88", "eliasn97", "trymacs", "xrohat", "gtasty"
    ],
    "discovery_category": "Grand Theft Auto VI",
    "language": "de",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="vo-demo")
    args = parser.parse_args()
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            parser.exit(1, f"{binary} fehlt in der Testumgebung.\n")

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "demo.srt": "1\n00:00:00,250 --> 00:00:04,750\n"
                    "VICE OVERDRIVE · Technischer Test\nKein Gameplay · Kein Upload\n",
        "youtube.txt": "VICE OVERDRIVE – Interner Test\n\nSynthetische Vorschau. Nicht posten.\n",
        "tiktok.txt": "Interner Schnitttest. Nicht posten. #ViceOverdrive\n",
    }
    for name, contents in files.items():
        (out / name).write_text(contents, encoding="utf-8")

    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease:"
        "force_divisible_by=2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:0x150d21,"
        "subtitles=demo.srt"
    )
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
        "-t", "5", "-an", "-vf", vf, "-c:v", "libx264",
        "-preset", "veryfast", "-pix_fmt", "yuv420p", "short.mp4"
    ], cwd=out, check=True)

    result = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name",
        "-of", "json", "short.mp4"
    ], cwd=out, text=True)
    video = json.loads(result)["streams"][0]
    if (video["width"], video["height"], video["codec_name"]) != (1080, 1920, "h264"):
        raise RuntimeError(f"Unerwartetes Videoformat: {video}")

    manifest = {**CONFIG, "source": "synthetic_test_pattern", "video": video}
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Demo exportiert nach {out}. Es wurde nichts hochgeladen.")


if __name__ == "__main__":
    main()
