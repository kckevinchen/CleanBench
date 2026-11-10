from __future__ import annotations

from types import SimpleNamespace


class NativeClient:
    def __init__(self, config, *, chat):
        if config["model"] != chat.recipe["model"]:
            raise ValueError("Native model differs from the frozen transport")
        self.chat = chat

    def create(self, params):
        allowed = {"model", "messages", "temperature", "top_p", "n", "stream", "model_client_cls"}
        if (
            set(params) - allowed
            or params.get("model") != self.chat.recipe["model"]
            or params.get("temperature") != self.chat.recipe["temperature"]
            or params.get("top_p", 1) != 1
            or params.get("n", 1) != 1
            or params.get("stream", False)
            or params.get("model_client_cls", "NativeClient") != "NativeClient"
        ):
            raise ValueError("Native request differs from the frozen generation contract")
        raw = self.chat(params["messages"], temperature=params["temperature"], top_p=1)
        usage = raw.get("usage", {})
        if (
            not all(
                type(usage.get(k)) is int and usage[k] >= 0
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
            or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
            or (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) != 0
        ):
            raise ValueError("Saved native response lacks valid non-reasoning token usage")
        if len(raw["choices"]) != 1 or raw["choices"][0]["message"].get("tool_calls"):
            raise ValueError("Native workflow expects one text reply without API tool calls")
        return SimpleNamespace(
            model=raw["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=raw["choices"][0]["message"]["content"])
                )
            ],
            usage=SimpleNamespace(**usage),
        )

    def message_retrieval(self, response):
        return [choice.message.content for choice in response.choices]

    def cost(self, response):
        # AutoGen requires a numeric placeholder; campaign records token usage,
        # not this framework placeholder as an estimated monetary cost.
        response.cost = 0
        return 0

    @staticmethod
    def get_usage(response):
        return {
            "model": response.model,
            "cost": 0,
            **{
                k: getattr(response.usage, k)
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
        }
