import os
import uuid
import threading
from fastapi import APIRouter, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse
from twilio.request_validator import RequestValidator
from app.services.stt import transcribe_with_deepgram
from app.services.tts import text_to_speech, cleanup_file
from app.services.llm import get_llm_response, extract_order_details
from app.services.emotion import detect_emotion, apply_emotion
from app.db.orders import generate_order_id, save_order
from app.routes.voice import conversation_store, validate_twilio_request, is_open

router = APIRouter()

@router.post("/process")
async def process(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    recording_url = form.get("RecordingUrl", "")

    if not validate_twilio_request(request, dict(form)):
        print("Invalid Twilio signature — request rejected")
        return Response("Forbidden", status_code=403)

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

    # Transcribe
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
    ai_reply = get_llm_response(call_sid, transcript, history)
    history.append({"role": "assistant", "content": ai_reply})
    conversation_store[call_sid] = history

    base_url = os.getenv("BASE_URL")

    if "ORDER_COMPLETE" in ai_reply:
        clean_reply = ai_reply.replace("ORDER_COMPLETE", "").replace("Goodbye!", "").strip()
        order_id = generate_order_id()
        details = extract_order_details(history)
        save_order(order_id, details)
        print(f"Order saved: {order_id}")

        if not is_open():
            final_message = (
                clean_reply +
                f" Your order ID is {order_id}."
                " Since we're currently closed, our team will confirm your order when we reopen!"
            )
        else:
            final_message = clean_reply + f" Your order ID is {order_id}. Goodbye!"

        emotional_text = apply_emotion(final_message, "celebratory")
        filename = f"static/audio_{uuid.uuid4()}.wav"
        text_to_speech(emotional_text, filename)
        threading.Thread(target=cleanup_file, args=(filename,)).start()

        response.play(f"{base_url}/{filename}")
        response.hangup()
    else:
        emotion = detect_emotion(ai_reply, history)
        print(f"Emotion detected: {emotion}")
        emotional_text = apply_emotion(ai_reply, emotion)
        filename = f"static/audio_{uuid.uuid4()}.wav"
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