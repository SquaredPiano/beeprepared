
import os
from deepgram import DeepgramClient
from dotenv import load_dotenv

load_dotenv("backend/.env")
try:
    key = os.getenv("DEEPGRAM_API_KEY") or os.getenv("DEEPGRAM_KEY")
    dg = DeepgramClient(api_key=key)
    print("DG Client Created")
    print(f"Listen type: {type(dg.listen)}")
    print(f"Listen dir: {dir(dg.listen)}")
    
    print(f"Listen v1: {dg.listen.v1}")
    print(f"DG Client dir: {dir(dg)}")
except Exception as e:
    print(f"Error: {e}")
