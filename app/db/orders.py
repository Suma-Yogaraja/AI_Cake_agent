import random
import string
from app.db.connection import get_db
from app.models.order import OrderDetails

def generate_order_id() -> str:
    """Generate a unique 6-digit order ID, guaranteed not already in the DB."""
    with get_db() as conn:
        cur = conn.cursor()
        while True:
            order_id = "SW-" + "".join(random.choices(string.digits, k=6))
            cur.execute("SELECT 1 FROM orders WHERE order_id = %s", (order_id,))
            if not cur.fetchone():
                cur.close()
                return order_id

def spoken_order_id(order_id: str) -> str:
    """Format order ID for TTS — commas force a pause between each character.
    'SW-481623' -> 'S, W, 4, 8, 1, 6, 2, 3'"""
    return ", ".join(c for c in order_id if c.isalnum())

def save_order(order_id: str, details: OrderDetails) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders (order_id, customer_name, cake_flavour, cake_size, cake_message, customer_phone, allergies)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            order_id,
            details.name,
            details.flavour,
            details.size,
            details.message,
            details.phone,
            details.allergies,
        ))
        conn.commit()
        cur.close()