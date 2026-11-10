
from dotenv import load_dotenv
from google import genai
import os

print("1. Loading environment...")
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("Gemini API key not found!")

print("2. API key found!")
print("3. Creating Gemini client...")

client = genai.Client(api_key=api_key)

print("4. Sending request to Gemini...")

try:
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents="Say hello to me as BabyBot in one sentence."
    )

    print("5. Response received!")
    print("\nBabyBot says:")
    print(response.text)

except Exception as e:
    print("\nAPI ERROR:")
    print(type(e).__name__, e)
