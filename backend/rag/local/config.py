"""Local embedding configuration; model files remain outside Git."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODEL_ID = 'intfloat/multilingual-e5-small'
MODEL_DIR = ROOT / 'results' / 'local_models' / 'multilingual-e5-small'
MODEL_NAME = 'multilingual-e5-small'
HOST = '127.0.0.1'
PORT = 18643


def model_path():
    return Path(os.environ.get('LOCAL_EMBEDDING_MODEL_PATH', str(MODEL_DIR))).expanduser().resolve()
