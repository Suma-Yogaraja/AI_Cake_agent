import os
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
from app.services.rag import search_knowledge_base

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
    - Only when customer confirms,  then add ORDER_COMPLETE on a new line
    
You are warm, friendly and conversational — like a real person working at a bakery. 
If asked something outside your knowledge, respond naturally like a human would.

"""

conversation_store = {}

def get_llm_response(call_sid: str, transcript: str, history: list) -> str:
    recent_history = history[-4:] if len(history) > 4 else history
    conversation_context = " ".join([m["content"] for m in recent_history])
    search_query = f"{conversation_context} {transcript}"
    context = search_knowledge_base(search_query, 20)
    print(f"context found: {context}")

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
        print(f"Enhanced prompt context section: {context[:200]}")
    else:
        print("No context added to prompt")

    start_time = __import__('time').time()
    completion = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": enhanced_prompt}] + history
    )
    end_time = __import__('time').time()

    ai_reply = completion.choices[0].message.content
    print(f"GPT-4o took: {round(end_time - start_time, 2)} seconds")
    print(f"AI replied: {ai_reply}")
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