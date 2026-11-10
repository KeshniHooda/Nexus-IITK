# ✦ Nexus — Your Personal IITK Companion

### Your campus. Your knowledge. One connection.

**Nexus** is an AI-powered campus companion designed to make academic information, student resources, communication and everyday campus tasks easier to access — all through one unified interface.

Built with the vision of creating a smarter, more connected IIT Kanpur ecosystem, Nexus brings together an intelligent AI assistant, an institutional knowledge base, multilingual voice interaction, IITK webmail assistance, academic reminders and a community-driven resource library.

Instead of navigating multiple websites, searching through scattered PDFs, digging through email threads or repeatedly asking around for course material, students can simply ask Nexus.

**One assistant. One platform. A more connected campus.**

---

##  Why Nexus?

Campus information is often fragmented.

Academic regulations live on institutional websites. Course resources are scattered across student drives and groups. Important announcements arrive through email. Deadlines and opportunities are easy to miss. Useful information is frequently buried under multiple layers of navigation.

Students spend valuable time finding information instead of using it.

Nexus addresses this problem by bringing several essential parts of student life together into a single AI-powered platform.

### What Nexus brings to the table

- **AI Academic Assistant:** Ask questions about IITK academics, academic procedures, campus information and student life.
- **Institutional RAG Knowledge Base:** Retrieve relevant information from indexed IITK sources and generate contextual answers.
- **Multilingual Voice Assistant:** Interact using speech, with separate input and response language selection.
- **IITK Webmail Assistant:** Access and understand important information from your institutional email.
- **Smart Reminders:** Identify actionable academic information and help students keep track of important events and deadlines.
- **Community Resources:** Discover course material, notes, assignments, quizzes and previous-year question papers shared by students.

---

# 🧠 1. AI Assistant — The Brain Behind Nexus

The AI Assistant is the central interface of Nexus.

It is designed to understand natural-language questions and help students navigate academic and campus-related information without having to manually search through multiple sources.

Students can ask questions in a conversational manner, rather than needing to know the exact website, document or department responsible for the information.

Examples of what students can ask:

- Questions about academic procedures and institutional policies.
- Information about courses, examinations and academic regulations.
- Questions about campus facilities and student-related information.
- Help locating relevant institutional resources.
- General academic questions and explanations.
- Questions that require combining information from multiple retrieved sources.

Nexus uses Google's Gemini API for natural-language understanding and response generation.

## How the RAG pipeline works

A major part of Nexus is its Retrieval-Augmented Generation (RAG) architecture.

Rather than relying entirely on the language model's pre-existing knowledge, Nexus can retrieve relevant information from its own indexed IITK knowledge base before generating an answer.

This helps make institution-specific responses more relevant and grounded in available source material.

### Step 1 — Information gathering

The institutional knowledge base is populated using relevant publicly accessible IIT Kanpur information sources.

The initial collection includes information from official IITK academic and student-affairs sources, particularly:

- Dean of Academic Affairs (DoAA).
- Dean of Students' Affairs (DoSA).
- Relevant institutional webpages and associated academic information.

The objective is to bring scattered institutional information into a structured, searchable knowledge repository.

### Step 2 — Content extraction and preprocessing

The collected information is processed into text suitable for retrieval.

The content is cleaned and divided into smaller, meaningful text segments called **chunks**.

Chunking allows the system to retrieve specific pieces of information instead of passing entire documents or webpages to the language model.

### Step 3 — Embedding generation

Each text chunk is converted into a numerical vector representation using:

`sentence-transformers/all-MiniLM-L6-v2`

These embeddings capture semantic information about the text, allowing Nexus to retrieve information based on meaning rather than relying exclusively on exact keyword matches.

For example, a student asking about dropping a course may retrieve relevant academic regulations even if the source uses different terminology.

### Step 4 — Vector database and indexing

The generated embeddings are stored in **ChromaDB**, which serves as the vector database.

This creates a searchable institutional knowledge repository.

The initial curated collection contains approximately 470 indexed text chunks from DoAA and DoSA sources.

### Step 5 — Semantic retrieval

When a student submits a question:

1. Nexus processes the query.
2. The query is converted into a representation suitable for semantic retrieval.
3. Relevant chunks are retrieved from ChromaDB.
4. The retrieved institutional context is passed to Gemini.

The retrieval process helps identify information relevant to the student's actual question.

### Step 6 — Context-aware answer generation

Gemini uses the student's question and the retrieved context to formulate a natural-language response.

The result is a conversational assistant that combines the language capabilities of a large language model with a searchable IITK-specific knowledge base.

### RAG pipeline at a glance

```text
Official IITK Information Sources
              |
              v
       Content Extraction
              |
              v
      Cleaning and Chunking
              |
              v
       Embedding Generation
              |
              v
           ChromaDB
              |
              |
Student Question
       |
       v
 Query Processing
       |
       v
 Semantic Retrieval
       |
       v
 Relevant Knowledge Chunks
       |
       v
 Gemini + Retrieved Context
       |
       v
 Contextual Answer
```

