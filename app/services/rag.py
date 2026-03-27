import os
from dotenv import load_dotenv
from openai import OpenAI
import psycopg2

load_dotenv()

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

def get_embedding(text):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

def search_knowledge_base(query: str, limit: int = 20) -> str:
    print(f"Searching knowledge base for: {query[:100]}")
    query_embedding = get_embedding(query)
    conn = get_db()
    cur = conn.cursor()
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
    cur.execute("""
        SELECT content, category
        FROM knowledge_base
        ORDER BY embedding <-> %s::vector
        LIMIT %s
    """, (embedding_str, limit))
    results = cur.fetchall()
    cur.close()
    conn.close()
    if not results:
        return ""
    context = "\n".join([f"[{row[1].upper()}] {row[0]}" for row in results])
    return context
