import asyncio
import os
import uuid
import threading
from dotenv import load_dotenv
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from app.services.llm import get_llm_response, extract_order_details
from app.services.tts import text_to_speech, cleanup_file
from app.services.emotion import detect_emotion, apply_emotion
from app.db.orders import generate_order_id, save_order
from app.routes.voice import conversation_store, is_open
from twilio.rest import Client as TwilioClient

load_dotenv()

deepgram_client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))

# Global state per call
inactivity_counts = {}
inactivity_timers = {}
event_loop = None

def schedule_inactivity(call_sid: str, seconds: int = 30):
    existing = inactivity_timers.get(call_sid)
    if existing:
        existing.cancel()

    def on_inactivity():
        count = inactivity_counts.get(call_sid, 0) + 1
        inactivity_counts[call_sid] = count
        print(f"Inactivity count for {call_sid}: {count}")
        if count == 1:
            print("Caller silent — prompting")
            asyncio.run_coroutine_threadsafe(prompt_silence(call_sid), event_loop)
        else:
            print("Caller still silent — ending call")
            asyncio.run_coroutine_threadsafe(end_silence(call_sid), event_loop)
            inactivity_counts.pop(call_sid, None)
            inactivity_timers.pop(call_sid, None)

    if event_loop:
        inactivity_timers[call_sid] = event_loop.call_later(seconds, on_inactivity)

def say_to_caller(call_sid: str, message: str):
    # Reset inactivity timer — agent just spoke, give customer 30 seconds to respond
    schedule_inactivity(call_sid)

    twilio_client = TwilioClient(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN")
    )
    base_url = os.getenv("BASE_URL")
    filename = f"audio_{uuid.uuid4()}.wav"
    filepath = f"static/{filename}"
    text_to_speech(message, filepath)
    threading.Thread(target=cleanup_file, args=(filepath,)).start()
    host = base_url.replace("https://", "").replace("http://", "")
    twilio_client.calls(call_sid).update(
        twiml=f'''<Response>
            <Play>{base_url}/{filename}</Play>
            <Connect>
                <Stream url="wss://{host}/stream/{call_sid}" track="inbound_track"/>
            </Connect>
            <Pause length="60"/>
        </Response>'''
    )

def end_call(call_sid: str):
    twilio_client = TwilioClient(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN")
    )
    twilio_client.calls(call_sid).update(
        twiml='<Response><Hangup/></Response>'
    )