**An important distinction:** Nexus does not fine-tune or retrain Gemini on IITK documents. It uses RAG to retrieve relevant information at query time. The institutional knowledge base can be expanded and re-indexed independently of the underlying language model.

---

# 🎙️ 2. Multilingual Voice Assistant

Nexus is designed to make AI interaction more accessible and natural.

Typing should not be the only way to interact with an assistant. Students should be able to ask questions in their preferred language and receive responses in a language they are comfortable with.

Nexus integrates Gnani AI's speech technologies to enable voice-based interaction.

### Speech-to-text — Gnani Prisma

Gnani Prisma is used to convert spoken input into text.

The transcribed question can then be processed by the existing Nexus AI pipeline.

### Language understanding — Gemini

Gemini processes the transcribed question, understands the user's intent and generates the response.

The voice workflow supports independent selection of input and response languages, allowing students to speak in one language and receive an answer in another.

### Text-to-speech — Gnani Timbre

Gnani Timbre converts the generated text response into speech.

This allows Nexus to communicate its answers through voice instead of limiting interactions to text.

### Voice pipeline

```text
User Speaks
     |
     v
Gnani Prisma
(Speech-to-Text)
     |
     v
Nexus AI Pipeline
     |
     v
Gemini
(Understanding + Response)
     |
     v
Gnani Timbre
(Text-to-Speech)
     |
     v
Spoken Response
```

The separation of speech recognition, language processing and speech synthesis makes the voice experience modular and easier to extend.

---

# 📧 3. IITK Webmail Integration

Important academic information often arrives through institutional email.

Course announcements, examination updates, administrative instructions, event notifications and deadlines can easily get buried in long email threads.

Nexus integrates with IITK webmail to make this information easier to access and understand.

### What it does

The webmail assistant helps users:

- Access their institutional inbox through the integrated email workflow.
- Search for relevant emails.
- Identify important academic announcements.
- Understand lengthy email content through AI-assisted summaries.
- Extract useful information from relevant messages.

Instead of manually scanning multiple email threads, students can use a conversational interface to find and understand information.

### Why this matters

An email is only useful if its information reaches the student at the right time.

Nexus reduces the effort required to locate important messages and understand what action, if any, is required.

**Privacy and safety:** The current integration is intended for read-only email access. Nexus does not send, delete or modify emails through this workflow.

---

# 🔔 4. Smart Reminders — Never Miss What Matters

Finding an announcement is only half the problem.

Students also need to remember what they are supposed to do after reading it.

An important email may contain a registration deadline, an assignment submission date, an examination announcement or an event notification.

Nexus includes a dedicated Reminders section to help turn relevant information into actionable items.

### How it helps

- Brings attention to important academic actions.
- Helps surface relevant information from email.
- Highlights dates and time-sensitive items.
- Makes it easier to keep track of academic responsibilities.
- Can surface optional IITK campus events.

The idea is simple:

**Don't just read important information. Act on it.**

By connecting email understanding with reminders, Nexus aims to bridge the gap between receiving information and acting upon it.

---

# 📚 5. Community Resources — Knowledge Shared by Students

Institutional websites cannot contain everything students need.

Some of the most useful academic material is created and shared by students themselves:

- Previous-year question papers.
- Mid-semester and end-semester papers.
- Lecture notes.
- Assignments and solutions.
- Quizzes and practice material.
- Course-specific study resources.

However, these resources are frequently scattered across personal Google Drives, student groups and individual folders.

Nexus introduces a community-driven resource catalogue to make this material easier to discover.

### How it works

Students can contribute resources through the Community Resources section.

Two contribution methods are supported:

**1. Direct file upload**

Students can upload academic material directly through the application.

The uploaded resource is stored locally by the application and associated with its course and resource metadata.

**2. Google Drive links**

Students can submit publicly accessible Google Drive file or folder links.

The catalogue can enumerate accessible folder contents where supported and retain the corresponding resource links.

### Structured resource discovery

Resources can be organised using metadata such as:

- Course code or course name.
- Department.
- Resource type.

This makes searching more structured and useful.

For example, a student looking for previous-year papers can search by course and resource type rather than manually navigating multiple folders.

### Why it matters

The Community Resources feature is built around a simple belief:

**Students should not have to rediscover material that another student has already found.**

By making student-contributed academic resources discoverable through one interface, Nexus encourages knowledge sharing and creates the foundation for a more collaborative academic ecosystem.

Community Resources is a separate catalogue from the institutional RAG knowledge base. Its current workflow focuses on organising and discovering uploaded files and shared links; it does not automatically embed every community resource into the institutional vector database.

---

# 📝 6. Personal Productivity

Alongside the AI Assistant, Nexus provides dedicated productivity sections to help students organise their academic lives.

### To-Do List

