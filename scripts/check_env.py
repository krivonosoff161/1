import os

from dotenv import load_dotenv

load_dotenv()
key = os.getenv("OKX_API_KEY")
print(f'API_KEY: {key[:20] if key else "NOT FOUND"}...')
