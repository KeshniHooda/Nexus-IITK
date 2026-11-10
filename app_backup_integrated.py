import re

import os
import streamlit as st
from dotenv import load_dotenv
from google import genai

from reminder_store import (
    initialise as initialise_reminder_store, add_manual, list_manual,
    delete_manual, list_extracted_reminders, set_completed, delete_extracted,
    add_extracted_reminder,
    add_task, list_tasks, set_task_done, delete_task
)
from email_monitor import scan_inbox, extract_academic_items
from webmail import search_emails
from rag_engine import answer_with_rag_if_relevant
from community_resources import add_drive_resource, add_uploaded_file, list_resources, delete_resource, search_resources, format_results, get_file_path
from voice_service import LANGUAGES, transcribe_audio, synthesize_speech

# =============================================
# 1. CONFIGURATION
# =============================================

load_dotenv()
initialise_reminder_store()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.8-flash"


st.set_page_config(
    page_title="Nexus | IITK",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =============================================
# 2. BABYBOT IDENTITY
# =============================================

BABYBOT_SYSTEM_INSTRUCTION = """
You are Nexus, an AI academic assistant built primarily
for students of the Indian Institute of Technology Kanpur (IITK).

IDENTITY:
- Your name is Nexus.
- Do not invent IITK portals, LMS platforms, services, integrations, or email-search results.
- The only currently connected institutional source is the user's IITK Webmail Inbox.
- Never claim you searched Webmail unless the application has returned actual search results.
- If a platform is not confirmed by the user or connected in the app, say you do not know whether IITK uses it.
- You are a friendly, reliable IITK academic companion.
- Never introduce yourself as Gemini or Google's AI unless
  explicitly asked which model powers you.
- Gemini is the technology powering you. Nexus is the product.

YOUR PURPOSE:

1. ACADEMICS:
Help with courses, lectures, assignments, quizzes, exams,
grading, study plans and academic concepts.

2. IITK INFORMATION:
Help students find academic calendars, institute notices,
deadlines, course information and administrative procedures.

3. CAMPUS LIFE:
Help with clubs, events, campus facilities and opportunities.

4. PERSONAL ORGANISATION:
Help students manage reminders, tasks and notes.

5. GENERAL ASSISTANCE:
Answer general questions while prioritising your role
as an IITK academic assistant.

PERSONALITY:
- Friendly, approachable and encouraging.
- Understand English and Hinglish.
- Explain difficult concepts step by step.
- Keep simple answers concise.

ACCURACY:
- Never invent IITK-specific dates, deadlines or policies.
- IITK Webmail is connected in read-only mode. Other IITK portals
  and academic databases are not connected yet. Never pretend that they are.
- If information is unavailable, say so honestly.
- Distinguish general guidance from verified IITK information.
- Never claim to have completed an action unless it was
  actually performed by the application.

INTRODUCTION:
When asked to introduce yourself, explain that you are
Nexus, an AI academic assistant designed to make academic
life at IITK easier by bringing academic information,
learning assistance and personal organisation into one place.
"""


# =============================================
# 3. SESSION STATE
# =============================================

defaults = {
    "page": "AI Assistant",
    "messages": [],
    "reminders": [],
    "tasks": [],
    "notes": [],
    "chats": [],
    "chat_counter": 0,
    "pending_email_matches": [],
    "pending_email_action": "reminder",
    "selected_input_language": "English",
    "selected_response_language": "English",
    "tts_audio_cache": {}
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# Migrate the earlier single-language preference without breaking existing sessions.
if "selected_language" in st.session_state:
    old_language = st.session_state.pop("selected_language")
    st.session_state.setdefault("selected_input_language", old_language)
    st.session_state.setdefault("selected_response_language", old_language)


# =============================================
# 4. GEMINI FUNCTIONS
# =============================================



def get_gemini_reply(chat_messages):

    if not GEMINI_API_KEY:
        raise ValueError("Gemini API key not found in .env")

    client = genai.Client(api_key=GEMINI_API_KEY)

    gemini_history = []

    for message in chat_messages:

        role = (
            "model"
            if message["role"] == "assistant"
            else "user"
        )

        gemini_history.append({
            "role": role,
            "parts": [{"text": message["content"]}]
        })

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=gemini_history,
        config=genai.types.GenerateContentConfig(
            system_instruction=BABYBOT_SYSTEM_INSTRUCTION
        )
    )

    if not response.text:
        raise RuntimeError("Gemini returned an empty response.")

    return response.text



def translate_with_gemini(text, target_language, mode="answer"):
    """Translate while preserving course codes, URLs, Markdown links and citations."""
    if target_language == "English" or not text.strip():
        return text
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API key not found in .env; translation requires Gemini.")
    client = genai.Client(api_key=GEMINI_API_KEY)
    if mode == "query":
        instruction = (
            "Translate the student's question into clear English for IIT Kanpur knowledge retrieval. "
            "Preserve exact course codes, names, numbers, dates and technical terms. "
            "Return only the translated question; do not answer it."
        )
    else:
        instruction = (
            f"Translate the following Nexus answer into natural {target_language}. "
            "Preserve all facts, course codes, dates, numbers, URLs, Markdown formatting, "
            "Markdown link destinations, and citation markers such as [1] exactly. "
            "Do not add facts, remove sources, or translate URLs/course codes. "
            "Return only the translated answer."
        )
    # Protect URLs and numbered citations so translation cannot alter destinations or references.
    protected = {}
    def _protect(match):
        token = f"BABYBOTKEEP{len(protected)}TOKEN"
        protected[token] = match.group(0)
        return token
    safe_text = re.sub(r"https?://[^\s)]+|\[\d+\]", _protect, text)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{instruction}\n\nTEXT:\n{safe_text}",
        config={"temperature": 0.0},
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty translation.")
    translated = response.text.strip()
    for token, original in protected.items():
        translated = translated.replace(token, original)
    return translated


def clean_for_speech(markdown_text):
    """Remove Markdown link destinations and citation markers from spoken audio."""
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1', markdown_text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'(?m)^\s*[-*#>`]+\s*', '', text)
    text = re.sub(r'\*\*|__|`|~~|\*', '', text)
    text = re.sub(r'\[\d+\]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def is_email_action_request(prompt):
    # Route both "find an email" and "find an email and save it" to real Webmail search.
    text = prompt.lower()
    mentions_mail = any(word in text for word in ("mail", "email", "inbox"))
    mentions_find = any(word in text for word in ("find", "search", "look for", "locate"))
    return mentions_mail and mentions_find


def email_search_query(prompt):
    query = prompt
    patterns = [
        r"\b(find|search for|look for|locate)\b",
        r"\b(an? email|the email|an? mail|the mail|mail|email|inbox)\b",
        r"\b(and )?(add|save|put)\b.*$",
        r"\b(to )?(my )?(reminders?|to[- ]?do list|tasks?|notes?)\b.*$",
        r"\b(regarding|about)\b",
    ]
    for pattern in patterns:
        query = re.sub(pattern, " ", query, flags=re.IGNORECASE)
    query = re.sub(r"[^A-Za-z0-9@._-]+", " ", query)
    return " ".join(query.split()).strip() or prompt


def _quiz_reminder_from_email(message):
    """Deterministically recover an explicitly dated quiz from the selected email."""
    subject = (message.get("subject") or "").strip()
    body = (message.get("body") or "").strip()
    combined = subject + "\n" + body

    course_match = re.search(r"\b(EE\s*\d{3,4})\b", subject, re.IGNORECASE)
    course = re.sub(r"\s+", "", course_match.group(1)).upper() if course_match else None
    quiz_match = re.search(r"\b(Major\s+Quiz\s*\d*)\b", subject, re.IGNORECASE)
    if not quiz_match:
        quiz_match = re.search(r"\b(Major\s+Quiz\s*\d*)\b", body, re.IGNORECASE)
    if not quiz_match:
        return None

    # Look for a date close to the major-quiz sentence, rather than borrowing
    # dates belonging to other events mentioned in the same email.
    sentence = re.search(
        re.escape(quiz_match.group(1)) + r"[^\n]{0,160}",
        body, re.IGNORECASE
    )
    date_scope = sentence.group(0) if sentence else body
    date_match = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", date_scope)
    if not date_match:
        return None
    day, month, year = map(int, date_match.groups())
    try:
        event_date = f"{year:04d}-{month:02d}-{day:02d}"
        from datetime import date as _date
        _date.fromisoformat(event_date)
    except ValueError:
        return None

    quiz_name = quiz_match.group(1).title().replace("  ", " ")
    title = f"{course} {quiz_name}" if course else quiz_name
    time_note = "The email says it will be held during regular tutorial hours; exact time is not announced."
    if re.search(r"regular\s+tutorial\s+hours", date_scope, re.IGNORECASE):
        details = time_note
    else:
        details = "Date explicitly stated in the selected IITK Webmail announcement."
    return {
        "title": title,
        "category": "Quiz",
        "item_type": "academic_reminder",
        "course": course,
        "event_date": event_date,
        "event_time": None,
        "details": details,
        "confidence": "high",
    }


def save_selected_email(message, action):
    source = {key: message.get(key) for key in ("subject", "sender", "date", "uid")}
    if action == "reminder":
        if not GEMINI_API_KEY:
            raise ValueError("Gemini API key not found in .env")
        # For a clearly named and explicitly dated quiz, use the email text
        # directly. This avoids model omissions and unnecessary API calls.
        exact_quiz = _quiz_reminder_from_email(message)
        if exact_quiz:
            items = [exact_quiz]
        else:
            client = genai.Client(api_key=GEMINI_API_KEY)
            items = extract_academic_items(client, message)

        if not items:
            return "I couldn't extract a dated academic item from this email, so I haven't added a reminder. You can still save it as a note."

        saved = 0
        for item in items:
            item["item_type"] = "academic_reminder"
            if add_extracted_reminder(item, source):
                saved += 1
        if saved:
            names = ", ".join(item.get("title", "Reminder") for item in items)
            return f"Added **{names}** to Reminders."
        return "This reminder is already in your Reminders, so I didn't create a duplicate."

    title = (message.get("subject") or "Task from email").strip()[:180]
    details = (message.get("body") or "")[:1200]
    add_task(title, "Medium", source=source, details=details)
    return f"Added **{title}** to your To-Do List, with its email source attached."



# =============================================
# 5. CUSTOM CSS
# =============================================

st.markdown("""
<style>

.stApp {
    background-color: #11151B;
    color: #E8E9E6;
}

.block-container {
    max-width: 1200px;
    padding-top: 2.5rem;
    padding-bottom: 2rem;
}

section[data-testid="stSidebar"] {
    background-color: #1B222B;
    border-right: 1px solid #303944;
    min-width: 290px;
}

section[data-testid="stSidebar"] > div {
    padding: 1.8rem 1.2rem;
}

.brand-title {
    font-size: 36px;
    font-weight: 800;
    letter-spacing: -1.5px;
    color: #E8E9E6;
    margin-bottom: 2px;
}

.brand-subtitle {
    font-size: 15px;
    color: #9BAF9D;
    margin-bottom: 28px;
}

.sidebar-label {
    color: #91A398;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.3px;
    margin-top: 25px;
    margin-bottom: 10px;
}

section[data-testid="stSidebar"] div.stButton > button {
    width: 100%;
    min-height: 48px;
    border-radius: 10px;
    text-align: left;
    font-size: 16px;
    font-weight: 500;
}

section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {
    background: #34453D;
    color: #E4EEE4;
    border: 1px solid #536B5B;
    border-left: 4px solid #A4BCA5;
    font-weight: 700;
}

section[data-testid="stSidebar"] div.stButton > button[kind="secondary"] {
    background: transparent;
    color: #C2C8CA;
    border: 1px solid transparent;
}

section[data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover {
    background: #28323A;
    border-color: #414E49;
    color: #FFFFFF;
}

h1, h2, h3 {
    color: #E8E9E6 !important;
}

.hero {
    text-align: center;
    padding-top: 100px;
    padding-bottom: 40px;
}

.hero h1 {
    font-size: 40px;
    font-weight: 750;
    letter-spacing: -1.2px;
    color: #E8E9E6;
    margin-bottom: 12px;
}

.hero p {
    font-size: 17px;
    color: #A8B2B0;
}

[data-testid="stChatInput"] {
    background: #202832;
    border: 1px solid #39463F;
    border-radius: 16px;
}

[data-testid="stChatInput"]:focus-within {
    border-color: #9BAF9D;
}

div[data-testid="stForm"] {
    background: #1B222B;
    border: 1px solid #303944;
    padding: 22px;
    border-radius: 15px;
}

.stTextInput input,
.stTextArea textarea {
    background: #202832;
    color: #E8E9E6;
    border: 1px solid #39463F;
    border-radius: 9px;
}

.stButton button,
.stFormSubmitButton button {
    border-radius: 9px;
}

hr {
    border-color: #354039;
}

.stCaption {
    color: #A8B2B0;
}

[data-testid="stExpander"] {
    background: #1B222B;
    border: 1px solid #303944;
    border-radius: 12px;
}

</style>
""", unsafe_allow_html=True)


# =============================================
# 6. NAVIGATION
# =============================================

def navigation_button(label, icon, page):

    selected = st.session_state.page == page

    if st.button(
        f"{icon}   {label}",
        key=f"nav_{page}",
        use_container_width=True,
        type="primary" if selected else "secondary"
    ):
        st.session_state.page = page
        st.rerun()


# =============================================
# 7. SIDEBAR
# =============================================

with st.sidebar:

    st.markdown("""
    <div class="brand-title">✦ Nexus</div>
    <div class="brand-subtitle">
        Your personal IITK companion
    </div>
    """, unsafe_allow_html=True)

    if st.button(
        "＋   New Chat",
        use_container_width=True,
        type="primary"
    ):
        st.session_state.messages = []
        st.session_state.page = "AI Assistant"
        st.rerun()

    st.markdown(
        '<div class="sidebar-label">YOUR SPACE</div>',
        unsafe_allow_html=True
    )

    navigation_button("AI Assistant", "💬", "AI Assistant")
    navigation_button("Reminders", "🔔", "Reminders")
    navigation_button("To-Do List", "✓", "To-Do List")
    navigation_button("Notes", "📝", "Notes")
    navigation_button("Community Resources", "📚", "Community Resources")

    st.markdown("---")

    st.markdown(
        '<div class="sidebar-label">RECENT CONVERSATIONS</div>',
        unsafe_allow_html=True
    )

    if st.session_state.chats:
        for chat in reversed(st.session_state.chats[-5:]):
            st.caption("💬  " + chat["title"])
    else:
        st.caption("Your conversations will appear here.")

    st.markdown("---")
    st.caption("⚙️  Settings")


# =============================================
# 8. AI ASSISTANT
# =============================================

if st.session_state.page == "AI Assistant":

    # Keep the custom multilingual composer anchored at the bottom, like a
    # conventional chat app. The main conversation gets enough bottom space
    # so the last response is never hidden behind the composer.
    st.markdown("""
    <style>
    section.main div[data-testid="stForm"]:has(input[aria-label="Message Nexus"]) {
        position: fixed;
        z-index: 999;
        bottom: 1rem;
        left: max(16rem, calc((100vw - 1200px + 15.5rem) / 2));
        right: max(1.5rem, calc((100vw - 1200px - 15.5rem) / 2));
        width: auto;
        margin: 0;
        background: rgba(27, 34, 43, 0.97);
        border: 1px solid #39463F;
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.38);
        backdrop-filter: blur(12px);
    }
    section.main div[data-testid="stForm"]:has(input[aria-label="Message Nexus"]) [data-testid="stFormSubmitButton"] button {
        min-height: 2.65rem;
    }
    @media (max-width: 800px) {
        section.main div[data-testid="stForm"]:has(input[aria-label="Message Nexus"]) {
            left: 1rem;
            right: 1rem;
            bottom: 0.5rem;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    if not st.session_state.messages:

        st.markdown("""
        <div class="hero">
            <h1>What can I help you with today?</h1>
            <p>
                Your academics, your emails, your deadlines.
                Everything in one place.
            </p>
        </div>
        """, unsafe_allow_html=True)

    # Display previous messages and per-answer Listen controls.
    for message_index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("content"):
                voice_language = message.get("language", st.session_state.selected_response_language)
                cache_key = f"{message_index}:{voice_language}"
                if st.button("🔊 Listen", key=f"listen_{message_index}"):
                    try:
                        with st.spinner("Generating Nexus audio with Gnani Timbre..."):
                            audio = synthesize_speech(clean_for_speech(message["content"]), voice_language)
                        st.session_state.tts_audio_cache[cache_key] = audio
                    except Exception as error:
                        st.warning(f"Voice playback is unavailable: {error}")
                if cache_key in st.session_state.tts_audio_cache:
                    st.audio(st.session_state.tts_audio_cache[cache_key], format="audio/wav")

    # Composer: fixed bottom chat input with independent input/output languages.
    with st.form("Nexus_multilingual_composer", clear_on_submit=True):
        input_col, mic_col, input_language_col, response_language_col = st.columns([5.4, 1.25, 1.65, 1.8])
        with input_col:
            typed_prompt = st.text_input(
                "Message Nexus",
                placeholder="Type your question...",
                label_visibility="collapsed",
            )
        with mic_col:
            if hasattr(st, "audio_input"):
                recorded_audio = st.audio_input("Speak", label_visibility="collapsed")
            else:
                recorded_audio = None
                st.caption("Update Streamlit for microphone input")
        with input_language_col:
            selected_input_language = st.selectbox(
                "Input language",
                list(LANGUAGES.keys()),
                index=list(LANGUAGES.keys()).index(st.session_state.selected_input_language),
                key="Nexus_input_language",
                help="Choose the language you will speak. This is used by Prisma.",
            )
        with response_language_col:
            selected_response_language = st.selectbox(
                "Response language",
                list(LANGUAGES.keys()),
                index=list(LANGUAGES.keys()).index(st.session_state.selected_response_language),
                key="Nexus_response_language",
                help="Choose the language Nexus will write and speak in.",
            )
        send_message = st.form_submit_button("Send", use_container_width=True)

    # Leave room for the fixed composer so the latest conversation remains visible.
    st.markdown('<div style="height: 150px;"></div>', unsafe_allow_html=True)

    st.session_state.selected_input_language = selected_input_language
    st.session_state.selected_response_language = selected_response_language
    prompt = None
    if send_message:
        if recorded_audio is not None:
            try:
                with st.spinner(f"Transcribing your {selected_input_language} speech with Gnani Prisma..."):
                    prompt = transcribe_audio(recorded_audio.getvalue(), recorded_audio.name or "recording.wav", selected_input_language)
                st.info(f"Detected speech: {prompt}")
            except Exception as error:
                st.error(f"Could not transcribe audio: {error}")
        else:
            prompt = (typed_prompt or "").strip()

    if prompt:
        original_prompt = prompt
        try:
            retrieval_prompt = translate_with_gemini(original_prompt, "English", mode="query") if selected_input_language != "English" else original_prompt
        except Exception as error:
            st.error(f"Could not prepare the question for English retrieval: {error}")
            retrieval_prompt = original_prompt

        # Save user message
        st.session_state.messages.append({
            "role": "user",
            "content": original_prompt,
            "language": selected_input_language
        })

        with st.chat_message("user"):
            st.markdown(original_prompt)

        # Route the English-normalised query while preserving the student's original wording.
        with st.chat_message("assistant"):
            try:
                if is_email_action_request(retrieval_prompt):
                    lower_prompt = retrieval_prompt.lower()
                    save_requested = any(word in lower_prompt for word in ("add", "save", "put", "reminder", "deadline", "to-do", "todo", "task"))
                    action = "reminder" if ("reminder" in lower_prompt or "deadline" in lower_prompt) else "task"
                    if any(word in lower_prompt for word in ("to-do", "todo", "task")):
                        action = "task"
                    if not save_requested:
                        action = None
                    query = email_search_query(retrieval_prompt)
                    with st.spinner(f"Searching IITK Webmail for: {query}..."):
                        matches = search_emails(query, limit=8, days_back=365)
                    if not matches:
                        reply = f"I couldn't find a matching email for **{query}** in the last year. Try a more specific course code, sender, or subject keyword."
                    elif len(matches) == 1 and action:
                        with st.spinner("Reading the email and saving it..."):
                            reply = save_selected_email(matches[0], action)
                    else:
                        st.session_state.pending_email_matches = matches
                        st.session_state.pending_email_action = action
                        if action:
                            destination = "Reminders" if action == "reminder" else "To-Do List"
                            reply = f"I found **{len(matches)} matching emails**. Choose the correct one below and I'll save it to your {destination}."
                        else:
                            reply = f"I found **{len(matches)} matching emails**. Choose one below to preview it; you can then save it to Reminders or your To-Do List."
                    if selected_response_language != "English":
                        reply = translate_with_gemini(reply, selected_response_language, mode="answer")
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply, "language": selected_response_language})

                elif any(term in retrieval_prompt.lower() for term in ("resource", "pyq", "previous year", "midsem", "mid-sem", "endsem", "end-sem", "quiz", "lecture notes", "assignment", "notes", "material", "papers", "paper", "slides")):
                    with st.spinner("Nexus is finding all matching course resources..."):
                        result = search_resources(retrieval_prompt, GEMINI_API_KEY or "", GEMINI_MODEL)
                        reply = format_results(result)
                    if selected_response_language != "English":
                        reply = translate_with_gemini(reply, selected_response_language, mode="answer")
                    st.markdown(reply)
                    for resource_item in result.get("items", []):
                        local_path = get_file_path(resource_item)
                        if local_path:
                            with open(local_path, "rb") as resource_file:
                                st.download_button(
                                    f"⬇️ Download {resource_item['title']}",
                                    data=resource_file.read(),
                                    file_name=resource_item.get("original_name") or resource_item["title"],
                                    key=f"chat_resource_download_{resource_item['id']}",
                                )
                    st.session_state.messages.append({"role": "assistant", "content": reply, "language": selected_response_language})

                else:
                    with st.spinner("Nexus is understanding your question and checking IITK sources..."):
                        reply = answer_with_rag_if_relevant(
                            retrieval_prompt,
                            st.session_state.messages,
                            GEMINI_API_KEY,
                            GEMINI_MODEL,
                        )
                        if reply is None:
                            reply = get_gemini_reply(st.session_state.messages)
                    if selected_response_language != "English":
                        reply = translate_with_gemini(reply, selected_response_language, mode="answer")
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply, "language": selected_response_language})
            except Exception as error:
                st.error(f"I couldn't complete that action: {type(error).__name__}: {error}")
                reply = "I ran into a problem while handling that request. Please check the error above."
                st.session_state.messages.append({"role": "assistant", "content": reply, "language": selected_response_language})

        # Save recent conversation title
        if len(st.session_state.messages) <= 2:
            st.session_state.chat_counter += 1
            st.session_state.chats.append({
                "id": st.session_state.chat_counter,
                "title": original_prompt[:35]
            })

    # If search returned multiple candidates, let the user select the exact email.
    if st.session_state.pending_email_matches:
        st.markdown("### Select the email Nexus should use")
        options = st.session_state.pending_email_matches
        labels = [
            f"{m.get('subject') or '(No subject)'} · {m.get('sender') or 'Unknown sender'} · {m.get('date') or 'Date unknown'}"
            for m in options
        ]
        chosen = st.selectbox("Matching emails", range(len(options)), format_func=lambda i: labels[i], key="email_match_choice")
        with st.expander("Preview selected email"):
            st.write(f"**From:** {options[chosen].get('sender', 'Unknown sender')}")
            st.write(f"**Date:** {options[chosen].get('date', 'Unknown')}")
            st.write((options[chosen].get("body") or "")[:1800])
        pending_action = st.session_state.pending_email_action
        if pending_action:
            if st.button("Use this email", key="confirm_email_action"):
                try:
                    with st.spinner("Saving from the selected email..."):
                        result = save_selected_email(options[chosen], pending_action)
                    st.success(result)
                    st.session_state.messages.append({"role": "assistant", "content": result})
                    st.session_state.pending_email_matches = []
                    st.session_state.pending_email_action = None
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not save this email: {type(error).__name__}: {error}")
        else:
            col1, col2 = st.columns(2)
            if col1.button("Add to Reminders", key="view_email_add_reminder"):
                try:
                    result = save_selected_email(options[chosen], "reminder")
                    st.success(result)
                    st.session_state.messages.append({"role": "assistant", "content": result})
                    st.session_state.pending_email_matches = []
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not save reminder: {type(error).__name__}: {error}")
            if col2.button("Add to To-Do List", key="view_email_add_task"):
                try:
                    result = save_selected_email(options[chosen], "task")
                    st.success(result)
                    st.session_state.messages.append({"role": "assistant", "content": result})
                    st.session_state.pending_email_matches = []
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not save task: {type(error).__name__}: {error}")



# =============================================
# 9. REMINDERS
# =============================================


elif st.session_state.page == "Community Resources":
    st.title("📚 Community Resources")
    st.caption("Upload files directly OR import a public Google Drive file/folder link. Nexus stores the original resource and course details only — no OCR, text extraction or embeddings.")

    mode = st.radio("How do you want to add resources?", ["Upload files", "Import Google Drive link"], horizontal=True, key="community_add_mode")
    if mode == "Upload files":
        with st.form("community_direct_upload_form", clear_on_submit=True):
            uploaded_files = st.file_uploader(
                "Choose one or more files", accept_multiple_files=True,
                type=["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp", "txt", "md", "csv", "png", "jpg", "jpeg", "webp", "zip"]
            )
            course = st.text_input("Course *", placeholder="e.g. EE320")
            c1, c2 = st.columns(2)
            with c1: department = st.text_input("Department (optional)", placeholder="e.g. EE")
            with c2: resource_type = st.selectbox("Resource type (optional)", ["", "PYQ", "Midsem", "Endsem", "Quiz", "Assignment", "Notes", "Lecture", "Lab", "Course material", "Other"], format_func=lambda x: "Any / not sure" if not x else x)
            submitted = st.form_submit_button("Upload to Nexus", type="primary", use_container_width=True)
            if submitted:
                if not course.strip(): st.error("Course is required (e.g. EE320).")
                elif not uploaded_files: st.error("Choose at least one file.")
                else:
                    added = 0
                    for uploaded in uploaded_files:
                        try:
                            add_uploaded_file(uploaded, course, department, resource_type)
                            added += 1
                        except Exception as e:
                            st.error(f"{uploaded.name}: {type(e).__name__}: {e}")
                    if added: st.success(f"Saved {added} original file(s) under {course}. They are now available in course-resource searches and the library.")
                    st.rerun()
    else:
        with st.form("community_drive_import_form", clear_on_submit=True):
            drive_link = st.text_input("Public Google Drive file or folder link", placeholder="Paste the Anyone with the link → Viewer URL")
            course = st.text_input("Course *", placeholder="e.g. EE320")
            c1, c2 = st.columns(2)
            with c1: department = st.text_input("Department (optional)", placeholder="e.g. EE", key="drive_department")
            with c2: resource_type = st.selectbox("Resource type (optional)", ["", "PYQ", "Midsem", "Endsem", "Quiz", "Assignment", "Notes", "Lecture", "Lab", "Course material", "Other"], format_func=lambda x: "Any / not sure" if not x else x, key="drive_resource_type")
            submitted = st.form_submit_button("Import Drive link", type="primary", use_container_width=True)
            if submitted:
                if not course.strip(): st.error("Course is required (e.g. EE320).")
                elif not drive_link.strip(): st.error("Paste a Google Drive file or folder link.")
                else:
                    with st.spinner("Discovering public folder contents and saving links..."):
                        try:
                            result = add_drive_resource(drive_link, course, department, resource_type)
                            st.success(f"Added {result['added']} new catalogue entries ({result['discovered']} discovered) for {course}.")
                            if result['errors']:
                                st.warning("Some folders could not be listed. The root link was saved. Ensure nested folders/files are shared as Anyone with the link → Viewer.")
                        except Exception as e: st.error(f"Could not import link: {type(e).__name__}: {e}")

    st.divider()
    st.subheader("Resource library")
    rows = list_resources()
    if not rows: st.info("No resources added yet. Upload files or import a public Drive folder above.")
    else:
        choices = ["All courses"] + sorted(set(x['course'] for x in rows))
        chosen = st.selectbox("Show course", choices)
        shown = rows if chosen == "All courses" else [x for x in rows if x['course'] == chosen]
        st.caption(f"{len(shown)} resources · original files and Drive links are retained")
        for item in shown:
            with st.container(border=True):
                left, right = st.columns([5, 1])
                with left:
                    st.markdown(f"**{item['title']}**")
                    st.caption(f"{item['course']} · {item.get('department') or 'Department not specified'} · {item.get('resource_type') or 'Unclassified'} · {'Direct upload' if item.get('source_kind') == 'upload' else 'Google Drive'}")
                    local_path = get_file_path(item)
                    if local_path:
                        with open(local_path, "rb") as f:
                            st.download_button("⬇️ Download original file", f.read(), file_name=item.get('original_name') or item['title'], key=f"library_download_{item['id']}")
                    elif item.get('url', '').startswith('https://'):
                        st.markdown(f"[Open in Google Drive]({item['url']})")
                with right:
                    if st.button("Remove", key=f"community_remove_{item['id']}"):
                        delete_resource(item['id']); st.rerun()

elif st.session_state.page == "Reminders":

    st.title("🔔  Reminders")
    st.caption("Important academic actions and optional IITK campus events from your email.")

    def email_scan_panel():
        st.markdown("### 📩 IITK Email Sync")
        st.caption("Nexus checks for new emails every 2 hours while the app is running. Each scan processes up to 5 emails.")
        if st.button("↻ Scan Inbox Now", key="scan_inbox_now"):
            with st.spinner("Checking IITK emails and identifying important items..."):
                try:
                    result = scan_inbox(max_new_emails=5)
                    st.success(f"Checked {result['emails_checked']} email(s). Added {result['reminders_added']} new item(s).")
                except Exception as error:
                    st.error(f"Email scan failed: {type(error).__name__}: {error}")
        st.caption("Duplicate items are skipped. Email content is read-only; Nexus never sends, deletes or modifies emails.")

    if hasattr(st, "fragment"):
        @st.fragment(run_every=7200)
        def periodic_email_scan():
            try:
                result = scan_inbox(max_new_emails=5)
                if result["emails_checked"]:
                    st.caption(f"Last background check: {result['emails_checked']} new email(s), {result['reminders_added']} new item(s) added.")
                else:
                    st.caption("Email sync is active · no new emails since the last check.")
            except Exception as error:
                st.warning(f"Automatic email sync unavailable: {type(error).__name__}: {error}")
        periodic_email_scan()
    else:
        st.info("Automatic 2-hour sync requires a newer Streamlit version. You can still use Scan Inbox Now.")

    email_scan_panel()
    st.divider()

    st.subheader("📚 Academic reminders")
    st.caption("Actionable academic items: tests, quizzes, submissions, registrations and important deadline changes.")
    academic_items = list_extracted_reminders(include_completed=True, item_type="academic_reminder", hide_past=True)
    if academic_items:
        for item in academic_items:
            with st.container(border=True):
                left, right = st.columns([5, 1])
                with left:
                    st.markdown(f"**{item['title']}**  ·  `{item['category']}`")
                    if item.get("course"):
                        st.caption(f"Course: {item['course']}")
                    when = item.get("event_date") or "Date not specified — please review source email"
                    if item.get("event_time"):
                        when += f" · {item['event_time']}"
                    st.write(f"📅 {when}")
                    if item.get("details"):
                        st.write(item["details"])
                    st.caption(f"Source: {item.get('source_subject') or 'Email'} · {item.get('source_sender') or 'Unknown sender'} · Confidence: {item.get('confidence', 'medium')}")
                with right:
                    done = st.checkbox("Done", value=bool(item["completed"]), key=f"email_rem_done_{item['id']}")
                    if done != bool(item["completed"]):
                        set_completed(item["id"], done)
                        st.rerun()
                    if st.button("Delete", key=f"email_rem_delete_{item['id']}"):
                        delete_extracted(item["id"])
                        st.rerun()
    else:
        st.info("No academic reminders yet. Nexus will add actionable academic items when it finds them in your emails.")

    st.divider()
    st.subheader("🎪 Campus events & activities")
    st.caption("Optional events worth knowing about. These are kept separate from your academic deadlines.")
    campus_events = list_extracted_reminders(include_completed=True, item_type="campus_event")
    if campus_events:
        for item in campus_events:
            event_line = f"**{item['title']}**"
            if item.get("event_date"):
                event_line += f" — {item['event_date']}"
            if item.get("event_time"):
                event_line += f" · {item['event_time']}"
            st.markdown(f"- {event_line}")
            if item.get("details"):
                st.caption(item["details"])
            st.caption(f"Source: {item.get('source_subject') or 'Email'} · {item.get('source_sender') or 'Unknown sender'}")
    else:
        st.info("No campus events detected yet.")

    st.divider()
    st.subheader("＋ Your personal reminders")
    with st.form("reminder_form"):
        reminder = st.text_input("What do you need to remember?")
        date_value = st.date_input("Reminder date")
        time_value = st.time_input("Reminder time")
        submitted = st.form_submit_button("＋ Add Reminder")
        if submitted and reminder.strip():
            add_manual(reminder.strip(), date_value, time_value)
            st.success("Reminder saved!")

    manual = list_manual()
    if manual:
        for item in manual:
            left, right = st.columns([5, 1])
            with left:
                st.write(f"- **{item['title']}** — {item['event_date']} · {item['event_time']}")
            with right:
                if st.button("Delete", key=f"manual_rem_delete_{item['id']}"):
                    delete_manual(item["id"])
                    st.rerun()
    else:
        st.info("You don't have any personal reminders yet.")

# =============================================
# 10. TO-DO LIST
# =============================================

elif st.session_state.page == "To-Do List":

    st.title("✓  To-Do List")
    st.caption("Organise your work and stay productive.")

    with st.form("task_form"):
        task_title = st.text_input("What do you need to get done?")
        priority = st.selectbox("Priority", ["High", "Medium", "Low"])
        submitted = st.form_submit_button("＋ Add Task")
        if submitted and task_title.strip():
            add_task(task_title.strip(), priority)
            st.success("Task saved!")
            st.rerun()

    st.divider()
    st.subheader("Your Tasks")
    tasks = list_tasks()
    if tasks:
        for task_item in tasks:
            col1, col2 = st.columns([5, 1])
            with col1:
                done = st.checkbox(
                    f"{task_item['title']}  ·  {task_item['priority']} priority",
                    value=bool(task_item['done']),
                    key=f"task_{task_item['id']}"
                )
                if done != bool(task_item['done']):
                    set_task_done(task_item['id'], done)
                    st.rerun()
                if task_item.get("details"):
                    with st.expander("Task details / source"):
                        st.write(task_item["details"])
                        if task_item.get("source_subject"):
                            st.caption(f"Email: {task_item['source_subject']} · {task_item.get('source_sender') or ''} · {task_item.get('source_date') or ''}")
            with col2:
                if st.button("Delete", key=f"task_del_{task_item['id']}"):
                    delete_task(task_item['id'])
                    st.rerun()
    else:
        st.info("Your task list is empty. Add your first task!")


# =============================================
# 11. NOTES
# =============================================

elif st.session_state.page == "Notes":

    st.title("📝  Notes")
    st.caption("A space for your important thoughts and information.")

    with st.form("note_form"):

        title = st.text_input("Note title")

        content = st.text_area(
            "Write your note here...",
            height=150
        )

        submitted = st.form_submit_button("Save Note")

        if submitted and title.strip():

            st.session_state.notes.append({
                "title": title,
                "content": content
            })

            st.success("Note saved!")
            st.rerun()

    st.divider()
    st.subheader("Saved Notes")

    if st.session_state.notes:

        for i, note in enumerate(st.session_state.notes):

            with st.expander(note["title"]):

                st.write(note["content"])

                if st.button("Delete Note", key=f"note_{i}"):

                    st.session_state.notes.pop(i)
                    st.rerun()

    else:
        st.info("You haven't saved any notes yet.")
