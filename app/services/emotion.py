def apply_emotion(text: str, emotion: str) -> str:
    # Deepgram Aura TTS does not support SSML prosody tags — return plain text.
    return text
