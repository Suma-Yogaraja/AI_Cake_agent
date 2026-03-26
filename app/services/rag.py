from openai import OpenAI
from app.db.connection import get_db_connection
from app.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

def get_embedding(text):
    response = client.embeddings.create(
        model="text-embedding-ada-002",
        input=text
    )
    return response.data[0].embedding

def search_knowledge_base(query, top_k=3):
    try:
        query_embedding = get_embedding(query)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT content, category,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM knowledge_base
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (query_embedding, query_embedding, top_k))
        results = cur.fetchall()
        cur.close()
        conn.close()
        if not results:
            return ""
        context = "\n\n".join([
            f"[{r['category']}]: {r['content']}" for r in results
        ])
        return context
    except Exception as e:
        print(f" RAG search error: {e}")
        return ""