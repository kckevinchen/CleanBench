"""Offline checks for required packages, native source and credentials (never prints values)."""

import importlib
import os
import shutil

from baselines.api import secret
from baselines.common import NATIVE_ROOT

PACKAGES = {
    "symspell": ["symspellpy"],
    "neuspell": ["neuspell", "torch", "transformers"],
    "bigdansing": ["pandas", "numpy", "scipy", "jaro"],
    "holistic": ["pandas", "numpy", "jaro"],
    "daisyp": ["pandas", "numpy"],
    "horizon": ["pandas", "numpy"],
    "relative_trust": ["pandas", "numpy"],
    "nadeef": [],
    "llunatic": [],
    "uniclean": ["pyspark", "pandas", "numpy", "networkx"],
    "katara": [],
    "cleanagent": ["autogen", "dataprep.clean", "yaml"],
    "cocoon": ["duckdb", "pandas", "openai"],
    "gpt41": ["openai"],
    "gpt52": ["openai"],
    "gpt55": ["openai"],
    "astra": ["openai"],
    "codex": [],
    "copilot": [],
}


def check(method):
    if method in {
        "bigdansing",
        "holistic",
        "daisyp",
        "horizon",
        "relative_trust",
        "nadeef",
        "llunatic",
        "uniclean",
    }:
        from baselines.rules import load

        load()
    for name in PACKAGES[method]:
        importlib.import_module(name)
    external = NATIVE_ROOT / "external"
    paths = []
    if method in {"bigdansing", "holistic", "daisyp", "horizon", "relative_trust"}:
        paths.append(external / "adr/adr_repo/.git")
    if method == "nadeef":
        paths.extend(
            [
                external / "nadeef/build/bin/nadeef.jar",
                external / "nadeef/build/adapter/NadeefBatch.class",
            ]
        )
    if method == "llunatic":
        paths.append(external / "llunatic/build/NativeBridge.class")
    if method == "uniclean":
        paths.append(external / "uniclean/upstream/uniclean_cleaners/Clean.py")
    if method == "katara":
        paths.append(external / "rein/rein-benchmark/cleaners/katara/katara.py")
        if not any((external / "katara/knowledge-base").rglob("*.txt")):
            raise ValueError("Download the KATARA knowledge base before running")
    for path in paths:
        if not path.exists():
            raise ValueError("Missing runtime component: " + str(path))
    if method in {"gpt41", "gpt52", "gpt55", "astra", "cleanagent", "cocoon"}:
        provider = os.environ.get("CLEANBENCH_API_PROVIDER", "openai")
        if provider not in {"openai", "azure"}:
            raise ValueError("Unknown API provider")
        name = "AZURE_OPENAI_API_KEY" if provider == "azure" else "OPENAI_API_KEY"
        if not secret(name):
            raise ValueError("Missing " + name + " (or _FILE)")
        if provider == "azure" and not os.environ.get("AZURE_OPENAI_ENDPOINT"):
            raise ValueError("Missing AZURE_OPENAI_ENDPOINT")
    if method in {"codex", "copilot"} and not shutil.which(method):
        raise ValueError("Missing " + method + " executable")
    if method == "codex" and not (secret("CODEX_API_KEY") or secret("OPENAI_API_KEY")):
        raise ValueError("Missing CODEX_API_KEY or OPENAI_API_KEY")
    if method == "copilot" and not secret("COPILOT_GITHUB_TOKEN"):
        raise ValueError("Missing COPILOT_GITHUB_TOKEN")
    return {"method": method, "offline_preflight": "passed"}
