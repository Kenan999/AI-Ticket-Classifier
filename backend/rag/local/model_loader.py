"""Local E5 embeddings using already-installed torch/transformers; no downloads."""
from .config import model_path
from functools import lru_cache


@lru_cache(maxsize=1)
def load_model():
    path = model_path()
    if not path.is_dir() or not (path / 'config.json').is_file():
        raise FileNotFoundError(f'Local embedding model missing: {path}')
    from transformers import AutoTokenizer, AutoModel
    model = AutoModel.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
    return model, tokenizer


def encode(model, texts):
    import torch
    import torch.nn.functional as F
    network, tokenizer = model
    with torch.inference_mode():
        inputs = tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors='pt')
        output = network(**inputs).last_hidden_state
        mask = inputs['attention_mask'].unsqueeze(-1)
        pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        return F.normalize(pooled, p=2, dim=1).tolist()