A space to organise tasks, keep track of pending work and manage everyday responsibilities.

### Notes

A dedicated space for storing useful information and personal notes.

### Reminders

A place to review important academic actions and relevant campus events surfaced through the email workflow.

Together, these features make Nexus more than a question-answering chatbot. It is designed as a unified student productivity companion.

---

# 🛠️ Technology Stack

Nexus brings together technologies from AI, information retrieval, speech processing and application development.

| Technology | Role |
|---|---|
| Python | Core application logic |
| Streamlit | Interactive web application |
| Google Gemini API | Natural-language understanding and response generation |
| Sentence Transformers | Semantic embedding generation |
| all-MiniLM-L6-v2 | Text embedding model |
| ChromaDB | Vector database and semantic retrieval |
| Gnani Prisma | Speech-to-text |
| Gnani Timbre | Text-to-speech |
| Python dotenv | Environment variable and secret configuration |
| IMAP / Email integration | Institutional email access |
| Google Drive links | Community resource discovery |

---

# 🏗️ Architecture Overview

Nexus is built as a modular application, with different components handling different responsibilities.

```text
                     NEXUS
                       |
          +------------+------------+
          |            |            |
          v            v            v
      AI Assistant  Productivity  Community
          |          Tools        Resources
          |
     +----+------------------+
     |                       |
     v                       v
  Gemini API             RAG Pipeline
                             |
                       Sentence Transformers
                             |
                          ChromaDB

     Webmail Integration
             |
       Email Processing
             |
        Reminders

     Voice Interface
             |
       Gnani Prisma
             |
          Gemini
             |
       Gnani Timbre
```

---

# 🚀 Getting Started

Want to explore Nexus or run your own local instance?

Follow the instructions below.

## 1. Prerequisites

Make sure you have:

- Python 3.10 or a compatible version.
- Git.
- A Google Gemini API key.
- A Gnani AI API key if you want to use voice features.
- Institutional email credentials if you want to enable the webmail integration.

## 2. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

Navigate into the project directory:

```bash
cd Nexus
```

Replace `Nexus` with the actual repository folder name if different.

## 3. Create a virtual environment

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4. Install dependencies

```bash
pip install -r requirements.txt
```

## 5. Configure environment variables

Create a `.env` file in the root directory.

Add your credentials:

```env
GEMINI_API_KEY=your_gemini_api_key
GNANI_API_KEY=your_gnani_api_key

IITK_EMAIL=your_institutional_email
IITK_EMAIL_PASSWORD=your_email_password
```

Only configure the credentials required for the features you intend to use.

**Never upload your `.env` file to GitHub.**

## 6. Prepare the institutional knowledge base

The RAG pipeline requires its vector database to be available.

If the repository does not contain a prebuilt ChromaDB index, follow the project's ingestion scripts and documentation to:

1. Gather the relevant institutional source material.
2. Extract and preprocess the text.
3. Generate embeddings.
4. Index the resulting chunks in ChromaDB.
5. Configure the application to use the generated collection.

The local knowledge base and source files may need to be prepared separately depending on the repository contents.

## 7. Launch Nexus

Run:

```bash
python -m streamlit run app_backup_integrated.py
```

Open the local URL displayed in the terminal, usually:

```text
http://localhost:8501
```

You're ready to explore Nexus!

---

# 🔐 Security and Privacy

Nexus uses API keys and account credentials to connect to external services.

Please follow these precautions:

- Keep `.env` private.
- Never commit API keys, passwords or access tokens.
- Do not share institutional email credentials.
- Use your own API credentials when running the application.
- Keep local user data and generated databases out of public repositories unless intentionally designed for distribution.
- Be mindful of the privacy of email content and uploaded community resources.

---

# 🗺️ Future Scope

Nexus is envisioned as an evolving campus-wide platform.

Potential directions for further development include:

- Expanding institutional knowledge coverage across departments and administrative offices.
- Improving retrieval quality and source-grounded responses.
- Adding more campus services and institutional integrations.
- Enabling broader student collaboration through community resources.
- Improving multilingual and voice interaction.
- Introducing more intelligent academic planning and deadline tracking.
- Making the platform accessible to a wider student community.

The long-term vision is to make campus information more accessible, connected and actionable.

---

# 💡 The Vision

Nexus is built around one simple idea:

**A student should spend less time searching for information and more time learning, creating and participating.**

From understanding an academic regulation to finding a previous-year paper, from locating an important email to remembering a deadline, Nexus aims to bring the everyday student experience into one intelligent interface.

It combines institutional knowledge, community contributions, AI assistance and productivity tools to create a more connected campus ecosystem.

**Nexus — Your campus. Your knowledge. One connection.**

---

## 👩‍💻 Built With

Made with the vision of creating a smarter and more connected IIT Kanpur student ecosystem.

If you find the project interesting, feel free to explore the repository, experiment with the architecture and build upon it.

**Let's make campus knowledge accessible to everyone.**