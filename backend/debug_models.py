import os
import vertexai
from vertexai.generative_models import GenerativeModel

def test_models():
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    
    print(f"--- Vertex AI Access Debugger ---")
    print(f"Project: {project_id}")
    print(f"Location: {location}")
    print(f"Credentials: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
    
    if not project_id:
        print("ERROR: GOOGLE_CLOUD_PROJECT not set.")
        return

    try:
        vertexai.init(project=project_id, location=location)
        print("vertexai.init() successful.")
    except Exception as e:
        print(f"vertexai.init() FAILED: {e}")
        return

    # List of models to test
    candidates = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-001",
        "gemini-1.5-flash-002",
        "gemini-1.5-pro",
        "gemini-1.5-pro-001",
        "gemini-1.0-pro",
        "gemini-pro"
    ]

    print("\nTesting Model Availability (via generate_content call):")
    for model_name in candidates:
        print(f"[-] Checking {model_name}...", end=" ", flush=True)
        try:
            model = GenerativeModel(model_name)
            # We must make a call to trigger the 404/403
            response = model.generate_content("Hello", stream=False)
            print(f"✅ AVAILABLE (Response length: {len(response.text)})")
        except Exception as e:
            err_str = str(e)
            if "404" in err_str:
                print("❌ 404 NOT FOUND")
            elif "403" in err_str:
                print("⛔ 403 PERMISSION DENIED")
            else:
                print(f"⚠️ ERROR: {err_str[:100]}...")

if __name__ == "__main__":
    test_models()
