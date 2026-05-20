import asyncio
import base64
import json
import logging
import os
import uuid
import time
from dotenv import load_dotenv
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from twilio.rest import Client as TwilioClient
from app.services.llm import get_llm_response, extract_order_details, rag_cache
from app.services.tts import text_to_speech_mulaw_bytes
from app.db.orders import generate_order_id, save_order, spoken_order_id
from app.routes.voice import conversation_store, is_open

load_dotenv()

logger = logging.getLogger(__name__)
deepgram_client = DeepgramClient(os.getenv("DEEPGRAM_API_KEY"))
_twilio = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

# Per-call state — all dicts keyed by call_sid, never shared across calls
active_websockets = {}    # call_sid -> WebSocket
stream_sids = {}          # call_sid -> Twilio streamSid
event_loops = {}          # call_sid -> asyncio event loop
inactivity_counts = {}    # call_sid -> int
inactivity_timers = {}    # call_sid -> TimerHandle
is_ai_speaking = {}       # call_sid -> bool (suppress STT while AI is talking)
is_processing = {}        # call_sid -> bool (prevent concurrent LLM calls)
call_timings = {}         # call_sid -> float (turnaround time logging)
mark_events = {}          # mark_name -> asyncio.Event (track audio playback completion)
pending_transcripts = {}  # call_sid -> str (speech captured while AI was talking)


def schedule_inactivity(call_sid: str, seconds: int = 30):
    """(Re)start the inactivity timer for a call. Each call has its own timer."""
    existing = inactivity_timers.get(call_sid)
    if existing:
        existing.cancel()

    loop = event_loops.get(call_sid)
    if not loop:
        return

    def on_inactivity():
        # AI is mid-response — don't interrupt, reschedule and check again later
        if is_processing.get(call_sid) or is_ai_speaking.get(call_sid):
            inactivity_timers[call_sid] = loop.call_later(seconds, on_inactivity)
            return

        count = inactivity_counts.get(call_sid, 0) + 1
        inactivity_counts[call_sid] = count
        if count == 1:
            logger.info(f"[{call_sid}] Caller silent — prompting")
            asyncio.run_coroutine_threadsafe(prompt_silence(call_sid), loop)
        else:
            logger.info(f"[{call_sid}] Caller still silent — ending call")
            asyncio.run_coroutine_threadsafe(end_silence(call_sid), loop)
            inactivity_counts.pop(call_sid, None)
            inactivity_timers.pop(call_sid, None)

    inactivity_timers[call_sid] = loop.call_later(seconds, on_inactivity)


async def send_audio_to_caller(call_sid: str, mulaw_bytes: bytes) -> asyncio.Event:
    """Send raw mulaw audio chunks over the open Twilio media stream WebSocket.

    Twilio plays the audio to the caller in real time. A mark event is sent
    after the last chunk — Twilio echoes it back when playback reaches that
    point. Returns the asyncio.Event that will be set when that happens,
    so callers can await actual playback completion instead of guessing.
    """
    ws = active_websockets.get(call_sid)
    sid = stream_sids.get(call_sid)
    if not ws or not sid:
        logger.warning(f"[{call_sid}] No active WebSocket — cannot send audio")
        ev = asyncio.Event()
        ev.set()
        return ev

    # 320 bytes = 40ms of mulaw 8kHz audio per chunk
    CHUNK = 320
    for i in range(0, len(mulaw_bytes), CHUNK):
        chunk = mulaw_bytes[i:i + CHUNK]
        await ws.send_text(json.dumps({
            "event": "media",
            "streamSid": sid,
            "media": {"payload": base64.b64encode(chunk).decode("utf-8")}
        }))

    # Mark sent after all audio — Twilio echoes it when audio finishes playing
    mark_name = f"{call_sid}_{uuid.uuid4().hex[:8]}"
    ev = asyncio.Event()
    mark_events[mark_name] = ev
    await ws.send_text(json.dumps({
        "event": "mark",
        "streamSid": sid,
        "mark": {"name": mark_name}
    }))
    return ev


