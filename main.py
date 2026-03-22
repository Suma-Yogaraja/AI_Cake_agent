from fastapi import FastAPI,Request,Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse
from openai import OpenAI
import psycopg2 #used for db connection
import random
import string
import os #to extract api key 
from dotenv import load_dotenv
import time
import whisper
import urllib.request
import tempfile
from fastapi import BackgroundTasks
from twilio.rest import Client as TwilioClient

#loads env variable like db,API
load_dotenv()

#ctreates web app API
app=FastAPI()

#connect to open AI
client=OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

#temporary memory
conversation_store={}

whisper_model = whisper.load_model("base")

#db connection
def get_db():
    return psycopg2.connect(
         host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

#generate orderID
def generate_order_id():
    numbers=''.join(random.choices(string.digits,k=4))
    return f"SW-{numbers}"

#extract order details
def extract_order_details(history):
    #read the conversation and extract in this format
    messages=[
        {"role" :"system","content":"""
        Extract the order details from this conversation and return them in this exact format:
        NAME: <customer name>
        FLAVOUR: <cake flavour>
        SIZE: <cake size>
        MESSAGE: <message on cake or 'none'>
        PHONE: <customer phone number>
        Only return these 5 lines, nothing else.
        """
        }
    ]+history

    #send request to AI
    result=client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )

    #NAME: John FLAVOUR: Chocolate ,SIZE: 8 inch ,MESSAGE: Happy Birthday ,PHONE: 1234567890
    return result.choices[0].message.content

def save_order(order_id,details):
    #split text into line
    lines=details.strip().split("\n")
     #create empty dictionary
    data={}
    for line in lines:
        key, value = line.split(":", 1) #splits -NAME: John to key=name ,value=john 
        data[key.strip()] = value.strip() #stores it like : data["NAME"] = "John"

    #connect to db and prepare run command   
    conn = get_db()
    cur = conn.cursor()
    #insert into db
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
    # save to DB
    conn.commit()
    cur.close()
    conn.close()

#function to convert audio file to text
def transcribe_with_whisper(audio_url):
    print(f"Downloading audio from: {audio_url}")
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    # create password manager
    password_mgr=urllib.request.HTTPPasswordMgrWithDefaultRealm()
    # add credential: like for this url ,this is password
    password_mgr.add_password(None,audio_url,account_sid,auth_token)
    handler=urllib.request.HTTPBasicAuthHandler(password_mgr)
    opener=urllib.request.build_opener(handler)

    #create temporary audio file in the local machine,audio file downloaded from twilio and saved as .wav like /tmp/abc123.wav
    with tempfile.NamedTemporaryFile(suffix=".wav",delete=False) as tmp:
        with opener.open(audio_url) as audio_response:
            tmp.write(audio_response.read())
        tmp_path=tmp.name

        print(f"Transcribing with Whisper...")
        start=time.time()
        #take audio file converts to text eg-"text": "I want a chocolate cake"
        result=whisper_model.transcribe(tmp_path,fp16=False)
        end=time.time()
        print(f"Whisper took: {round(end - start, 2)} seconds")
        print(f"Whisper heard: {result['text']}")
        return result["text"]



#AI personality defined 
SYSTEM_PROMPT="""
You are the friendly front desk assistant for Butter and Batter bakery.
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

#end point twilio calls when someonr speaks
@app.post("/voice", response_class=PlainTextResponse)
async def voice(request: Request):
    #get data from twilio
    form =await request.form()

    #unique id for call id
    call_sid=form.get("CallSid","unknown")
    #create response
    response=VoiceResponse()

    
    #what user said
    speech=form.get("SpeechResult","")
    recording_url=form.get("RecordingUrl","")

    if recording_url:
        speech=transcribe_with_whisper(recording_url)
    #unique id for call id
    call_sid=form.get("CallSid","unknown")
    #create response
    response=VoiceResponse()
    #creates memory
    conversation_store[call_sid]=[]

    response.say("Hello! Welcome to Butter and batter Bakery. How can I help you today?")
        #listen to user
    response.record( 
        action="/transcribe",
        max_length=10,
        finish_on_key="#",
        play_beep=False,
        timeout=3
    )
    return str(response)


@app.post("/transcribe", response_class=PlainTextResponse)
async def transcribe(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    recording_url = form.get("RecordingUrl", "")

    response = VoiceResponse()
    history = conversation_store.get(call_sid, [])

    if not recording_url:
        response.say("Sorry I didn't catch that, please try again.")
        response.record(
            action="/transcribe",
            max_length=10,
            finish_on_key="#",
            play_beep=False,
            timeout=3
        )
        return str(response)

    # Transcribe with Whisper
    speech =transcribe_with_whisper(recording_url + ".wav")

    if not speech.strip():
        response.say("Sorry I didn't catch that, please try again.")
        response.record(
            action="/transcribe",
            max_length=10,
            finish_on_key="#",
            play_beep=False,
            timeout=3
        )
        return str(response)

    print(f"User said: {speech}")
    history.append({"role": "user", "content": speech})

    start = time.time()
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history
    )
    end = time.time()

    ai_reply = completion.choices[0].message.content
    print(f"GPT-4o took: {round(end - start, 2)} seconds")
    print(f"AI replied: {ai_reply}")

    history.append({"role": "assistant", "content": ai_reply})
    conversation_store[call_sid] = history

    if "ORDER_COMPLETE" in ai_reply:
        clean_reply = ai_reply.replace("ORDER_COMPLETE", "").strip()

        order_id = generate_order_id()
        print(f"Generated order ID: {order_id}")

        details = extract_order_details(history)
        print(f"Extracted details: {details}")

        save_order(order_id, details)
        print("Order saved to database")

        response.say(clean_reply + f" Your order ID is {order_id}. Goodbye!")
        response.hangup()
    else:
        response.say(ai_reply)
        response.record(
            action="/transcribe",
            max_length=10,
            finish_on_key="#",
            play_beep=False,
            timeout=3
        )

    return str(response)







    






