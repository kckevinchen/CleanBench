import { api, escapeHtml } from "./shared/utils.js";

export function setupExportConflictGuard({ apiBase, notify, onJump }) {
  const API = apiBase;
  const toast = notify;
  const jumpToCell = onJump;
  const escape = escapeHtml;
  const escapeAttr = escapeHtml;

  let _pendingExport = null;

  function bindExportLinks() {
    const wires = [
      "#export-bundle-link",
      "#export-link",
      "#export-by-type-link",
      "#export-single-link",
    ];
    for (const sel of wires) {
      const a = document.querySelector(sel);
      if (!a) continue;
      // ``capture: true`` so we run before any default navigation
      // bookkeeping the browser would otherwise kick off.
      a.addEventListener("click", (ev) => onExportClick(ev, a), { capture: true });
    }
    const modal = document.getElementById("export-conflicts-modal");
    if (!modal) return;
    for (const el of modal.querySelectorAll("[data-modal-close]")) {
      el.addEventListener("click", () => closeExportConflictsModal());
    }
    window.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (modal.hidden) return;
      closeExportConflictsModal();
    });
  }

  async function onExportClick(ev, anchor) {
    // The per-type single-link uses aria-disabled=true as a sentinel
    // when no type is picked yet; let that be a no-op.
    if (anchor.getAttribute("aria-disabled") === "true") {
      ev.preventDefault();
      return;
    }
    const href = anchor.href;
    if (!href || href.endsWith("#")) {
      ev.preventDefault();
      return;
    }
    ev.preventDefault();
    let groups = [];
    try {
      const r = await api(`${API}/export/conflicts`);
      groups = (r && r.conflicts) || [];
    } catch (e) {
      toast(`Could not check labels before export: ${e.message || e}`, 3000);
      return;
    }
    if (groups.length === 0) {
      triggerExportDownload(href, anchor.getAttribute("download"));
      return;
    }
    _pendingExport = { href, download: anchor.getAttribute("download") || "" };
    openExportConflictsModal(groups);
  }

  function triggerExportDownload(href, downloadAttr) {
    // Use a transient anchor so the browser honours the
    // ``Content-Disposition: attachment`` set by the server. Setting
    // ``window.location.href`` would navigate the SPA away.
    const a = document.createElement("a");
    a.href = href;
    if (downloadAttr) a.download = downloadAttr;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function openExportConflictsModal(conflicts) {
    const modal = document.getElementById("export-conflicts-modal");
    if (!modal) return;
    renderExportConflictsModal(conflicts);
    modal.hidden = false;
  }

  function closeExportConflictsModal() {
    const modal = document.getElementById("export-conflicts-modal");
    if (!modal) return;
    modal.hidden = true;
    _pendingExport = null;
  }

  function renderExportConflictsModal(conflicts) {
    const body = document.getElementById("export-conflicts-body");
    if (!body) return;
    const totalCells = conflicts.reduce((n, g) => n + (g.cells || []).length, 0);
    const groupsHtml = conflicts
      .map((g) => {
        const cellsHtml = (g.cells || [])
          .map((c) => {
            const lab = String(c.label || "");
            const labelClass = `label-${escapeAttr(lab)}`;
            const corrStr =
              c.corrected_value == null ? "" : String(c.corrected_value);
            return (
              `<div class="export-conflict-cell">` +
              `<span class="row-label">row ${Number(c.row)}</span>` +
              `<span class="label-pill ${labelClass}">${escape(lab)}</span>` +
              `<span class="corrected" title="${escapeAttr(corrStr)}">${escape(corrStr)}</span>` +
              `<button type="button" class="jump-btn"` +
              ` data-source="${escapeAttr(g.source || "")}"` +
              ` data-row="${Number(c.row)}"` +
              ` data-column="${escapeAttr(g.column || "")}">Jump</button>` +
              `</div>`
            );
          })
          .join("");
        const labelsLabel = (g.labels || [])
          .map((l) => `<code>${escape(String(l))}</code>`)
          .join(", ");
        return (
          `<div class="export-conflict-group">` +
          `<div class="export-conflict-head">` +
          `<span class="source">${escape(g.source || "")}</span>` +
          `<span class="column">· ${escape(g.column || "")}</span>` +
          `<span class="value" title="${escapeAttr(g.original_value || "")}">${escape(g.original_value || "")}</span>` +
          `<span class="muted">· labels: ${labelsLabel}</span>` +
          `</div>` +
          `<div class="export-conflict-cells">${cellsHtml}</div>` +
          `</div>`
        );
      })
      .join("");
    body.innerHTML =
      `<div class="export-conflict-summary danger">` +
      `Found <b>${conflicts.length}</b> value(s) across <b>${totalCells}</b> cell(s)` +
      ` whose verdicts disagree row-to-row. Click <b>Jump</b> to revise a cell,` +
      ` or <b>Export anyway</b> to download the JSONL as-is.` +
      `</div>` +
      `<div class="export-conflict-list">${groupsHtml}</div>`;
    for (const btn of body.querySelectorAll(".jump-btn")) {
      btn.addEventListener("click", () => {
        const src = btn.dataset.source || "";
        const row = Number.parseInt(btn.dataset.row, 10);
        const col = btn.dataset.column || "";
        if (!src || !Number.isInteger(row)) return;
        closeExportConflictsModal();
        jumpToCell(src, row, col);
      });
    }
    // Re-bind on every render so the listener doesn't pile up.
    const anyway = document.getElementById("export-conflicts-anyway");
    if (anyway) {
      anyway.onclick = () => {
        const pending = _pendingExport;
        closeExportConflictsModal();
        if (pending && pending.href) {
          triggerExportDownload(pending.href, pending.download);
        }
      };
    }
  }

  bindExportLinks();
}