async def say_to_caller(call_sid: str, message: str):
    """Generate TTS and deliver it to the caller over the existing WebSocket.
    Blocks until Twilio confirms playback is complete, then resets inactivity.
    Guarantees is_ai_speaking is cleared and inactivity is reset even on failure."""
    start_time = call_timings.pop(call_sid, None)
    if start_time:
        logger.info(f"[{call_sid}] Total turnaround time: {round(time.time() - start_time, 2)}s")

    is_ai_speaking[call_sid] = True
    try:
        mulaw_bytes = await asyncio.to_thread(text_to_speech_mulaw_bytes, message)
        done_event = await send_audio_to_caller(call_sid, mulaw_bytes)
        try:
            await asyncio.wait_for(done_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning(f"[{call_sid}] Mark timeout — continuing anyway")
    except Exception as e:
        logger.error(f"[{call_sid}] TTS/send failed: {e}")
    finally:
        is_ai_speaking[call_sid] = False
        pending = pending_transcripts.pop(call_sid, None)
        if pending:
            logger.info(f"[{call_sid}] Processing pending transcript: {pending}")
            await process_transcript(call_sid, pending)
        else:
            schedule_inactivity(call_sid)


async def prompt_silence(call_sid: str):
    """Play a 'are you still there?' prompt, then restart the inactivity timer."""
    is_ai_speaking[call_sid] = True
    try:
        mulaw_bytes = await asyncio.to_thread(
            text_to_speech_mulaw_bytes,
            "Hello, are you still there? How can I help you today?"
        )
        done_event = await send_audio_to_caller(call_sid, mulaw_bytes)
        try:
            await asyncio.wait_for(done_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
    except Exception as e:
        logger.error(f"[{call_sid}] TTS/send failed in prompt_silence: {e}")
    finally:
        is_ai_speaking[call_sid] = False
        pending = pending_transcripts.pop(call_sid, None)
        if pending:
            logger.info(f"[{call_sid}] Processing pending transcript after silence prompt: {pending}")
            await process_transcript(call_sid, pending)
        else:
            schedule_inactivity(call_sid)


async def end_silence(call_sid: str):
    """Play a goodbye message then hang up the call."""
    is_ai_speaking[call_sid] = True
    try:
        mulaw_bytes = await asyncio.to_thread(
            text_to_speech_mulaw_bytes,
            "We still haven't heard from you. Thank you for calling Butter and Batter Bakery. Please call us back anytime. Goodbye!"
        )
        done_event = await send_audio_to_caller(call_sid, mulaw_bytes)
        try:
            await asyncio.wait_for(done_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
    except Exception as e:
        logger.error(f"[{call_sid}] TTS/send failed in end_silence: {e}")
    finally:
        is_ai_speaking[call_sid] = False
        end_call(call_sid)


def end_call(call_sid: str):
    _twilio.calls(call_sid).update(twiml='<Response><Hangup/></Response>')
    logger.info(f"[{call_sid}] Call ended")


async def handle_order_complete(call_sid: str, ai_reply: str, history: list):
    """Extract order details, save to DB, play confirmation, and hang up."""
    existing = inactivity_timers.pop(call_sid, None)
    if existing:
        existing.cancel()
    inactivity_counts.pop(call_sid, None)

    clean_reply = ai_reply.replace("ORDER_COMPLETE", "").replace("Goodbye!", "").strip()
    order_id = generate_order_id()
    details = await asyncio.to_thread(extract_order_details, history)
    await asyncio.to_thread(save_order, order_id, details)
    logger.info(f"[{call_sid}] Order saved: {order_id}")

    spoken_id = spoken_order_id(order_id)
    if not is_open():
        final_message = (
            clean_reply +
            f" Your order ID is {spoken_id}. Since we are currently closed, "
            "our team will confirm your order when we reopen!"
        )
    else:
        final_message = (
            clean_reply +
            f" Your order ID is {spoken_id}. Our team will call you within 2 hours "
            "to confirm. Thank you for choosing Butter and Batter Bakery. Have a wonderful day!"
        )

    is_ai_speaking[call_sid] = True
    try:
        mulaw_bytes = await asyncio.to_thread(text_to_speech_mulaw_bytes, final_message)
        done_event = await send_audio_to_caller(call_sid, mulaw_bytes)
        try:
            await asyncio.wait_for(done_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
    except Exception as e:
        logger.error(f"[{call_sid}] TTS/send failed in handle_order_complete: {e}")
    finally:
        is_ai_speaking[call_sid] = False
        pending = pending_transcripts.pop(call_sid, None)
        if pending:
            logger.info(f"[{call_sid}] User spoke during order completion ({pending!r}) — continuing")
            schedule_inactivity(call_sid)
            asyncio.ensure_future(process_transcript(call_sid, pending))
        else:
            end_call(call_sid)
            _cleanup_state(call_sid)


async def process_transcript(call_sid: str, transcript: str):
    if not transcript.strip():
        return
    if is_ai_speaking.get(call_sid):
        logger.debug(f"[{call_sid}] AI speaking — ignoring transcript: {transcript}")
        return
    if is_processing.get(call_sid):
        logger.debug(f"[{call_sid}] Already processing — ignoring: {transcript}")
        return

    is_processing[call_sid] = True
    try:
        logger.info(f"[{call_sid}] User said: {transcript}")
        history = conversation_store.get(call_sid, [])
        history.append({"role": "user", "content": transcript})
        ai_reply = await asyncio.to_thread(get_llm_response, call_sid, transcript, history)
        history.append({"role": "assistant", "content": ai_reply})
        conversation_store[call_sid] = history

        if "ORDER_COMPLETE" in ai_reply:
            await handle_order_complete(call_sid, ai_reply, history)
        else:
            await say_to_caller(call_sid, ai_reply)
    finally:
        is_processing[call_sid] = False


def _cleanup_state(call_sid: str):
    """Remove all per-call state after a call ends."""
    timer = inactivity_timers.pop(call_sid, None)
    if timer:
        timer.cancel()
    for d in [active_websockets, stream_sids, event_loops, inactivity_counts,
              is_ai_speaking, is_processing, call_timings, pending_transcripts, rag_cache]:
        d.pop(call_sid, None)
    conversation_store.pop(call_sid, None)
    # Unblock and clear only this call's pending mark events
    stale = [name for name in mark_events if name.startswith(f"{call_sid}_")]
    for name in stale:
        mark_events.pop(name).set()


async def handle_stream(websocket, call_sid: str):
    loop = asyncio.get_running_loop()
    event_loops[call_sid] = loop

    dg_connection = deepgram_client.listen.live.v("1")
    transcript_buffer = []

    def on_transcript(self, result, **kwargs):
        try:
            if not result.is_final:
                return
            sentence = result.channel.alternatives[0].transcript
            if not sentence:
                return
            if is_ai_speaking.get(call_sid):
                transcript_buffer.append(sentence)
                return
            inactivity_counts[call_sid] = 0
            schedule_inactivity(call_sid)
            logger.debug(f"[{call_sid}] Final transcript: {sentence}")
            transcript_buffer.append(sentence)
        except Exception as e:
            logger.error(f"[{call_sid}] Transcript error: {e}")

    def on_utterance_end(self, utterance_end, **kwargs):
        if is_ai_speaking.get(call_sid):
            if transcript_buffer:
                pending_transcripts[call_sid] = " ".join(transcript_buffer)
                logger.info(f"[{call_sid}] Pending transcript saved: {pending_transcripts[call_sid]}")
                transcript_buffer.clear()
            return
        logger.debug(f"[{call_sid}] Utterance ended")
        call_timings[call_sid] = time.time()
        if transcript_buffer:
            full_transcript = " ".join(transcript_buffer)
            transcript_buffer.clear()
            asyncio.run_coroutine_threadsafe(
                process_transcript(call_sid, full_transcript), loop
            )

    dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)

    options = LiveOptions(
        model="nova-2",
        language="en-IN",
        smart_format=True,
        interim_results=True,
        utterance_end_ms="1500",
        vad_events=True,
        encoding="mulaw",
        sample_rate=8000
    )
    if not dg_connection.start(options):
        logger.error(f"[{call_sid}] Failed to start Deepgram connection")
        return
    logger.info(f"[{call_sid}] Deepgram live connection started")
    schedule_inactivity(call_sid)

    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                stream_sids[call_sid] = data["start"]["streamSid"]
                active_websockets[call_sid] = websocket
                logger.info(f"[{call_sid}] Stream started — streamSid: {stream_sids[call_sid]}")

            elif event == "media":
                # Always forward caller audio to Deepgram.
                # on_transcript ignores it while AI is speaking.
                payload = data["media"]["payload"]
                dg_connection.send(base64.b64decode(payload))

            elif event == "mark":
                # Twilio echoes back our mark when playback reaches that point —
                # this unblocks say_to_caller / prompt_silence / end_silence.
                mark_name = data.get("mark", {}).get("name", "")
                ev = mark_events.pop(mark_name, None)
                if ev:
                    ev.set()

            elif event == "stop":
                logger.info(f"[{call_sid}] Stream stopped")
                break

    except Exception as e:
        logger.error(f"[{call_sid}] WebSocket error: {e}")
    finally:
        dg_connection.finish()
        _cleanup_state(call_sid)
        logger.info(f"[{call_sid}] WebSocket closed")
