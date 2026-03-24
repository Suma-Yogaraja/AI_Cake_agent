import os
import uuid
import requests
from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client as TwilioClient
from openai import OpenAI
from deepgram import DeepgramClient, SpeakOptions, PrerecordedOptions
from dotenv import load_dotenv
import psycopg2
import random
import string
import time
import threading

load_dotenv()

app = FastAPI()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
deepgram = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))

conversation_store = {}

SYSTEM_PROMPT = """
You are the friendly front desk assistant for Butter and Batter Bakery.
Keep responses short — this is a phone call, not an essay.
You can help with:
- Our menu: chocolate cake, vanilla cake, red velvet, strawberry cake. All available in 6 inch, 8 inch, 10 inch.
- Business hours: Monday to Saturday, 9am to 6pm.
- Taking orders: collect in this order:
    1. Customer name
    2. Cake flavour
    3. Cake size
    4. Message on cake
    5. Phone number for confirmation
- Once you have all details, confirm the order back to the customer and say a warm goodbye.
- After your goodbye message, add exactly this word on a new line: ORDER_COMPLETE

If you don't know something, say you'll pass the message to the team.
"""

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


def search_knowledge_base(query: str, limit: int = 3) -> str:
    print(f"Searching knowledge base for: {query[:100]}")
    
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    )
    query_embedding = response.data[0].embedding
    print(f"Got embedding, length: {len(query_embedding)}")
    
    conn = get_db()
    cur = conn.cursor()
    # Convert embedding list to PostgreSQL vector format
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

    cur.execute("""
    SELECT content, category
    FROM knowledge_base
    ORDER BY embedding <-> %s::vector
    LIMIT %s
""", (embedding_str, limit)) 
    
    results = cur.fetchall()
    print(f"Results count: {len(results)}")
    cur.close()
    conn.close()
    
    if not results:
        return ""
    
    context = "\n".join([f"[{row[1].upper()}] {row[0]}" for row in results])
    print(f"Context: {context[:200]}")
    return context

def detect_emotion(ai_reply: str, history: list) -> str:
    # Always celebratory at order complete
    if "ORDER_COMPLETE" in ai_reply:
        return "celebratory"
    
    # Always greeting at start
    if len(history) <= 2:
        return "greeting"
    
    # Ask GPT-4o to classify the emotion
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
    
    # Fallback if GPT returns something unexpected
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


def generate_order_id():
    numbers = ''.join(random.choices(string.digits, k=4))
    return f"SW-{numbers}"

def extract_order_details(history):
    messages = [
        {"role": "system", "content": """
        Extract the order details from this conversation and return them in this exact format:
        NAME: <customer name>
        FLAVOUR: <cake flavour>
        SIZE: <cake size>
        MESSAGE: <message on cake or 'none'>
        PHONE: <customer phone number>
        Only return these 5 lines, nothing else.
        """}
    ] + history

    result = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    return result.choices[0].message.content

def save_order(order_id, details):
    lines = details.strip().split("\n")
    data = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (order_id, customer_name, cake_flavour, cake_size, cake_message, customer_phone)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        order_id,
        data.get("NAME", "unknown"),
        data.get("FLAVOUR", "unknown"),
        data.get("SIZE", "unknown"),
        data.get("MESSAGE", "none"),
        data.get("PHONE", "unknown")
    ))
    conn.commit()
    cur.close()
    conn.close()

