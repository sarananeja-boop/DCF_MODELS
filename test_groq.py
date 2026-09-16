from groq import Groq
import os
from dotenv import load_dotenv
load_dotenv('backend/.env')
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
try:
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": "hello"}],
        model="groq/compound",
    )
    print(chat_completion.choices[0].message.content)
except Exception as e:
    print(e)
