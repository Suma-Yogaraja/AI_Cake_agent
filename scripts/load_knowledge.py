import os
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client=OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def get_embedding(text:str):
    response=client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

def load_knowldege(content:str,category:str):
    embedding=get_embedding(content)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO knowledge_base (content, embedding, category)
        VALUES (%s, %s, %s)
    """, (content, embedding, category))
    conn.commit()
    cur.close()
    conn.close()
    print(f"Loaded: {content[:60]}...")

# Bakery knowledge base
menu_items=[
    "Chocolate cake is available in 6 inch for $25, 8 inch for $35, 10 inch for $45. Rich dark chocolate sponge with chocolate ganache frosting.",
    "Vanilla cake is available in 6 inch for $22, 8 inch for $32, 10 inch for $42. Classic vanilla sponge with buttercream frosting.",
    "Red velvet cake is available in 6 inch for $28, 8 inch for $38, 10 inch for $48. Moist red velvet sponge with cream cheese frosting.",
    "Strawberry cake is available in 6 inch for $26, 8 inch for $36, 10 inch for $46. Fresh strawberry sponge with strawberry cream frosting.",
    "All cakes can be customised with a message on top at no extra charge.",
    "Custom cake designs and decorations are available for an additional charge starting from $15. Please call to discuss.",
    "We do not currently offer gluten free or vegan cake options.",
    "All cakes serve approximately 8 people for a 6 inch, 15 people for an 8 inch, and 25 people for a 10 inch.",
]

faqs = [
    "Our business hours are Monday to Saturday, 9am to 6pm. We are closed on Sundays.",
    "We are located at 123 Baker Street. Free parking is available outside.",
    "Orders must be placed at least 48 hours in advance. Same day orders are not available.",
    "We offer delivery within 10km radius for a flat fee of $10. Orders above $50 get free delivery.",
    "Payment can be made by cash or card on collection. Online payment is not currently available.",
    "Cancellations must be made at least 24 hours before pickup time for a full refund.",
    "We can accommodate nut allergies — please mention when placing your order.",
    "Birthday cake candles and cake boxes are provided free of charge with every order.",
]

policies = [
    "Orders are confirmed only after a callback from our team within 2 hours.",
    "If you have not received a confirmation call within 2 hours, please call us back.",
    "Wedding cakes and large event orders require a 50% deposit at the time of booking.",
    "We cannot guarantee exact colour matching for custom cake designs.",
]

for item in menu_items:
    load_knowldege(item,"menu")

for faq in faqs:
    load_knowldege(faq,"faq")

for policy in policies:
    load_knowldege(policy,"policy")
    