def handle_order_complete(call_sid: str, ai_reply: str, history: list):
    # Cancel inactivity timer — call is ending
    existing = inactivity_timers.pop(call_sid, None)
    if existing:
        existing.cancel()
    inactivity_counts.pop(call_sid, None)

    clean_reply = ai_reply.replace("ORDER_COMPLETE", "").replace("Goodbye!", "").strip()
    order_id = generate_order_id()
    details = extract_order_details(history)
    print(f"Extracted details: {details}")
    save_order(order_id, details)
    print(f"Order saved: {order_id}")
    base_url = os.getenv("BASE_URL")
    if not is_open():
        final_message = clean_reply + f" Your order ID is {order_id}. Since we are currently closed, our team will confirm your order when we reopen!"
    else:
        final_message = clean_reply + f" Your order ID is {order_id}. Our team will call you within 2 hours to confirm. Thank you for choosing Butter and Batter Bakery. Have a wonderful day!"
    emotional_text = apply_emotion(final_message, "celebratory")
    filename = f"audio_{uuid.uuid4()}.wav"
    filepath = f"static/{filename}"
    text_to_speech(emotional_text, filepath)
    threading.Thread(target=cleanup_file, args=(filepath,)).start()
    print(f"Attempting to play: {base_url}/{filename}")
    try:
        twilio_client = TwilioClient(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
        result = twilio_client.calls(call_sid).update(
            twiml=f'''<Response>
                <Play>{base_url}/{filename}</Play>
                <Pause length="3"/>
                <Hangup/>
            </Response>'''
        )
        print(f"Twilio update success: {result.status}")
    except Exception as e:
        print(f"Twilio update failed: {e}")

async def prompt_silence(call_sid: str):
    base_url = os.getenv("BASE_URL")
    filename = f"audio_{uuid.uuid4()}.wav"
    filepath = f"static/{filename}"
    text_to_speech("Hello, are you still there? How can I help you today?", filepath)
    threading.Thread(target=cleanup_file, args=(filepath,)).start()
    host = base_url.replace("https://", "").replace("http://", "")
    try:
        twilio_client = TwilioClient(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
        result = twilio_client.calls(call_sid).update(
            twiml=f'''<Response>
                <Play>{base_url}/{filename}</Play>
                <Connect>
                    <Stream url="wss://{host}/stream/{call_sid}" track="inbound_track"/>
                </Connect>
                <Pause length="60"/>
            </Response>'''
        )
        print(f"Prompt silence success: {result.status}")
    except Exception as e:
        print(f"Prompt silence failed: {e}")

async def end_silence(call_sid: str):
    base_url = os.getenv("BASE_URL")
    filename = f"audio_{uuid.uuid4()}.wav"
    filepath = f"static/{filename}"
    text_to_speech("We still haven't heard from you. Thank you for calling Butter and Batter Bakery. Please call us back anytime. Goodbye!", filepath)
    threading.Thread(target=cleanup_file, args=(filepath,)).start()
    try:
        twilio_client = TwilioClient(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
        result = twilio_client.calls(call_sid).update(
            twiml=f'''<Response>
                <Play>{base_url}/{filename}</Play>
                <Pause length="2"/>
                <Hangup/>
            </Response>'''
        )
        print(f"End silence success: {result.status}")
    except Exception as e:
        print(f"End silence failed: {e}")

async def process_transcript(call_sid: str, transcript: str):
    if not transcript.strip():
        return
    print(f"User said: {transcript}")
    history = conversation_store.get(call_sid, [])
    history.append({"role": "user", "content": transcript})
    ai_reply = get_llm_response(call_sid, transcript, history)
    history.append({"role": "assistant", "content": ai_reply})
    conversation_store[call_sid] = history
    if "ORDER_COMPLETE" in ai_reply:
        threading.Thread(
            target=handle_order_complete,
            args=(call_sid, ai_reply, history)
        ).start()
    else:
        emotion = detect_emotion(ai_reply, history)
        emotional_text = apply_emotion(ai_reply, emotion)
        say_to_caller(call_sid, emotional_text)

async def handle_stream(websocket, call_sid: str):
    global event_loop
    print(f"WebSocket opened for call: {call_sid}")
    loop = asyncio.get_event_loop()
    event_loop = loop

    dg_connection = deepgram_client.listen.live.v("1")
    transcript_buffer = []
    silence_timer = None

    def on_transcript(self, result, **kwargs):
        nonlocal silence_timer
        try:
            is_final = result.is_final
            sentence = result.channel.alternatives[0].transcript
            if not sentence or not is_final:
                return
            # Customer spoke — reset inactivity timer and count
            inactivity_counts[call_sid] = 0
            schedule_inactivity(call_sid)
            print(f"Final transcript: {sentence}")
            transcript_buffer.append(sentence)
            if silence_timer:
                silence_timer.cancel()
            full_transcript = " ".join(transcript_buffer)
            transcript_buffer.clear()
            silence_timer = loop.call_later(
                2.0,
                lambda: asyncio.run_coroutine_threadsafe(
                    process_transcript(call_sid, full_transcript),
                    loop
                )
            )
        except Exception as e:
            print(f"Transcript error: {e}")

    dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    options = LiveOptions(
        model="nova-2",
        language="en-IN",
        smart_format=True,
        interim_results=True,
        utterance_end_ms="1000",
        vad_events=True,
        encoding="mulaw",
        sample_rate=8000
    )
    if not dg_connection.start(options):
        print("Failed to start Deepgram connection")
        return
    print("Deepgram live connection started")
    schedule_inactivity(call_sid)

    try:
        async for message in websocket.iter_text():
            import json
            import base64
            data = json.loads(message)
            event = data.get("event")
            if event == "media":
                payload = data["media"]["payload"]
                audio = base64.b64decode(payload)
                dg_connection.send(audio)
            elif event == "stop":
                print("Stream stopped")
                break
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        dg_connection.finish()
        print(f"WebSocket closed for call: {call_sid}")