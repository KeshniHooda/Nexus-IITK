BABYBOT COMMUNITY RESOURCE LIBRARY — INSTALL

WHAT THIS ADDS
- A separate Community Resources page.
- Form fields: Google Drive link + required course; department and resource type optional.
- Public Google Drive file/folder links only.
- Best-effort recursive folder listing via Drive's public embedded folder view.
- Stores folder/file names, links and parent paths in SQLite.
- No file downloads, text extraction, OCR, embeddings or changes to the official RAG index.
- Chat resource searches return all matching entries; if category is unclear or labels are weak, they fall back to all resources for that course.

INSTALL
1. Stop Streamlit with Ctrl+C.
2. Back up your current app_backup_integrated.py and rag_engine.py.
3. Copy these three files from this package into the MAIN project folder (same folder as webmail.py):
   app_backup_integrated.py
   rag_engine.py
   community_resources.py
4. Keep webmail.py, email_monitor.py, reminder_store.py, .env and the rag/ folder unchanged.
5. Install dependencies if missing:
   python -m pip install beautifulsoup4 requests
6. Run:
   python -m streamlit run app_backup_integrated.py

DATABASE
- babybot_resources.db is created automatically beside app_backup_integrated.py.
- It stores catalogue metadata and Drive URLs only, not the original files.
- Removing an item in the library removes only its catalogue record, never the Drive file.

GOOGLE DRIVE
- Set the root folder to Anyone with the link → Viewer.
- Nested folders/files must also be accessible to anyone with the link.
- This uses the public embedded folder HTML, not Google's authenticated Drive API. Google may block/change this listing. If listing fails, the root folder link is still saved and the app reports the failure. Test with your actual folder before depending on recursive discovery.
- No Google credentials or OAuth are requested.

TEST EXAMPLE
Create this folder structure in Drive (or unzip the accompanying BabyBot_EE320_Resource_Test_Folder.zip and upload its folder):
BabyBot Test - EE320/
  PYQs/
    Midsem/
      EE320_Midsem_2023.pdf
      EE320_Midsem_2024.pdf
    Endsem/
      EE320_Endsem_2023.pdf
      EE320_Endsem_2024.pdf
  Quizzes/
    EE320_Quiz_1_2024.pdf
    EE320_Quiz_2_2025.pdf
  Lectures/
    Lecture_01.pdf
    Lecture_02.pdf
  Assignments/
    Assignment_1.pdf

Set the root folder to Anyone with the link → Viewer. Confirm nested content is also viewable. Copy the ROOT folder URL.
In BabyBot → Community Resources enter:
  Google Drive link: [root folder link]
  Course: EE320
  Department: EE
  Resource type: leave blank
Click Add to BabyBot.

TEST THESE QUERIES IN THE CHAT
1. "EE320 ke saare resources dikha do" — all categories.
2. "EE320 ke PYQs do" — every PYQ item; if folder names do not clearly identify PYQs, it falls back to all EE320 resources.
3. "EE320 midsem papers from all years" — every matching midsem item.
4. "EE320 ka material bhejo" — all resource types.
5. "EE320 ke quizzes" — all matching quizzes; if labels are weak, all EE320 resources.

IMPORTANT
This feature catalogues file/folder names and links only. It cannot know the contents of a PDF or prove that a badly named file is a quiz. In ambiguous cases it deliberately returns all course resources rather than hiding potentially useful files.
