import os
from openai import OpenAI

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def detect_emotion(ai_reply: str, history: list) -> str:
    if "ORDER_COMPLETE" in ai_reply:
        return "celebratory"
    if len(history) <= 2:
        return "greeting"
    result = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": """
            You are classifying the emotion of a bakery assistant's response.
            Be generous with positive emotions — this is a friendly bakery.
        Rules:
        - If the response mentions a specific cake, flavour or size → excited
        - If the response reads back order details → confirming  
        - If the response contains sorry or apologize → empathetic
        - If the response asks a question to collect order info → neutral
        - If the response says goodbye or thank you for ordering → celebratory
        Reply with only one word: excited, confirming, empathetic, neutral, or celebratory
        """},
            {"role": "user", "content": ai_reply}
        ],
        max_tokens=5
    )
    emotion = result.choices[0].message.content.strip().lower()
    print(f"GPT emotion classification: {emotion}")
    if emotion not in ["excited", "confirming", "empathetic", "neutral", "celebratory", "greeting"]:
        return "neutral"
    return emotion

def apply_emotion(text: str, emotion: str) -> str:
    if emotion == "celebratory":
        return f"<speak><prosody rate='fast' pitch='high'>{text}</prosody></speak>"
    elif emotion == "excited":
        return f"<speak><prosody rate='medium' pitch='high'>{text}</prosody></speak>"
    elif emotion == "confirming":
        return f"<speak><prosody rate='slow' pitch='low'>{text}</prosody></speak>"
    elif emotion == "greeting":
        return f"<speak><prosody rate='medium' pitch='medium'>{text}</prosody></speak>"
    elif emotion == "empathetic":
        return f"<speak><prosody rate='slow' pitch='low'>{text}</prosody></speak>"
    else:
        return text
