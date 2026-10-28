import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

MAX_FRAMES = int(os.environ.get("VIDEO_MAX_FRAMES", "6"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

EXTENSIONS = {
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-wav": ".wav",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


@dataclass
class MediaExtract:
    transcript: str = ""
    frames: list[bytes] = field(default_factory=list)


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=300)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return 0.0


def extract_audio(source: Path, target: Path) -> Path | None:
    try:
        run_ffmpeg(["-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(target)])
    except subprocess.CalledProcessError:
        return None
    return target if target.exists() and target.stat().st_size > 0 else None


def extract_frames(source: Path, out_dir: Path, max_frames: int = MAX_FRAMES) -> list[bytes]:
    duration = probe_duration(source)
    interval = max(duration / max_frames, 0.5) if duration else 1.0
    pattern = out_dir / "frame_%03d.jpg"
    run_ffmpeg(["-i", str(source), "-vf", f"fps=1/{interval:.3f},scale=768:-2", "-frames:v", str(max_frames),
                str(pattern)])
    return [path.read_bytes() for path in sorted(out_dir.glob("frame_*.jpg"))]


@lru_cache(maxsize=1)
def whisper_model():
    from faster_whisper import WhisperModel

    return WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)


def transcribe(path: Path) -> str:
    segments, _ = whisper_model().transcribe(str(path), vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()


def process_media(media_type: str, mime_type: str, data: bytes) -> MediaExtract:
    suffix = EXTENSIONS.get(mime_type, ".bin")
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        source = root / f"input{suffix}"
        source.write_bytes(data)
        if media_type in {"voice", "audio"}:
            return MediaExtract(transcript=transcribe(source))
        audio = extract_audio(source, root / "audio.wav")
        transcript = transcribe(audio) if audio else ""
        frames_dir = root / "frames"
        frames_dir.mkdir()
        return MediaExtract(transcript=transcript, frames=extract_frames(source, frames_dir))
