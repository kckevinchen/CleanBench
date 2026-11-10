from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import yaml

from baselines.common import atomic_json, read_json, read_table

from .execution import IsolatedExecution
from .transport import NativeClient
from .workflow import run_workflow

REVISION = "cleanagent_runtime_repair_v1"


def identity_column(columns):
    name = "__cleanagent_row_id__"
    while name in columns:
        name += "_"
    return name


def validate_output(dirty, directory, *, locations=None):
    columns, before = read_table(dirty)
    identity = identity_column(columns)
    cleaned = directory / "cleaned_data.csv"
    declared = directory / "cleaned_columns.json"
    if any(not p.is_file() or p.is_symlink() for p in (cleaned, declared)):
        raise ValueError("Save regular cleaned_data.csv and cleaned_columns.json files")
    header, after = read_table(cleaned)
    if header != columns + [identity]:
        raise ValueError(
            "Output must contain the original columns, in order, followed by the row identity"
        )
    if len(after) != len(before) or [r[-1] for r in after] != [str(i) for i in range(len(before))]:
        raise ValueError("Row count/order/identity changed; preserve every original row")
    cleaned_columns = read_json(declared)
    if (
        not isinstance(cleaned_columns, list)
        or any(not isinstance(c, str) or c not in columns for c in cleaned_columns)
        or len(cleaned_columns) != len(set(cleaned_columns))
    ):
        raise ValueError("cleaned_columns.json must list unique original column names")
    changes = []
    for i, row in enumerate(before):
        for j, value in enumerate(row):
            if after[i][j] != value:
                if columns[j] not in cleaned_columns:
                    raise ValueError(
                        f"Unintended string change outside declared cleaning column: {columns[j]}"
                    )
                changes.append({"row": i, "col": j, "corrected_value": after[i][j]})
    if locations is not None:
        raise ValueError("Known-location repair is outside this runner")
    return {"changes": changes, "cleaned_columns": cleaned_columns, "identity_column": identity}


