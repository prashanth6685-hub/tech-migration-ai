"""RAG package: local embeddings, vector store, ingestion, retrieval.

Phase 5 wires official documentation into answers. All knowledge access goes
through these interfaces so the embedding model and vector DB can be swapped
by configuration alone — the same seam AIProvider gives the LLM.
"""
