import os
import time
import logging
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
from app.services.rag import search_knowledge_base

logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT ="""
You are the friendly front desk assistant for Butter and Batter Bakery.
Keep responses short — this is a phone call, not an essay.

You can help with:
- Our menu: chocolate cake, vanilla cake, red velvet, strawberry cake. All available in 6 inch, 8 inch, 10 inch.
- Business hours: Monday to Saturday, 9am to 6pm.

Taking orders — collect in this order:
    1. Customer name
    2. Cake flavour
    3. Cake size
    4. Message on cake (or none)
    5. Any allergies or special requirements
    6. Phone number for confirmation

Once you have all details:
    - Once you have all details, confirm the order naturally in one short paragraph like:
        "Just to confirm — a 10 inch strawberry cake with no message, no allergies, for Roy. We'll call 1234567899 within 2 hours. "
    - Ask: "Is everything correct, or would you like to make any changes?"
    - If they want changes, collect the updated details and confirm again
    - Only when the customer gives a clear, unqualified confirmation ("yes", "that's correct", "perfect", "looks good") with no "but", "however", "wait", "actually", or follow-up question in the same turn — add ORDER_COMPLETE on a new line
    - If the customer says "yes, but..." or "yes, however..." or asks a follow-up in the same breath, do NOT add ORDER_COMPLETE — address their question first
    
You are warm, friendly and conversational — like a real person working at a bakery. 
If asked something outside your knowledge, respond naturally like a human would.

"""

rag_cache = {}  # call_sid -> KB context string, fetched once per call


def get_llm_response(call_sid: str, transcript: str, history: list) -> str:
    if call_sid not in rag_cache:
        rag_cache[call_sid] = search_knowledge_base(transcript, 20)
        logger.info(f"[{call_sid}] RAG fetched and cached")
    context = rag_cache[call_sid]

    from datetime import datetime
    now = datetime.now()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    current_day = days[now.weekday()]
    current_time = now.strftime("%I:%M %p")
    is_currently_open = now.weekday() != 6 and 9 <= now.hour < 18

    enhanced_prompt = SYSTEM_PROMPT + f"""
        CURRENT TIME CONTEXT:
        - Today is {current_day}
        - Current time is {current_time}
        - Bakery is currently: {"OPEN" if is_currently_open else "CLOSED"}

        When asked if we are open, answer directly using the above — do not ask the customer what day it is.
    """
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
    else:
        logger.warning(f"[{call_sid}] No RAG context found for query")

    start_time = time.time()
    completion = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": enhanced_prompt}] + history
    )
    elapsed = round(time.time() - start_time, 2)

    ai_reply = completion.choices[0].message.content
    logger.info(f"[{call_sid}] GPT-4o replied in {elapsed}s: {ai_reply[:80]}")
    return ai_reply

def extract_order_details(history: list) -> str:
    messages = [
        {"role": "system", "content": """
            Extract the order details from this conversation and return them in this exact format:
            NAME: <customer name>
            FLAVOUR: <cake flavour>
            SIZE: <cake size>
            MESSAGE: <message on cake or 'none'>
            PHONE: <customer phone number>
            ALLERGIES: <any allergies mentioned or 'none'>
            Only return these 6 lines, nothing else.
        """}
    ] + history

    result = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    return result.choices[0].message.content