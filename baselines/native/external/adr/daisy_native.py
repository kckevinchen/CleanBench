"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import contextlib
import csv
import hashlib
import sys
import time
import types

from baselines.common import atomic_json

from .native_correction import UPSTREAM

SOURCE_DIR = UPSTREAM / "Daisy/daisy"


MODULES = ("constraint", "dataset", "SPJ", "queryOperate", "cleanOperate")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextlib.contextmanager
def load_core():
    """Load the five unchanged generic modules without absent example packages."""
    names = ["daisy"] + ["daisy." + n for n in MODULES]
    previous = {name: sys.modules.get(name) for name in names}
    package = types.ModuleType("daisy")
    package.__path__ = [str(SOURCE_DIR)]
    sys.modules["daisy"] = package
    try:
        for name in MODULES:
            path = SOURCE_DIR / (name + ".py")
            module = types.ModuleType("daisy." + name)
            module.__file__ = str(path)
            sys.modules[module.__name__] = module
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), vars(module))
            # Equivalent to the generic wildcard imports in the released init.
            for key, value in vars(module).items():
                if not key.startswith("_"):
                    setattr(package, key, value)
        yield package
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def translated_rules(header, rules):
    aliases = {column: "C%d" % i for i, column in enumerate(header)}
    result = []
    for rule in rules:
        lhs, rhs = rule["lhs"], rule["rhs"]
        if not isinstance(lhs, list) or not lhs or any(c not in aliases for c in lhs + [rhs]):
            raise ValueError("Saved FD references an invalid source column")
        if len(set(lhs)) != len(lhs) or rhs in lhs:
            raise ValueError("Saved FD is redundant or contains duplicate determinants")
        predicates = ["EQ(t1.%s,t2.%s)" % (aliases[c], aliases[c]) for c in lhs]
        predicates.append("IQ(t1.%s,t2.%s)" % (aliases[rhs], aliases[rhs]))
        result.append(
            {
                "text": "t1&t2&" + "&".join(predicates),
                "schema": [aliases[c] for c in lhs + [rhs]],
                "source_columns": [header.index(c) for c in lhs + [rhs]],
            }
        )
    return result


def execute(dirty, rules, work):
    with dirty.open(newline="", encoding="utf-8") as stream:
        header, *rows = csv.reader(stream)
    if not rows or len(set(header)) != len(header) or any(len(r) != len(header) for r in rows):
        raise ValueError("Expected nonempty rectangular source and unique headers")
    plans = translated_rules(header, rules)
    if not plans:
        return {
            "cells": [],
            "rules_completed": 0,
            "violation_pairs": 0,
            "parser_normalized_cells": 0,
            "abstention": "no dirty-mined FD rules",
        }
    work.mkdir(parents=True, exist_ok=False)
    native_dirty = work / "dirty.csv"
    aliases = ["C%d" % j for j in range(len(header))]
    with native_dirty.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows([aliases] + rows)
    atomic_json(work / "columns.json", header)
    atomic_json(work / "rules.json", plans)
    atomic_json(work / "execution.json", {"started_at": time.time()})
    detected, total_pairs = set(), 0
    with load_core() as native:
        dataset = native.dataset(str(native_dirty))
        if list(dataset.df.columns) != ["index"] + aliases or len(dataset.df) != len(rows):
            raise ValueError("Native parser changed source coordinates")
        before = dataset.df.copy(deep=True)
        parsed = before.iloc[:, 1:].values.tolist()
        atomic_json(work / "native_input.json", parsed)
        normalized = sum(a != b for source, row in zip(rows, parsed) for a, b in zip(source, row))
        # The release's example DC schemas enumerate participating attributes.
        # Preserve that API contract and select every source row for this benchmark.
        select = native.Select(list(dataset.df.columns), "dirty", ["index", ">=", 0])
        code = native.CleanSigma.fix_tuple_pair.__code__
        for index, plan in enumerate(plans):
            dc = native.DCRule(plan["text"], plan["schema"])
            expected = [("=", [c, c]) for c in plan["schema"][:-1]] + [
                ("<>", [plan["schema"][-1]] * 2)
            ]
            if [(p.opt, p.components) for p in dc.predicates] != expected:
                raise ValueError("Native DC parser changed the intended rule")
            pairs = set()

            def observe(frame, event, arg):
                if (
                    event == "return"
                    and frame.f_code is code
                    and frame.f_locals.get("err_sig") is True
                ):
                    local = frame.f_locals
                    first, second = int(local["fst_tup"]["index"]), int(local["sec_tup"]["index"])
                    if not (0 <= first < len(rows) and 0 <= second < len(rows)):
                        raise ValueError("Native violation uses invalid source rows")
                    pairs.add((first, second))

            previous = sys.getprofile()
            try:
                sys.setprofile(observe)
                answer = native.do_select(dataset, select)
                sigma = native.CleanSigma(dataset, answer, dc=dc)
            finally:
                sys.setprofile(previous)
            candidates = []
            for row in sigma.relax_full.values():
                source_row = int(row["index"])
                if source_row != int(row.name) or not 0 <= source_row < len(rows):
                    raise ValueError("Native candidate changed source identity")
                domains = {str(j): row[aliases[j]] for j in plan["source_columns"]}
                candidates.append({"row": source_row, "domains": domains})
            if len(candidates) != len(rows) or len({c["row"] for c in candidates}) != len(rows):
                raise ValueError("Native candidates lost or duplicated source rows")
            cells = sorted({(i, j) for pair in pairs for i in pair for j in plan["source_columns"]})
            atomic_json(
                work / "rules" / ("%03d.json" % index),
                {
                    "status": "complete",
                    "rule": plan,
                    "violation_pairs": sorted(pairs),
                    "detected_cells": cells,
                    "probabilistic_candidates": candidates,
                },
            )
            detected.update(cells)
            total_pairs += len(pairs)
            if not dataset.df.equals(before):
                raise ValueError("Native DC detection changed the source frame")
            atomic_json(
                work / "progress.json",
                {
                    "rules_completed": index + 1,
                    "rules_total": len(plans),
                    "detections": len(detected),
                    "violation_pairs": total_pairs,
                },
            )
    return {
        "cells": sorted(detected),
        "rules_completed": len(plans),
        "violation_pairs": total_pairs,
        "parser_normalized_cells": normalized,
    }
