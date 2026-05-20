import os
import uuid
import logging
import threading
from fastapi import APIRouter, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.request_validator import RequestValidator
from datetime import datetime
from app.services.tts import text_to_speech, cleanup_file

router = APIRouter()
logger = logging.getLogger(__name__)

conversation_store = {}

def validate_twilio_request(request: Request, form_data: dict) -> bool:
    validator = RequestValidator(os.getenv("TWILIO_AUTH_TOKEN"))
    url = str(request.url)
    signature = request.headers.get("X-Twilio-Signature", "")
    return validator.validate(url, form_data, signature)

def is_open():
    now = datetime.now()
    if now.weekday() == 6:
        return False
    return 9 <= now.hour < 18

@router.post("/voice")
async def voice(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    conversation_store[call_sid] = []

    if not validate_twilio_request(request, dict(form)):
        logger.warning(f"[{call_sid}] Invalid Twilio signature — request rejected")
        return Response("Forbidden", status_code=403)

    if not is_open():
        greeting = "Hi! This is Butter and Batter Bakery. We're currently closed, but I can still take your order and our team will confirm it once we're back between 9am and 6pm. How can I help you?"
    else:
        greeting = "Hello! Welcome to Butter and Batter Bakery. How can I help you today?"

    filename = f"static/audio_{uuid.uuid4()}.wav"
    text_to_speech(greeting, filename)
    threading.Thread(target=cleanup_file, args=(filename,)).start()

    base_url = os.getenv("BASE_URL")
    response = VoiceResponse()
    response.play(f"{base_url}/{os.path.basename(filename)}")
    connect = Connect()
    connect.stream(
        url=f"wss://{base_url.replace('https://', '')}/stream/{call_sid}",
        track="inbound_track"
    )
    response.append(connect)
    response.pause(length=60)
    return Response(str(response), media_type="application/xml")
