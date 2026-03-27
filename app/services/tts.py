import os
import time
from dotenv import load_dotenv
from deepgram import DeepgramClient, SpeakOptions

load_dotenv()

def text_to_speech(text: str, filename: str) -> str:
    deepgram = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
    print(f"Generating TTS for: {text[:50]}...")
    start = time.time()
    options = SpeakOptions(
        model="aura-asteria-en",
        encoding="linear16",
        sample_rate=8000
    )
    deepgram.speak.v("1").save(filename, {"text": text}, options)
    end = time.time()
    print(f"Deepgram TTS took: {round(end - start, 2)} seconds")
    return filename

def cleanup_file(filename: str):
    time.sleep(30)
    if os.path.exists(filename):
        os.remove(filename)
        print(f"Cleaned up: {filename}")
