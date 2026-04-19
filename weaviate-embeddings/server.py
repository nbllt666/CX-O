import os
from contextlib import asynccontextmanager
from typing import List, Optional

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.environ.get("MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
DEVICE = "cuda" if torch.cuda.is_available() and os.environ.get("ENABLE_CUDA", "0") == "1" else "cpu"

model: Optional[SentenceTransformer] = None


class EmbeddingRequest(BaseModel):
    text: str


class BatchEmbeddingRequest(BaseModel):
    texts: List[str]


class EmbeddingResponse(BaseModel):
    embedding: List[float]
    dimension: int


class BatchEmbeddingResponse(BaseModel):
    embeddings: List[List[float]]
    dimension: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    print(f"Loading model {MODEL_NAME} on {DEVICE}...")
    model = SentenceTransformer(MODEL_NAME, device=DEVICE)
    print(f"Model loaded successfully. Dimension: {model.get_sentence_embedding_dimension()}")
    yield
    print("Shutting down...")


app = FastAPI(title="Embedding Server", lifespan=lifespan)


@app.get("/.well-known/ready")
async def ready():
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ready"}


@app.post("/vectors", response_model=EmbeddingResponse)
async def get_embedding(request: EmbeddingRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    embedding = model.encode(request.text, convert_to_numpy=True)
    return EmbeddingResponse(
        embedding=embedding.tolist(),
        dimension=len(embedding)
    )


@app.post("/vectors/batch", response_model=BatchEmbeddingResponse)
async def get_batch_embeddings(request: BatchEmbeddingRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    embeddings = model.encode(request.texts, convert_to_numpy=True)
    return BatchEmbeddingResponse(
        embeddings=embeddings.tolist(),
        dimension=embeddings.shape[1]
    )


@app.get("/meta")
async def meta():
    return {
        "model": MODEL_NAME,
        "device": DEVICE,
        "dimension": model.get_sentence_embedding_dimension() if model else None,
        "cuda_available": torch.cuda.is_available(),
    }
