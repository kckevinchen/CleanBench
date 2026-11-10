"""Project the published KATARA KB onto dirty-table values once per fresh run."""

from collections import defaultdict

from baselines.common import NATIVE_ROOT, atomic_json, read_table
from baselines.native.katara import native


def prepare(inputs, datasets, output):
    index = defaultdict(set)
    for dataset in datasets:
        _, rows = read_table(inputs / dataset / "dirty.csv")
        for value in {v.lower() for row in rows for v in row}:
            index[value].add(dataset)
    projections = {dataset: [] for dataset in datasets}
    files = sorted((NATIVE_ROOT / "external/katara/knowledge-base").rglob("*.txt"))
    if not files:
        raise ValueError("KATARA knowledge base is missing")
    mod = native()
    for number, path in enumerate(files):
        domain, relations = set(), {}
        with path.open() as stream:
            mod.load_file(stream, domain, relations)
        active = defaultdict(set)
        for subject in domain:
            for dataset in index.get(subject.lower(), ()):
                active[dataset].add(subject)
        for dataset, subjects in active.items():
            restricted = {
                relation: {s: o for s, o in pairs.items() if s in subjects}
                for relation, pairs in relations.items()
            }
            projections[dataset].append(
                dict(
                    file=path.name,
                    types=sorted(subjects),
                    relations={r: pairs for r, pairs in restricted.items() if pairs},
                )
            )
        if number % 100 == 0:
            print(f"KATARA KB projection: {number}/{len(files)}", flush=True)
    for dataset, projected in projections.items():
        atomic_json(output / "kb_projection" / (dataset + ".json"), projected)
