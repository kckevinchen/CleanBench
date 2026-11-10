"""Published CleanBench inference bridge; see baselines/provenance.json."""

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def scenario(rows, fds, work):
    columns = ["rid"] + ["C" + str(j) for j in range(len(rows[0]))]
    ns = "{http://www.w3.org/2001/XMLSchema}"
    ET.register_namespace("xs", ns[1:-1])
    schema = ET.Element(ns + "schema")
    database = ET.SubElement(schema, ns + "element", name="database")
    seq = ET.SubElement(ET.SubElement(database, ns + "complexType"), ns + "sequence")
    container = ET.SubElement(seq, ns + "element", name="records")
    seq = ET.SubElement(ET.SubElement(container, ns + "complexType"), ns + "sequence")
    record = ET.SubElement(seq, ns + "element", name="T", minOccurs="1", maxOccurs="unbounded")
    fields = ET.SubElement(ET.SubElement(record, ns + "complexType"), ns + "sequence")
    for c in columns:
        ET.SubElement(fields, ns + "element", name=c, type="xs:string")
    ET.ElementTree(schema).write(work / "input.xsd", encoding="utf-8", xml_declaration=True)
    data = ET.Element("database")
    container = ET.SubElement(data, "records")
    for i, row in enumerate(rows):
        t = ET.SubElement(container, "T")
        for c, value in zip(columns, [str(i), *row]):
            ET.SubElement(t, c).text = value
    ET.ElementTree(data).write(work / "input.xml", encoding="utf-8", xml_declaration=True)
    document = ET.Element("scenario")
    target = ET.SubElement(document, "target")
    ET.SubElement(target, "type").text = "XML"
    xml = ET.SubElement(target, "xml")
    ET.SubElement(xml, "xml-schema").text = "input.xsd"
    ET.SubElement(xml, "xml-instance").text = "input.xml"
    dependencies = []
    for n, fd in enumerate(fds):
        atoms = []
        for side in ("a", "b"):
            attrs = [f"{c}: $v{c}" + ("" if c in fd["lhs"] else side) for c in columns]
            atoms.append("records(" + ", ".join(attrs) + ")")
        dependencies.append(
            f"fd{n}: " + ", ".join(atoms) + f" -> $v{fd['rhs']}a == $v{fd['rhs']}b."
        )
    ET.SubElement(document, "dependencies").text = "ExtEGDs:\n" + "\n".join(dependencies)
    # Published automatic greedy configuration; no human manager or ground truth.
    ET.SubElement(ET.SubElement(document, "partialOrder"), "type").text = "Greedy"
    manager = ET.SubElement(document, "costManager")
    for key, value in [("type", "Greedy"), ("doPermutations", "false"), ("doBackward", "false")]:
        ET.SubElement(manager, key).text = value
    path = work / "scenario.xml"
    ET.ElementTree(document).write(path, encoding="utf-8", xml_declaration=True)
    return path


def decode(records, rows):
    result, unresolved = {}, []
    for record in records:
        i = int(record["rid"]["value"])
        if i in result or not 0 <= i < len(rows):
            raise ValueError("Native engine changed row identity")
        values = []
        for j in range(len(rows[i])):
            cell = record["C" + str(j)]
            if cell["type"].lower() != "constant":
                unresolved.append({"row": i, "col": j, **cell})
                values.append(None)
            else:
                values.append(cell["value"])
        result[i] = values
    if set(result) != set(range(len(rows))):
        raise ValueError("Native engine inserted/deleted rows")
    return [result[i] for i in range(len(rows))], unresolved


def execute(request, rows, work):
    root = Path(request["project"])
    path = scenario(rows, request["fds"], work)
    output = work / "native.json"
    raw = work / "raw_strings.json"
    raw.write_text(json.dumps(rows, ensure_ascii=False))
    classpath = (
        str(root / "external/llunatic/build") + ":" + str(root / "external/llunatic/upstream/lib/*")
    )
    command = [
        str(root / "external/nadeef/mamba_env/bin/java"),
        "-Xmx2g",
        "-cp",
        classpath,
        "NativeBridge",
        str(path),
        str(output),
        str(raw),
    ]
    with (work / "native.log").open("w") as log:
        subprocess.run(
            command, cwd=work, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=280
        )
    native = json.loads(output.read_text())
    before, unknown = decode(native["before"], rows)
    if before != rows or unknown:
        raise ValueError("Native XML loader changed raw strings")
    if not native["solutions"]:
        return {"changes": [], "detections": [], "unresolved": "no concrete native solution"}
    after, unresolved = decode(native["after"], rows)
    changes = [
        {"row": i, "col": j, "corrected_value": v}
        for i, row in enumerate(after)
        for j, v in enumerate(row)
        if v is not None and v != rows[i][j]
    ]
    return {
        "changes": changes,
        "detections": [{"row": c["row"], "col": c["col"]} for c in changes],
        "unresolved": unresolved,
        "solution_score": native["score"],
        "solutions": native["solutions"],
        "detection_semantics": "locations of concrete native changes",
    }
