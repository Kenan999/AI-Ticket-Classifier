"""Explicit, manual download of the project embedding model."""
from .config import MODEL_ID, MODEL_DIR


def download():
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError('Install local embedding requirements first') from exc
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return snapshot_download(repo_id=MODEL_ID, local_dir=str(MODEL_DIR),
                             allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt', '*.md'],
                             local_files_only=False)


if __name__ == '__main__':
    print(download())
