"""Fetch the pretrained NeuSpell checkpoint used by the benchmark."""

import hashlib
import importlib.util
from pathlib import Path

import gdown
from huggingface_hub.constants import HF_HUB_CACHE
from transformers import BertModel, BertTokenizer

package = Path(importlib.util.find_spec("neuspell").origin)
root = package.parent.parent / "data/checkpoints/subwordbert-probwordnoise"
root.mkdir(parents=True, exist_ok=True)
for name, identity, expected in [
    (
        "model.pth.tar",
        "13FnCUPAG-P0-rFIRNewHYXZzwp4HBIjr",
        "78fece6180f32b46ef82267066ff5f2062ef923c04951151c6ec388df751dd76",
    ),
    (
        "vocab.pkl",
        "11Bo86aI0MxAU1MHpF-eYfAHg3HqiT9me",
        "0bdbeed9f99760810b51f27ea609f8f8366c3038b3de99e7603a935018929a41",
    ),
]:
    if not gdown.download(id=identity, output=str(root / name), quiet=False):
        raise RuntimeError("Checkpoint download failed: " + name)
    with (root / name).open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError("Checkpoint checksum mismatch: " + name)
revision = "cd5ef92a9fb2f889e972770a36d4ed042daf221e"
BertTokenizer.from_pretrained("bert-base-cased", revision=revision)
BertModel.from_pretrained("bert-base-cased", revision=revision)
# NeuSpell names the model without a revision. Bind that name to the fixed
# snapshot in the offline cache before NeuSpell's first import.
reference = Path(HF_HUB_CACHE) / "models--bert-base-cased/refs/main"
reference.parent.mkdir(parents=True, exist_ok=True)
reference.write_text(revision)
