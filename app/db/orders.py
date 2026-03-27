import os
import random
import string
import psycopg2

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def generate_order_id():
    numbers = ''.join(random.choices(string.digits, k=4))
    return f"SW-{numbers}"

def save_order(order_id, details):
    lines = details.strip().split("\n")
    data = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (order_id, customer_name, cake_flavour, cake_size, cake_message, customer_phone,allergies)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        order_id,
        data.get("NAME", "unknown"),
        data.get("FLAVOUR", "unknown"),
        data.get("SIZE", "unknown"),
        data.get("MESSAGE", "none"),
        data.get("PHONE", "unknown"),
        data.get("ALLERGIES", "none")
    ))
    conn.commit()
    cur.close()
    conn.close()