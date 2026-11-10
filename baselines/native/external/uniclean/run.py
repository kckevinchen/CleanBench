"""Published CleanBench inference bridge; see baselines/provenance.json."""

import os
import sys
from pathlib import Path


def execute(request):
    import pandas as pd
    from pyspark.sql import SparkSession
    from pyspark.sql.types import StringType, StructField, StructType

    source = Path(request["project"]) / "external/uniclean/upstream/uniclean_cleaners"
    sys.path.insert(0, str(source))
    os.environ["MPLBACKEND"] = "Agg"
    import AnalyticsCache.get_planuml_graph as graph

    # Disable only optional network-based graph rendering, not cleaner decisions.
    graph.PlantUML.process_str = lambda *args, **kwargs: None
    graph.PlantUML.process_file = lambda *args, **kwargs: None
    from Clean import CleanonLocalWithnoSmple
    from SampleScrubber.cleaner.multiple import AttrRelation

    dirty = pd.read_csv(request["dirty_csv"], dtype=str, keep_default_na=False, na_filter=False)
    columns = ["C" + str(i) for i in range(len(dirty.columns))]
    rows = dirty.values.tolist()
    schema = StructType([StructField(c, StringType(), False) for c in ["index", *columns]])
    spark = (
        SparkSession.builder.master("local[1]")
        .appName("UniClean-benchmark")
        .config("spark.driver.memory", "2g")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    try:
        data = spark.createDataFrame([[str(i), *row] for i, row in enumerate(rows)], schema)
        cleaners = [
            AttrRelation(fd["lhs"], [fd["rhs"]], str(i)) for i, fd in enumerate(request["fds"])
        ]
        result = CleanonLocalWithnoSmple(spark, cleaners, data, request["work"], single_max=10000)
        output = result.select("index", *columns).collect()
        by_id = {}
        for record in output:
            i = int(record["index"])
            if i in by_id or not 0 <= i < len(rows):
                raise ValueError("UniClean changed row identity")
            by_id[i] = [record[c] for c in columns]
        if set(by_id) != set(range(len(rows))):
            raise ValueError("UniClean changed row coverage")
        if any(not isinstance(v, str) for row in by_id.values() for v in row):
            raise ValueError("UniClean emitted non-string/null output")
        changes = [
            {"row": i, "col": j, "corrected_value": v}
            for i, row in by_id.items()
            for j, v in enumerate(row)
            if v != rows[i][j]
        ]
        return {
            "changes": changes,
            "detections": [{"row": c["row"], "col": c["col"]} for c in changes],
            "detection_semantics": "locations of concrete native changes",
        }
    finally:
        spark.stop()
