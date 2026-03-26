import os
from openai import OpenAI
from app.services.rag import search_knowledge_base

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

conversation_store = {}

def get_llm_response(call_sid: str, transcript: str, history: list) -> str:
    recent_history = history[-4:] if len(history) > 4 else history
    conversation_context = " ".join([m["content"] for m in recent_history])
    search_query = f"{conversation_context} {transcript}"
    context = search_knowledge_base(search_query, 20)
    print(f"context found: {context}")

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
        Only return these 5 lines, nothing else.
        """}
    ] + history

    result = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    return result.choices[0].message.content