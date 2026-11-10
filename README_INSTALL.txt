BABYBOT - GNANI PRISMA v2.5 + TIMBRE v2.5 VOICE UPGRADE

WHAT THIS PATCH ADDS
- Keeps the existing BabyBot Streamlit app, RAG, Webmail, reminders, tasks, notes and Community Resources.
- Adds a microphone recording control beside the text composer.
- Adds a language dropdown for English, Hindi, Hinglish, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam and Punjabi.
- Uses Gnani Prisma v2.5 for speech-to-text.
- Uses Gemini to normalise non-English questions into English for retrieval and translate answers into the selected language.
- Uses Gnani Timbre v2.5 when the student presses Listen beside an assistant response.
- Keeps written answers and the original source/download links visible.

INSTALL
1. Make a backup of your current app_backup_integrated.py.
2. Copy the included app_backup_integrated.py into your project root, replacing the old app file.
3. Copy voice_service.py into the same project root (beside app_backup_integrated.py).
4. Open the project's existing .env and add:
   GNANI_API_KEY=your_gnani_api_key
   Do not remove GEMINI_API_KEY or the IITK email settings already there.
5. In the project's activated .venv, run:
   python -m pip install requests
6. Run the app from the project root:
   python -m streamlit run app_backup_integrated.py

IMPORTANT
- Do not share your API key or commit .env to GitHub.
- The Prisma REST endpoint accepts short recordings up to 60 seconds (ideal 30 seconds).
- The app sends the selected language to Prisma; Hinglish uses Hindi STT with code-mixed recognition, and Timbre's hi-en output voice.
- If GNANI_API_KEY is missing, microphone transcription and Listen show a clear error; typed chat still works.
- Non-English translation uses Gemini and therefore consumes Gemini API quota.
- The app is patched from the integrated source file supplied in this conversation. It has been syntax-compiled, but live API calls and a full Streamlit browser test require your own keys/runtime.


CHAT LAYOUT UPDATE:
The multilingual composer is now fixed to the bottom of the AI Assistant page, like a standard chat app. The conversation retains bottom scroll space so replies are not obscured.


UPDATE: SEPARATE INPUT AND RESPONSE LANGUAGES
The composer now has two dropdowns:
- Input language: the language you speak; Prisma uses this for transcription.
- Response language: the language BabyBot writes and Timbre reads aloud.
Gemini translates the question into English for retrieval and translates the final answer
into the selected response language. The answer's Listen button uses that response language.

TIMBRE HTTP 500
The voice service retries a server-side HTTP 5xx error once. If HTTP 500 continues,
the response is coming from Gnani's service; check the Gnani dashboard for service status,
API access/credits and the exact Timbre model/voice entitlement. Do not share API keys
in screenshots or chat. Text answers and Prisma input can continue working while TTS is down.