def execute(dirty, directory, recipe, *, chat=None, locations=None):
    import autogen
    import dataprep.clean as cleaners
    import pandas as pd

    if recipe["revision"] != REVISION:
        raise ValueError("Unknown CleanAgent revision")
    dirty = dirty.resolve()
    directory = directory.resolve()
    code = directory / "code"
    code.mkdir(parents=True, exist_ok=False)
    columns, rows = read_table(dirty)
    frame = pd.DataFrame(rows, columns=columns)
    prompts = yaml.safe_load(Path(recipe["prompt_file"]).read_text())
    if chat is None:
        raise ValueError("An API transport is required")
    execution = IsolatedExecution(dirty, code, recipe["execution_limits"])
    context = (
        "\nActual original schema: "
        + json.dumps(columns, ensure_ascii=False)
        + "\nIdentity column: "
        + json.dumps(identity_column(columns))
        + "\nFirst five dirty rows:\n"
        + frame.head().to_markdown()
        + "\nInstalled DataPrep signatures:\n"
        + "\n".join(
            name + str(inspect.signature(getattr(cleaners, name)))
            for name in (
                "clean_email",
                "clean_phone",
                "clean_date",
                "clean_country",
                "clean_ip",
                "clean_df",
            )
        )
    )
    extra = ""
    if locations is not None:
        raise ValueError("This package runs end-to-end inference without supplied locations")
    state = {"validated": False, "programmer_turns": 0, "attempts": [], "manager": None}

    class Assistant(autogen.AssistantAgent):
        def __init__(self, **kwargs):
            is_coder = kwargs["name"] == "Python_Programmer"
            kwargs["system_message"] += "\n" + prompts["coder" if is_coder else "annotator"]
            if is_coder:
                kwargs["system_message"] += context
            kwargs["is_termination_msg"] = lambda message: False
            super().__init__(**kwargs)
            self.register_model_client(model_client_cls=NativeClient, chat=chat)

        def generate_reply(self, *args, **kwargs):
            if self.name == "Python_Programmer":
                state["programmer_turns"] += 1
                if state["programmer_turns"] > recipe["max_programmer_turns"]:
                    raise RuntimeError("Bounded CleanAgent recovery exhausted without valid output")
            return super().generate_reply(*args, **kwargs)

    class Manager(autogen.GroupChatManager):
        def __init__(self, **kwargs):
            kwargs["is_termination_msg"] = lambda message: state["validated"]
            super().__init__(**kwargs)
            self.register_model_client(model_client_cls=NativeClient, chat=chat)
            state["manager"] = self

    class Group(autogen.GroupChat):
        def __init__(self, **kwargs):
            def next_speaker(last, group):
                agents = {a.name: a for a in group.agents}
                if last.name == "User_Proxy":
                    return agents["Column_Type_Annotator"]
                if last.name == "Python_Programmer":
                    return agents["Code_Executor"]
                return agents["Python_Programmer"]

            kwargs["speaker_selection_method"] = next_speaker
            super().__init__(**kwargs)

    cwd = Path.cwd()
    try:
        os.chdir(directory)
        with execution.install(autogen) as isolated_proxy:

            class Proxy(isolated_proxy):
                def __init__(self, **kwargs):
                    kwargs["is_termination_msg"] = lambda message: False
                    if kwargs["name"] == "Code_Executor":
                        kwargs["code_execution_config"]["last_n_messages"] = 1
                        kwargs["default_auto_reply"] = prompts["executor_no_code"]
                    super().__init__(**kwargs)

                def execute_code_blocks(self, blocks):
                    index = len(state["attempts"]) + 1
                    attempt = directory / "attempts" / str(index)
                    attempt.mkdir(parents=True)
                    for name in ("cleaned_data.csv", "cleaned_columns.json"):
                        p = code / name
                        if p.exists() or p.is_symlink():
                            p.unlink()
                    exitcode, logs = super().execute_code_blocks(blocks)
                    check = {"index": index, "exitcode": exitcode, "valid": False}
                    for name in ("cleaned_data.csv", "cleaned_columns.json"):
                        p = code / name
                        if p.is_file() and not p.is_symlink():
                            shutil.copyfile(p, attempt / name)
                    if exitcode == 0:
                        try:
                            result = validate_output(dirty, code, locations=locations)
                            state.update(validated=True, result=result)
                            check["valid"] = True
                            logs += "\nCleanAgent output validation succeeded."
                        except (ValueError, json.JSONDecodeError) as exc:
                            exitcode = 1
                            check["validation_error"] = str(exc)
                            logs += "\nOUTPUT VALIDATION FAILED: " + str(exc)
                    state["attempts"].append(check)
                    atomic_json(attempt / "validation.json", check)
                    return exitcode, logs

            api = SimpleNamespace(
                AssistantAgent=Assistant,
                UserProxyAgent=Proxy,
                GroupChat=Group,
                GroupChatManager=Manager,
                ConversableAgent=autogen.ConversableAgent,
            )
            with (
                (directory / "native.log").open("w") as log,
                contextlib.redirect_stdout(log),
                contextlib.redirect_stderr(log),
            ):
                asyncio.run(
                    run_workflow(
                        frame,
                        Path("/input/dirty.csv"),
                        code,
                        api,
                        [{"model": recipe["model"], "model_client_cls": "NativeClient"}],
                        extra_requirement=extra,
                    )
                )
        if not state["validated"]:
            raise RuntimeError("CleanAgent ended without a validated output")
        return {
            **state["result"],
            "revision": REVISION,
            "labeled_rows": [],
            "programmer_turns": state["programmer_turns"],
            "attempts": state["attempts"],
            "native_code_executions": execution.calls,
            "new_api_calls": chat.calls - chat.reused,
            "usage": {"input_tokens": chat.input_tokens, "output_tokens": chat.output_tokens},
        }
    finally:
        os.chdir(cwd)
        if state["manager"] is not None:
            atomic_json(directory / "conversation.json", state["manager"].groupchat.messages)
        atomic_json(
            directory / "execution_audit.json",
            {
                "revision": REVISION,
                "validated": state["validated"],
                "programmer_turns": state["programmer_turns"],
                "attempts": state["attempts"],
            },
        )
