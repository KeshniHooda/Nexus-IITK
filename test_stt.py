
import streamlit as st
from dotenv import load_dotenv
import os

from gnani.stt import GnaniSTTClient

# Load our API key
load_dotenv()
api_key = os.getenv("GNANI_API_KEY")

st.set_page_config(page_title="BabyBot STT Test")
st.title("BabyBot - Voice Recognition")
st.write("Speak something in Hindi, English or Hinglish!")

# Record audio through your microphone
audio = st.audio_input("Record your voice")

if audio is not None:
    if not api_key:
        st.error("Gnani API key not found!")
    else:
        with st.spinner("BabyBot is listening..."):
            client = GnaniSTTClient(api_key=api_key)

            result = client.transcribe_bytes(
                audio.getvalue(),
                filename="recording.wav",
                language_code="hi-IN"
            )

        st.success("Transcription successful!")
        st.write("### BabyBot heard:")
        st.write(result["transcript"])
