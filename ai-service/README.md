# ai-service

Service Python (FastAPI) : RAG + connexion Claude.

- `ingestion/` : pipeline PDF → pages.json → nettoyage → parsing structurel → chunking → embeddings → pgvector (Phases 3-7)
- `app/` : service RAG + endpoint appelé par le backend (Phases 9-10)
