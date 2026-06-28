# Test Framework

## Overview
This document is used to test the documentation server's RAG capabilities. It verifies hybrid search (BM25 + Vector) and the ingestion pipeline.

## Features
- **Chunking**: Splits markdown into semantic blocks based on headers.
- **Embedding**: Converts text to vectors via LM Studio.
- **Retrieval**: Combines keyword matching (BM25) and semantic similarity.

## Configuration
Ensure `DATA_DIR` is set correctly in `.env` (default: `/data/raw`).

## Testing
To verify indexing, query for terms like "chunking", "embedding", or "hybrid search".
