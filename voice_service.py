"""Gnani Prisma v2.5 STT and Timbre v2.5 TTS helpers for BabyBot."""
from __future__ import annotations

import os
import requests
import time

STT_URL = "https://api.vachana.ai/stt/v3"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

LANGUAGES = {
    "English": {"stt": "en-IN", "tts": "en-IN", "voice": "Kaveri"},
    "Hindi": {"stt": "hi-IN", "tts": "hi-IN", "voice": "Nalini"},
    "Hinglish": {"stt": "hi-IN", "tts": "hi-en", "voice": "Poorvi"},
    "Bengali": {"stt": "bn-IN", "tts": "bn-IN", "voice": "Kirra"},
    "Tamil": {"stt": "ta-IN", "tts": "ta-IN", "voice": "Trisha"},
    "Telugu": {"stt": "te-IN", "tts": "te-IN", "voice": "Suhana"},
    "Marathi": {"stt": "mr-IN", "tts": "mr-IN", "voice": "Zahira"},
    "Gujarati": {"stt": "gu-IN", "tts": "gu-IN", "voice": "Falak"},
    "Kannada": {"stt": "kn-IN", "tts": "kn-IN", "voice": "Saanvi"},
    "Malayalam": {"stt": "ml-IN", "tts": "ml-IN", "voice": "Reshma"},
    "Punjabi": {"stt": "pa-IN", "tts": "pa-IN", "voice": "Mehuli"},
}


def _api_key() -> str:
    key = os.getenv("GNANI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GNANI_API_KEY is missing. Add it to your project's .env file.")
    return key


def transcribe_audio(audio_bytes: bytes, filename: str, language: str) -> str:
    """Transcribe a short browser-recorded clip using Prisma v2.5."""
    if not audio_bytes:
        raise ValueError("No audio was recorded. Please try recording again.")
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported input language: {language}")
    mime = "audio/wav"
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "wav").lower()
    if ext == "mp3":
        mime = "audio/mpeg"
    elif ext == "m4a":
        mime = "audio/mp4"
    elif ext == "ogg":
        mime = "audio/ogg"
    elif ext == "flac":
        mime = "audio/flac"
    elif ext == "aac":
        mime = "audio/aac"
    files = {"audio_file": (filename or "recording.wav", audio_bytes, mime)}
    data = {"language_code": LANGUAGES[language]["stt"], "format": "transcribe"}
    try:
        response = requests.post(
            STT_URL,
            headers={"X-API-Key-ID": _api_key()},
            data=data,
            files=files,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Gnani Prisma: {exc}") from exc
    if not response.ok:
        detail = response.text[:500]
        raise RuntimeError(f"Gnani Prisma returned HTTP {response.status_code}: {detail}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Gnani Prisma returned an unreadable response.") from exc
    transcript = (payload.get("transcript") or "").strip()
    if not payload.get("success", True) or not transcript:
        raise RuntimeError(payload.get("error", {}).get("message", "No speech was detected."))
    return transcript


def synthesize_speech(text: str, language: str) -> bytes:
    """Generate a WAV response using Gnani Timbre v2.5."""
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("There is no response text to read aloud.")
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported output language: {language}")
    # Keep synthesis bounded; the written answer and citations remain available in chat.
    if len(clean_text) > 5000:
        clean_text = clean_text[:5000]
    config = LANGUAGES[language]
    payload = {
        "text": clean_text,
        "model": "timbre-v2.5",
        "voice": config["voice"],
        "language": config["tts"],
        "speed": 1.0,
        "audio_config": {
            "encoding": "linear_pcm",
            "container": "wav",
            "num_channels": 1,
            "sample_rate": 24000,
            "sample_width": 2,
        },
    }
    headers = {"X-API-Key-ID": _api_key(), "Content-Type": "application/json"}
    response = None
    # Timbre occasionally returns transient 5xx errors. Retry once; do not
    # repeatedly hit the service or retry authentication/validation failures.
    for attempt in range(2):
        try:
            response = requests.post(
                TTS_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(1.5)
                continue
            raise RuntimeError(f"Could not reach Gnani Timbre after one retry: {exc}") from exc
        if response.status_code >= 500 and attempt == 0:
            time.sleep(1.5)
            continue
        break
    if response is None:
        raise RuntimeError("Gnani Timbre did not return a response.")
    if not response.ok:
        detail = response.text[:500]
        if response.status_code >= 500:
            raise RuntimeError(
                f"Gnani Timbre is currently returning HTTP {response.status_code} after a retry. "
                f"This is likely a provider-side temporary failure. Details: {detail}"
            )
        raise RuntimeError(f"Gnani Timbre returned HTTP {response.status_code}: {detail}")
    if not response.content:
        raise RuntimeError("Gnani Timbre returned an empty audio response.")
    return response.content
