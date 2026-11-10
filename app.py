
import os
import streamlit as st
from dotenv import load_dotenv
from google import genai

# =============================================
# 1. CONFIGURATION
# =============================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3-flash-preview"

st.set_page_config(
    page_title="BabyBot | IITK",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =============================================
# 2. BABYBOT IDENTITY
# =============================================

BABYBOT_SYSTEM_INSTRUCTION = """
You are BabyBot, an AI academic assistant built primarily
for students of the Indian Institute of Technology Kanpur (IITK).

IDENTITY:
- Your name is BabyBot.
- You are a friendly, reliable IITK academic companion.
- Never introduce yourself as Gemini or Google's AI unless
  explicitly asked which model powers you.
- Gemini is the technology powering you. BabyBot is the product.

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
- IITK portals, emails and academic databases are not
  connected yet. Never pretend that they are.
- If information is unavailable, say so honestly.
- Distinguish general guidance from verified IITK information.
- Never claim to have completed an action unless it was
  actually performed by the application.

INTRODUCTION:
When asked to introduce yourself, explain that you are
BabyBot, an AI academic assistant designed to make academic
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
    "chat_counter": 0
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


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
    <div class="brand-title">✦ BabyBot</div>
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

    # Display previous messages
    for message in st.session_state.messages:

        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    prompt = st.chat_input("Message BabyBot...")

    if prompt:

        # Save user message
        st.session_state.messages.append({
            "role": "user",
            "content": prompt
        })

        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate Gemini response
        with st.chat_message("assistant"):

            with st.spinner("BabyBot is thinking..."):

                try:

                    reply = get_gemini_reply(
                        st.session_state.messages
                    )

                    st.markdown(reply)

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": reply
                    })

                except Exception as error:

                    st.error(
                        "I couldn't reach my AI brain just now. "
                        "Please try again."
                    )

                    st.caption(
                        f"Technical detail: {type(error).__name__}: {error}"
                    )

        # Save recent conversation title
        if len(st.session_state.messages) <= 2:

            st.session_state.chat_counter += 1

            st.session_state.chats.append({
                "id": st.session_state.chat_counter,
                "title": prompt[:35]
            })


# =============================================
# 9. REMINDERS
# =============================================

elif st.session_state.page == "Reminders":

    st.title("🔔  Reminders")
    st.caption("Keep track of important dates and events.")

    with st.form("reminder_form"):

        reminder = st.text_input(
            "What do you need to remember?"
        )

        date = st.date_input("Reminder date")
        time = st.time_input("Reminder time")

        submitted = st.form_submit_button("＋ Add Reminder")

        if submitted and reminder.strip():

            st.session_state.reminders.append({
                "title": reminder,
                "date": date,
                "time": time
            })

            st.success("Reminder added successfully!")
            st.rerun()

    st.divider()
    st.subheader("Your Reminders")

    if st.session_state.reminders:

        for i, item in enumerate(st.session_state.reminders):

            col1, col2 = st.columns([5, 1])

            with col1:
                st.markdown(f"**🔔 {item['title']}**")
                st.caption(
                    f"{item['date']}  ·  {item['time']}"
                )

            with col2:

                if st.button("Delete", key=f"rem_{i}"):

                    st.session_state.reminders.pop(i)
                    st.rerun()

    else:
        st.info("You don't have any reminders yet.")


# =============================================
# 10. TO-DO LIST
# =============================================

elif st.session_state.page == "To-Do List":

    st.title("✓  To-Do List")
    st.caption("Organise your work and stay productive.")

    with st.form("task_form"):

        task = st.text_input(
            "What do you need to get done?"
        )

        priority = st.selectbox(
            "Priority",
            ["High", "Medium", "Low"]
        )

        submitted = st.form_submit_button("＋ Add Task")

        if submitted and task.strip():

            st.session_state.tasks.append({
                "title": task,
                "priority": priority,
                "done": False
            })

            st.rerun()

    st.divider()
    st.subheader("Your Tasks")

    if st.session_state.tasks:

        for i, task in enumerate(st.session_state.tasks):

            col1, col2 = st.columns([5, 1])

            with col1:

                done = st.checkbox(
                    f"{task['title']}  ·  {task['priority']} priority",
                    value=task["done"],
                    key=f"task_{i}"
                )

                st.session_state.tasks[i]["done"] = done

            with col2:

                if st.button("Delete", key=f"task_del_{i}"):

                    st.session_state.tasks.pop(i)
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
