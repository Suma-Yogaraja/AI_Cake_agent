import os
import time
from dotenv import load_dotenv
from deepgram import DeepgramClient, SpeakOptions

load_dotenv()

def text_to_speech(text: str, filename: str) -> str:
    """TTS to WAV file — used only for the initial greeting served via Twilio <Play>."""
    deepgram = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
    start = time.time()
    options = SpeakOptions(
        model="aura-asteria-en",
        encoding="linear16",
        sample_rate=8000
    )
    deepgram.speak.v("1").save(filename, {"text": text}, options)
    print(f"Deepgram TTS took: {round(time.time() - start, 2)} seconds")
    return filename

def text_to_speech_mulaw_bytes(text: str) -> bytes:
    """TTS to raw mulaw 8kHz bytes for sending back over the Twilio media stream WebSocket."""
    deepgram = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
    start = time.time()
    options = SpeakOptions(
        model="aura-asteria-en",
        encoding="mulaw",
        sample_rate=8000
    )
    response = deepgram.speak.v("1").stream({"text": text}, options)
    audio = response.stream.read()
    # Strip RIFF/WAV container header if Deepgram returns one
    if audio[:4] == b'RIFF':
        idx = audio.find(b'data', 12)
        if idx != -1:
            audio = audio[idx + 8:]
    print(f"Deepgram TTS (mulaw) took: {round(time.time() - start, 2)} seconds")
    return audio

def cleanup_file(filename: str):
    time.sleep(60)
    if os.path.exists(filename):
        os.remove(filename)
