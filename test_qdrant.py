"""Quick Qdrant connectivity check. Run: python test_qdrant.py"""
from qdrant_client import QdrantClient
from config import QDRANT_URL, QDRANT_API_KEY

print(f"Connecting to {QDRANT_URL} ...")
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
collections = client.get_collections().collections
print("Qdrant connection OK")
print("Existing collections:", [c.name for c in collections] or "(none yet)")
