import os
import time
import requests
from dotenv import load_dotenv
from deepgram import DeepgramClient, PrerecordedOptions

load_dotenv()

deepgram = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))

def transcribe_with_deepgram(recording_url: str) -> str:
    audio_url = recording_url + ".wav"
    print(f"Downloading audio from: {audio_url}")
    start = time.time()
    audio_response = requests.get(
        audio_url,
        auth=(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    )
    audio_content = audio_response.content
    print(f"Download took: {round(time.time() - start, 2)} seconds")
    print("Transcribing with Deepgram...")
    start = time.time()
    options = PrerecordedOptions(
        model="nova-2",
        language="en-IN",
        smart_format=True,
        punctuate=True,
        numerals=True,
        filler_words=False,
        keywords=["strawberry:2", "chocolate:2", "vanilla:2", "red velvet:2", "cake:2", "inch:2"]
    )
    response = deepgram.listen.prerecorded.v("1").transcribe_file(
        {"buffer": audio_content, "mimetype": "audio/mulaw"},
        options
    )
    end = time.time()
    transcript = response.results.channels[0].alternatives[0].transcript
    print(f"Deepgram took: {round(end - start, 2)} seconds")
    print(f"Deepgram heard: {transcript}")
    return transcript
