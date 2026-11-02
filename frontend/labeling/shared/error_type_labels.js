// Display names do not change the historical detector keys used by the API.
const TYPE_NAMES = {
  spelling: "Spelling",
  "typo-spelling": "Spelling",
  formatting: "Formatting",
  "typo-formatting": "Formatting",
  inconsistency: "Inconsistency",
  semantic_incompatible: "Inconsistency",
  numeric_outlier: "Inconsistency",
  fd_violation: "Inconsistency",
  row_calculation_inconsistency: "Inconsistency",
  string_calculation_inconsistency: "Inconsistency",
  row_duplication: "Inconsistency",
  inter_table_inconsistency: "Inconsistency",
};

export function displayErrorType(type, explanation = "") {
  const key = String(type || "").trim().toLowerCase();
  if (key === "typo") {
    const subtype = /^\s*typo[:\-](spelling|formatting|whitespace|punctuation)\b/i
      .exec(String(explanation || ""))?.[1]?.toLowerCase();
    if (subtype === "spelling") return "Spelling";
    if (subtype) return "Formatting";
    // Older typo records can cover either type; do not guess without a subtype.
    return "Spelling / Formatting";
  }
  return TYPE_NAMES[key] || String(type || "");
}

export function displayExplanation(explanation) {
  return String(explanation || "").replace(
    /^\s*typo[:\-](?:spelling|formatting|whitespace|punctuation)\s*[-–—:]\s*/i,
    "",
  );
}

export function displayClusterTypes(cluster) {
  const names = [];
  for (const type of cluster.error_types || []) {
    const detections = (cluster.detections || []).filter(
      (d) => d.error_type === type,
    );
    if (detections.length) {
      names.push(...detections.map((d) => displayErrorType(type, d.explanation)));
    } else {
      names.push(displayErrorType(type));
    }
  }
  return [...new Set(names)];
}
