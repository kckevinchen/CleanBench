"""Load CleanAgent's original agent workflow without starting its web interface."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "CleanAgent/main.py"
UPSTREAM_COMMIT = "66c10c2c1d141e7d63946f80a3f660e072d5bbe0"


def load_workflow(agent_api, source: Path = SOURCE) -> dict:
    """Keep the original prompts, termination rule and complete start_chat body."""
    assignments = {
        "CANDIDATE_COLUMN_TYPES",
        "termination_notice",
        "COL_ANNOTATOR_SYSTEM_MESSAGE",
        "PROBLEM",
        "LLM_CONFIG",
        "TERMINATION_MESSAGE",
        "EXTRA_REQUIREMENT",
    }
    nodes, found = [], set()
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in assignments:
                nodes.append(node)
                found.add(target.id)
        elif isinstance(node, ast.AsyncFunctionDef) and node.name == "start_chat":
            nodes.append(node)
            found.add(node.name)
    missing = (assignments | {"start_chat"}) - found
    if missing:
        raise ValueError(f"Original CleanAgent workflow is incomplete: {sorted(missing)}")
    namespace = {
        "CONFIG_LIST": [],
        **{
            name: getattr(agent_api, name)
            for name in (
                "AssistantAgent",
                "UserProxyAgent",
                "GroupChat",
                "GroupChatManager",
                "ConversableAgent",
            )
        },
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


async def run_workflow(
    frame,
    dirty: Path,
    output: Path,
    agent_api,
    config_list: list[dict],
    *,
    extra_requirement: str = "",
):
    """Execute the original coroutine with supplied transport and execution classes.

    This loader is not a benchmark launcher. The caller owns durable API receipts,
    isolated code execution, dependency pinning and output coordinate validation.
    """
    namespace = load_workflow(agent_api)
    native_config = namespace["LLM_CONFIG"]
    native_config["config_list"] = config_list
    namespace.update(
        df=frame,
        upload_path=str(dirty),
        CLEANED_DATA_STROAGE_DIR=str(output),
        CONFIG_LIST=config_list,
    )
    message = namespace["PROBLEM"].format(
        path=dirty, candidate_column_types=namespace["CANDIDATE_COLUMN_TYPES"]
    )
    extra = ""
    if extra_requirement:
        extra = namespace["EXTRA_REQUIREMENT"].format(extra_requirement=extra_requirement)
        message += extra
    # Upstream's is_test only suppresses the Chainlit message-display callback.
    return await namespace["start_chat"](
        message,
        is_test=True,
        have_extra_requirement=bool(extra_requirement),
        extra_require=extra,
    )
