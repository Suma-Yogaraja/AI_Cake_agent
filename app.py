from flask import Flask, request,session
from twilio.twiml.voice_response import VoiceResponse
from openai import OpenAI
import psycopg2
import random
import string
import os
from dotenv import load_dotenv
import time

load_dotenv()

app = Flask(__name__)
app.secret_key="cakeShop"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def generate_order_id():
    numbers=''.join(random.choices(string.digits,k=4))
    return f"SW-{numbers}"

def extract_order_details(history):
    messages=[
        {"role": "system","content": """
         Extract the order details from this conversation and return them in this exact format:
         NAME: <customer name>
         FLAVOUR: <cake flavour>
         SIZE: <cake size>
         MESSAGE: <message on cake or 'none'>
         PHONE: <customer phone number>
         Only return these 5 lines, nothing else.
         """}
    ]+history
    result= client.chat.completions.create(
        model="gpt-4o",
        messages=messages

    )
    return result.choices[0].message.content

def save_order(order_id,details):
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



SYSTEM_PROMPT = """
You are the friendly front desk assistant for Butter and batter Bakery.
Keep responses short — this is a phone call, not an essay.
You can help with:
- Our menu: chocolate cake, vanilla cake, red velvet, strawberry cake. All available in 6 inch, 8 inch, 10 inch.
-6 inch will costs 5$ ,8 inch costs 20 $ and 10 inch costs 50$
- Business hours: Monday to Saturday, 9am to 6pm.
- Taking orders: collect in this order:
    1. Customer name-fter they say their name, ask them to spell it out to make sure you get it right. For example: "Could you spell that out for me?"
    2. Cake flavour
    3. Cake size
    4. Message on cake-repeat the message back to confirm it's correct before moving on
    5. Phone number for confirmation-must be exactly 10 digits.after customer gives it, read it back digit by digit and ask them to confirm it is correct. Only proceed if they confirm.
- Once you have all details, confirm the order back to the customer and say a warm goodbye.
- After your goodbye message, add exactly this word on a new line: ORDER_COMPLETE

If you don't know something, say you'll pass the message to the team.
"""

@app.route("/voice", methods=["POST"])
def voice():
    speech = request.form.get("SpeechResult", "")
    response = VoiceResponse()

    history=session.get("history",[])

    if not speech:
        session["history"]=[]
        response.say("Hello! Welcome to Butter and Batter Bakery. How can I help you today?")
        response.gather(
            input="speech",
            action="/voice",
            timeout=3,
            speech_timeout="auto"
        )
        return str(response)

    print(f"User said: {speech}")

    history.append({"role":"user","content":speech})
    
    start=time.time()
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history
    )
    end=time.time()
    ai_reply = completion.choices[0].message.content

    print(f"GPT-4o took: {round(end - start, 2)} seconds")
    print(f"AI replied: {ai_reply}")

    history.append({"role":"assistant","content":ai_reply})
    session["history"]=history

    if "ORDER_COMPLETE" in ai_reply:
       
        clean_reply = ai_reply.replace("ORDER_COMPLETE", "").strip()
        order_id = generate_order_id()

        start=time.time()
        details = extract_order_details(history)
        end=time.time()

        print(f"Extracted details: {details}")
        print(f"Order extraction took: {round(end - start, 2)} seconds")

        save_order(order_id, details)

        response.say(clean_reply + f" Your order ID is {order_id}. Goodbye!")
        response.hangup()
    else:
        response.say(ai_reply)
        response.gather(
        input="speech",
        action="/voice",
        timeout=3,
        speech_timeout="auto"
    )

    return str(response)

if __name__ == "__main__":
    app.run(port=5000, debug=True)