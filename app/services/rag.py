import os
from dotenv import load_dotenv
from openai import OpenAI
from app.db.connection import get_db

load_dotenv()

_openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_embedding(text):
    response = _openai.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

def search_knowledge_base(query: str, limit: int = 20) -> str:
    query_embedding = get_embedding(query)
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT content, category
            FROM knowledge_base
            ORDER BY embedding <-> %s::vector
            LIMIT %s
        """, (embedding_str, limit))
        results = cur.fetchall()
        cur.close()
    if not results:
        return ""
    return "\n".join([f"[{row[1].upper()}] {row[0]}" for row in results])
