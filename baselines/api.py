"""Runtime-only OpenAI-compatible or Azure API configuration and response validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from baselines.common import atomic_json, read_table, validate_changes

MODEL_ENV = {
    "gpt41": ("CLEANBENCH_MODEL_GPT41", "gpt-4.1"),
    "gpt52": ("CLEANBENCH_MODEL_GPT52", "gpt-5.2"),
    "gpt55": ("CLEANBENCH_MODEL_GPT55", "gpt-5.5"),
    "astra": ("CLEANBENCH_MODEL_ASTRA", "gpt-6-astra"),
    "cleanagent": ("CLEANBENCH_MODEL_WORKFLOWS", "gpt-4o-2024-11-20"),
    "cocoon": ("CLEANBENCH_MODEL_WORKFLOWS", "gpt-4o-2024-11-20"),
}


def secret(name):
    filename = os.environ.get(name + "_FILE")
    return Path(filename).read_text().strip() if filename else os.environ.get(name, "")


def model_for(method):
    name, default = MODEL_ENV[method]
    return os.environ.get(name) or default


def client(timeout=90):
    from openai import AzureOpenAI, OpenAI

    common = dict(
        timeout=float(os.environ.get("CLEANBENCH_API_TIMEOUT", str(timeout))), max_retries=0
    )
    if os.environ.get("CLEANBENCH_API_PROVIDER", "openai") == "azure":
        key, endpoint = secret("AZURE_OPENAI_API_KEY"), os.environ.get("AZURE_OPENAI_ENDPOINT")
        if not key or not endpoint:
            raise ValueError("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY (or _FILE)")
        return AzureOpenAI(
            api_key=key,
            azure_endpoint=endpoint,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-03-01-preview"),
            **common,
        )
    key = secret("OPENAI_API_KEY")
    if not key:
        raise ValueError("Set OPENAI_API_KEY or OPENAI_API_KEY_FILE")
    return OpenAI(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL") or None, **common)


def issues_to_changes(raw, headers, rows):
    data = json.loads(raw) if isinstance(raw, str) else raw
    if (
        not isinstance(data, dict)
        or set(data) != {"issues"}
        or not isinstance(data["issues"], list)
    ):
        raise ValueError("Expected an object containing an issues list")
    changes = []
    for issue in data["issues"]:
        required = {
            "row",
            "column",
            "error_type",
            "observed",
            "explanation",
            "corrected_value",
            "confidence",
        }
        if not isinstance(issue, dict) or set(issue) != required:
            raise ValueError("Invalid issue schema")
        if issue["error_type"] not in {
            "typo",
            "inconsistency",
            "semantic_incompatible",
            "numeric_outlier",
        } or issue["confidence"] not in {"low", "medium", "high"}:
            raise ValueError("Invalid error type or confidence")
        if not isinstance(issue["explanation"], str):
            raise ValueError("Invalid explanation")
        i = issue.get("row")
        if type(i) is not int or not 0 <= i < len(rows) or issue.get("column") not in headers:
            raise ValueError("Invalid issue coordinate")
        j = headers.index(issue["column"])
        if issue.get("observed") != rows[i][j]:
            raise ValueError("Observed string does not match the input")
        if "corrected_value" not in issue:
            raise ValueError("Missing corrected_value")
        changes.append(dict(row=i, col=j, corrected_value=issue["corrected_value"]))
    return validate_changes(changes, headers, rows)


def direct(method, dirty, directory, repetition):
    # The published direct-API workflow allows two attempts for a table.
    for attempt in (1, 2):
        work = directory / f"attempt_{attempt:02}"
        work.mkdir()
        try:
            return direct_attempt(method, dirty, work, repetition)
        except Exception as error:
            status = getattr(error, "status_code", None)
            atomic_json(work / "error.json", {"kind": type(error).__name__, "http_status": status})
            if (
                attempt == 2
                or status in {401, 403, 404}
                or getattr(error, "code", None) == "insufficient_quota"
            ):
                raise


def direct_attempt(method, dirty, directory, repetition):
    headers, rows = read_table(dirty)
    prompt = (Path(__file__).parent / "prompts" / f"api_run_{repetition:02}.txt").read_text()
    user = json.dumps(
        {"headers": headers, "rows": [{"row": i, "values": r} for i, r in enumerate(rows)]},
        ensure_ascii=False,
    )
    if method == "gpt41":
        request = dict(
            model=model_for(method),
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user}],
        )
        atomic_json(directory / "request.json", request)
        response = client().chat.completions.create(**request).model_dump()
        atomic_json(directory / "response.json", response)
        if response["choices"][0]["finish_reason"] != "stop":
            raise ValueError("Incomplete model response")
        text = response["choices"][0]["message"]["content"]
    else:
        request = dict(
            model=model_for(method),
            input=user,
            instructions=prompt,
            reasoning={"effort": "low" if method == "astra" else "none", "summary": "detailed"},
        )
        atomic_json(directory / "request.json", request)
        response = client().responses.create(**request)
        atomic_json(directory / "response.json", response.model_dump())
        if response.status != "completed":
            raise ValueError("Incomplete model response")
        text = response.output_text
    return {"changes": issues_to_changes(text, headers, rows)}


class WorkflowChat:
    """Preserve native messages and sampling settings; no response-cache reuse between runs."""

    def __init__(self, method, directory):
        self.method, self.directory = method, directory
        self.recipe = {"model": model_for(method), "temperature": 0}
        self.client = client(timeout=60 if method == "cleanagent" else 90)
        self.calls = self.reused = self.input_tokens = self.output_tokens = 0

    def __call__(
        self, messages, temperature=0.1, top_p=0.1, use_cache=True, api_type=None, return_cost=False
    ):
        if return_cost:
            raise ValueError("Cost estimation is not part of this workflow")
        self.calls += 1
        request = dict(
            model=self.recipe["model"], messages=messages, temperature=temperature, top_p=top_p
        )
        atomic_json(self.directory / "requests" / f"{self.calls:04}.json", request)
        response = self.client.chat.completions.create(**request).model_dump()
        atomic_json(self.directory / "responses" / f"{self.calls:04}.json", response)
        allowed = {"stop", "length"} if self.method == "cleanagent" else {"stop"}
        if response["choices"][0]["finish_reason"] not in allowed:
            raise ValueError("Incomplete workflow response")
        usage = response.get("usage") or {}
        self.input_tokens += usage.get("prompt_tokens", 0)
        self.output_tokens += usage.get("completion_tokens", 0)
        return response
