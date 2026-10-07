"""Phase 5 knowledge-base API: ingest documentation, list collections.

Ingestion is a batch job, not a runtime scrape: the UI posts URLs or pasted
markdown, the pipeline fetches/cleans/chunks/embeds/upserts, and later
answers retrieve from the collections. Retrieval failures never fail a
request — answers fall back to model knowledge with an ungrounded marker.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from rag.embeddings import Embedder, get_embedder
from rag.ingest import (
    MAX_MARKDOWN_CHARS,
    MAX_URLS_PER_REQUEST,
    IngestItem,
    ingest_items,
)
from rag.vector_store import VectorStore, collection_name, get_vector_store

router = APIRouter()

DocType = Literal["official", "guide", "api_reference"]


class KnowledgeItem(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2000)
    title: Optional[str] = Field(default=None, max_length=300)
    markdown: Optional[str] = Field(default=None, max_length=MAX_MARKDOWN_CHARS)

    @model_validator(mode="after")
    def _needs_url_or_markdown(self):
        if not self.url and not self.markdown:
            raise ValueError("each item needs a url or markdown")
        if self.markdown and not self.title:
            raise ValueError("markdown items need a title")
        return self


class IngestRequest(BaseModel):
    items: list[KnowledgeItem] = Field(min_length=1, max_length=MAX_URLS_PER_REQUEST)
    tech: str = Field(min_length=1, max_length=80)
    version: Optional[str] = Field(default=None, max_length=40)
    doc_type: DocType = "official"


class IngestResponse(BaseModel):
    collection: str
    chunks_ingested: int
    items: int
    errors: list[str] = []


class CollectionSummary(BaseModel):
    name: str
    chunks: int


@router.post("/knowledge/ingest", response_model=IngestResponse)
async def ingest_knowledge(
    req: IngestRequest,
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
) -> IngestResponse:
    items = [
        IngestItem(url=i.url, title=i.title, markdown=i.markdown) for i in req.items
    ]
    try:
        result = await ingest_items(
            items,
            tech=req.tech,
            version=req.version,
            doc_type=req.doc_type,
            embedder=embedder,
            store=store,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ingestion failed: {exc}")
    return IngestResponse(
        collection=result.collection,
        chunks_ingested=result.chunks_ingested,
        items=result.items,
        errors=result.errors,
    )


@router.get("/knowledge/collections", response_model=list[CollectionSummary])
async def list_knowledge_collections(
    store: VectorStore = Depends(get_vector_store),
) -> list[CollectionSummary]:
    out: list[CollectionSummary] = []
    for name in store.list_collections():
        info = store.collection_info(name)
        if info is not None:
            out.append(CollectionSummary(name=info.name, chunks=info.chunks))
    return out


@router.delete("/knowledge/collections/{name}")
async def delete_knowledge_collection(
    name: str, store: VectorStore = Depends(get_vector_store)
) -> dict:
    # Only docs_* collections are managed here — refuse anything else.
    if not name.startswith("docs_"):
        raise HTTPException(status_code=400, detail="not a managed collection")
    deleted = store.delete_collection(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="collection not found")
    return {"deleted": name}
