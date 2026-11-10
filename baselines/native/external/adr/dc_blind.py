import hashlib

from baselines.common import read_json

from .dc_correction import grid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_detection(dirty, work):
    stage = read_json(work / "native_detection.json", {})
    header, rows = grid(dirty)
    if stage.get("status") != "complete" or stage.get("dirty_sha256") != sha(dirty):
        raise ValueError("No completed native detection with matching source")
    cells = stage["cells"]
    if any(
        not isinstance(c, list)
        or len(c) != 2
        or any(type(v) is not int for v in c)
        or not (0 <= c[0] < len(rows) and 0 <= c[1] < len(header))
        for c in cells
    ) or len({tuple(c) for c in cells}) != len(cells):
        raise ValueError("Invalid native detected-cell coordinates")
    return [{"row": row, "col": col} for row, col in cells]
