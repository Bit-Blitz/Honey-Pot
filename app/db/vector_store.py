import chromadb
import os
from chromadb.config import Settings
from app.core.config import settings

class VectorStore:
    def __init__(self):
        self.persist_directory = os.path.join(os.getcwd(), "db", "vector_store")
        os.makedirs(self.persist_directory, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.collection = self.client.get_or_create_collection(name="scammer_fingerprints")

    def add_fingerprint(self, session_id: str, text: str, metadata: dict):
        self.collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[session_id]
        )

    def search_similar(self, text: str, limit: int = 3):
        results = self.collection.query(
            query_texts=[text],
            n_results=limit
        )
        return results

vector_db = VectorStore()
