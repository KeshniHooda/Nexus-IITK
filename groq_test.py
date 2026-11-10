
import os
from dotenv import load_dotenv
from groq import Groq

# Load API keys from .env
load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise ValueError("GROQ_API_KEY not found in .env")

client = Groq(api_key=api_key)

print("Searching the web...")

response = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[
        {
            "role": "user",
            "content": (
                "Search the web for the latest important announcements "
                "on the official IIT Kanpur website. Give me a short "
                "summary and include source URLs."
            )
        }
    ],
    tools=[{"type": "browser_search"}],
    tool_choice="required",
    max_completion_tokens=2048
)

print("\nBABYBOT WEB SEARCH TEST")
print(response.choices[0].message.content)
