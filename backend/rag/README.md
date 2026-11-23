# RAG embeddings

The shared embedding interface supports `gemini`, `openai`, and `local`.
The existing Gemini index stays at `results/rag_vectors.sqlite3`. OpenAI and
local use `results/rag_vectors_openai.sqlite3` and
`results/rag_vectors_local.sqlite3`. Never compare vectors from different
providers or embedding models. When changing an embedding model, rebuild its
index before retrieval.

The default retrieval provider remains Gemini for compatibility. Set
`RAG_EMBEDDING_PROVIDER=local` or `openai` to select another index at runtime.
Index creation is explicit and **does not** run automatically:

    python3 -m backend.rag.retriever index --provider local
    python3 -m backend.rag.retriever index --provider openai
    python3 -m backend.rag.retriever index --provider gemini

Gemini uses `GEMINI_API_KEY` and defaults to `gemini-embedding-001`.
OpenAI uses `OPENAI_API_KEY` and defaults to `text-embedding-3-small`.
Local defaults to `http://127.0.0.1:18643/v1/embeddings` and model ID
`local-embedding-model`; you must start a compatible embedding service and
configure `LOCAL_EMBEDDING_ENDPOINT` and `LOCAL_EMBEDDING_MODEL` to match it.
The Qwen chat-completion model is not itself an embedding service.

The chunker splits Markdown by second-level headings, then by paragraphs and
sentences. It enforces a conservative 1,800 UTF-8-byte input budget, including
space for the document title, and only splits within a sentence as a last resort.
This is a safe practical size bound, **not** exact token counting. Each provider
performs its own internal tokenization; provider-specific exact token counts
are not yet implemented. Rebuild each provider index to apply the new chunks.

## Project-owned local embedding service (manual setup)

The source lives in `backend/rag/local/`, not in an external application.
Model weights are stored in the Git-ignored repository directory
`results/local_models/multilingual-e5-small/`. A fresh clone must explicitly
install dependencies and download the model; nothing runs on import.

On a machine with a supported Python environment, from the **repository root**:

```bash
python3 -m venv .venv-local-embeddings
source .venv-local-embeddings/bin/activate
python -m pip install -r backend/rag/local/requirements.txt
python -m backend.rag.local.download_model
python -m backend.rag.local.server
```

Review the package and model source before installing. The optional dependency
`sentence-transformers` and its dependencies are not installed by the standard
Backend requirements. The server binds to loopback `127.0.0.1:18643` only.
In a second terminal verify `curl http://127.0.0.1:18643/health`, then build
`python -m backend.rag.retriever index --provider local` using a Python
environment with the Backend dependencies. Model ID is `multilingual-e5-small`.
The service uses E5 `passage:` / `query:` prefixes and normalized embeddings.
For a different model, configure and validate a compatible embedding service;
do not reuse this model's index. A live model inference test remains necessary.
