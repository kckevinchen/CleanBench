"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

UPSTREAM = Path(__file__).resolve().parent / "cocoon_repo"


def load_upstream(chat):
    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))
    import cocoon_data
    import cocoon_data.config as config
    import cocoon_data.llm as llm

    config.cocoon_main_setting["allow_cache"] = False
    # Errors must reach the supervisor instead of reverting a failed SQL step silently.
    config.cocoon_main_setting["DEBUG_MODE"] = True
    llm.call_llm_chat = chat
    cocoon_data.call_llm_chat = chat
    return cocoon_data


def clean_table(frame, chat) -> tuple[object, dict]:
    import duckdb

    cocoon = load_upstream(chat)
    with duckdb.connect(":memory:") as connection:
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=true")
        connection.register("input_frame", frame)
        connection.execute('CREATE TABLE "source_table" AS SELECT * FROM input_frame')
        step = cocoon.SQLStep("source_table", connection, materialized=True)
        pipeline = cocoon.TransformationSQLPipeline([step], {})
        if list(pipeline.get_schema(connection)) != list(frame.columns):
            raise ValueError("SQL engine changed the source column identities")
        table = cocoon.Table(table_name="source_table", columns=list(frame.columns))
        item = {"con": connection}
        parameters = {"table_pipeline": pipeline, "table_object": table}
        decide_all = cocoon.DecideStringUnusualForAll(item=item, para=parameters.copy())
        cleaned, decisions = {}, {}
        # Notebook display is omitted; extraction, prompts, parsing and SQL are native.
        with contextlib.redirect_stdout(io.StringIO()):
            decide_all.extract(item)
            for column in decide_all.elements:
                node = decide_all.nodes[column]
                decision = node.run(node.extract(item), use_cache=False)
                decisions[column] = decision
            clean_all = cocoon.CleanUnusualForAll(item=item, para=parameters.copy())
            # This is exactly the document consumed by CleanUnusualForAll.extract.
            clean_all.get_sibling_document = lambda name: {"Decide String Unusual": decisions}
            clean_all.extract(item)
            for column in clean_all.elements:
                node = clean_all.nodes[column]
                batches = node.extract(item)
                outputs = [node.run(batch, use_cache=False) for batch in batches]
                cleaned[column] = node.merge_run_output(outputs)
            clean_all.display_after_finish_workflow(
                lambda document: None, {"Clean Unusual": cleaned}
            )
        result = connection.execute(f"SELECT * FROM {pipeline}").fetchdf().fillna("")
        if result.shape != frame.shape or list(result.columns) != list(frame.columns):
            raise ValueError("Native cleaning changed row or column coordinates")
        return result.astype(str), {"decisions": decisions, "cleaning": cleaned}
