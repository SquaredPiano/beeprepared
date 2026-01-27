import os
import boto3
from google import genai
from supabase import create_client, Client
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

load_dotenv()

def test_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    print(f"Checking Supabase: {url}")
    if not url or not key:
        print("[FAIL] Supabase credentials missing")
        return False
    try:
        supabase: Client = create_client(url, key)
        res = supabase.table("lectures").select("*").limit(1).execute()
        print("[OK] Supabase connection successful")
        return True
    except Exception as e:
        print(f"[FAIL] Supabase connection failed: {e}")
        return False

def test_r2():
    endpoint = os.getenv("R2_ENDPOINT_URL")
    key_id = os.getenv("R2_ACCESS_KEY_ID")
    secret = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET_NAME")
    if not all([endpoint, key_id, secret, bucket]):
        print("[FAIL] R2 credentials missing")
        return False
    try:
        s3 = boto3.client(service_name='s3', endpoint_url=endpoint, aws_access_key_id=key_id, aws_secret_access_key=secret)
        s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
        print("[OK] R2 connection successful")
        return True
    except Exception as e:
        print(f"[FAIL] R2 connection failed: {e}")
        return False

def test_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[FAIL] Gemini API key missing")
        return False
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model='gemini-2.0-flash', contents='Ping')
        if response.text:
            print(f"[OK] Gemini connection successful")
            return True
    except Exception as e:
        print(f"[FAIL] Gemini connection failed: {e}")
        return False

def test_azure():
    key = os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("AZURE_SPEECH_REGION")
    if not key or not region:
        print("[FAIL] Azure Speech credentials missing")
        return False
    try:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        print("[OK] Azure Speech config validated")
        return True
    except Exception as e:
        print(f"[FAIL] Azure Speech config failed: {e}")
        return False

if __name__ == "__main__":
    print("--- START API KEY TEST ---")
    test_supabase()
    test_r2()
    test_gemini()
    test_azure()
    print("--- END API KEY TEST ---")