def transcribe_with_deepgram(recording_url: str) -> str:
    audio_url = recording_url + ".wav"
    print(f"Downloading audio from: {audio_url}")

    # Download with Twilio credentials
    start = time.time()
    audio_response = requests.get(
        audio_url,
        auth=(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    )
    audio_content = audio_response.content
    print(f"Download took: {round(time.time() - start, 2)} seconds")

    # Send to Deepgram as buffer
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

def text_to_speech(text: str, filename: str) -> str:
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
    import time
    time.sleep(30)
    if os.path.exists(filename):
        os.remove(filename)
        print(f"Cleaned up: {filename}")

@app.post("/voice", response_class=Response)
async def voice(request: Request):
    form = await request.form()
    print(f"BASE_URL is: {os.getenv('BASE_URL')}")
    call_sid = form.get("CallSid", "unknown")
    conversation_store[call_sid] = []

    greeting = "Hello! Welcome to Butter and Batter Bakery. How can I help you today?"
    filename = f"audio_{uuid.uuid4()}.wav"
    text_to_speech(greeting, filename)
    threading.Thread(target=cleanup_file, args=(filename,)).start()

    base_url = os.getenv("BASE_URL")
    response = VoiceResponse()
    response.play(f"{base_url}/{filename}")
    response.record(
        action="/process",
        method="POST",
        max_length=10,
        play_beep=False,
        timeout=3
    )
    return Response(str(response), media_type="application/xml")

@app.post("/process", response_class=Response)
async def process(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    recording_url = form.get("RecordingUrl", "")

    response = VoiceResponse()
    history = conversation_store.get(call_sid, [])

    if not recording_url:
        response.say("Sorry, I didn't catch that.")
        response.record(
            action="/process",
            method="POST",
            max_length=10,
            play_beep=False,
            timeout=3
        )
        return Response(str(response), media_type="application/xml")

    # Transcribe with Deepgram
    transcript = transcribe_with_deepgram(recording_url)

    if not transcript.strip():
        response.say("Sorry, I didn't catch that. Could you repeat?")
        response.record(
            action="/process",
            method="POST",
            max_length=10,
            play_beep=False,
            timeout=3
        )
        return Response(str(response), media_type="application/xml")

    print(f"User said: {transcript}")
    history.append({"role": "user", "content": transcript})

    # GPT-4o
    # Build a context-aware search query
    recent_history = history[-4:] if len(history) > 4 else history
    conversation_context = " ".join([m["content"] for m in recent_history])
    search_query = f"{conversation_context} {transcript}"
    context = search_knowledge_base(search_query,limit=8)
    print(f"context found:{context}")

    # Build enhanced system prompt with knowledge
    enhanced_prompt = SYSTEM_PROMPT
    if context:
        enhanced_prompt += f"""

        IMPORTANT — KNOWLEDGE BASE RESULTS:
        {context}

        STRICT RULES:
        - You MUST answer using the knowledge base results above
        - NEVER say "I don't know" or "I'll pass to the team" if the answer is in the knowledge base
        - If the customer asks about price, location, hours, delivery — the answer IS in the knowledge base above
        - Only say you'll pass to the team if the topic is completely absent from the knowledge base
        """
        print(f"Enhanced prompt context section: {context[:200]}")
    else:
        print("No context added to prompt")
    start = time.time()
    completion = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": enhanced_prompt}] + history
    )
    end = time.time()

    ai_reply = completion.choices[0].message.content
    print(f"GPT-4o took: {round(end - start, 2)} seconds")
    print(f"AI replied: {ai_reply}")

    history.append({"role": "assistant", "content": ai_reply})
    conversation_store[call_sid] = history

    base_url = os.getenv("BASE_URL")

    if "ORDER_COMPLETE" in ai_reply:
        clean_reply = ai_reply.replace("ORDER_COMPLETE", "").strip()
        order_id = generate_order_id()
        details = extract_order_details(history)
        save_order(order_id, details)
        print(f"Order saved: {order_id}")

        final_message = clean_reply + f" Your order ID is {order_id}. Goodbye!"
        final_message = clean_reply + f" Your order ID is {order_id}. Goodbye!"
        emotion = detect_emotion(ai_reply, history)
        emotional_text = apply_emotion(final_message, "celebratory")
        filename = f"audio_{uuid.uuid4()}.wav"
        text_to_speech(emotional_text, filename)
        threading.Thread(target=cleanup_file, args=(filename,)).start()

        response.play(f"{base_url}/{filename}")
        response.hangup()
    else:
        emotion = detect_emotion(ai_reply, history)
        print(f"Emotion detected: {emotion}")
        emotional_text = apply_emotion(ai_reply, emotion)
        filename = f"audio_{uuid.uuid4()}.wav"
        text_to_speech(emotional_text, filename)    
        
        threading.Thread(target=cleanup_file, args=(filename,)).start()

        response.play(f"{base_url}/{filename}")
        response.record(
            action="/process",
            method="POST",
            max_length=10,
            play_beep=False,
            timeout=3
        )

    return Response(str(response), media_type="application/xml")

app.mount("/", StaticFiles(directory="."), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
