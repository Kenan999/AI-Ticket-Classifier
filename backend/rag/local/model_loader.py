"""Load a local Sentence Transformers embedding model only when requested."""
from .config import model_path


def load_model():
    path = model_path()
    if not path.is_dir() or not (path / 'modules.json').is_file():
        raise FileNotFoundError(f'Embedding model not installed at {path}; follow backend/rag/README.md')
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError('Install the optional local embedding requirements first') from exc
    return SentenceTransformer(str(path), local_files_only=True, trust_remote_code=False)


def encode(model, texts):
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.tolist()
