
from dotenv import load_dotenv
import os

from gnani.tts import GnaniTTSClient, AudioConfig

# Load credentials from .env
load_dotenv()

api_key = os.getenv("GNANI_API_KEY")

if not api_key:
    raise ValueError("Gnani API key not found!")

# Connect to Gnani's Text-to-Speech service
client = GnaniTTSClient(api_key=api_key)

# Generate speech
audio = client.synthesize(
    "Namaste! Main BabyBot hoon. Welcome to IIT Kanpur!",
    voice="Nalini",
    model="timbre-v2.5",
    language="hi-IN",
    audio_config=AudioConfig(
        container="mp3",
        sample_rate=48000,
        bitrate="128k"
    )
)

# Save the generated audio
with open("babybot_test.mp3", "wb") as file:
    file.write(audio)

print("SUCCESS! BabyBot generated its first voice response.")
