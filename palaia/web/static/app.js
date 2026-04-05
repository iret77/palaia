// palaia WebUI — local memory explorer
// Vanilla JS, no build step. Uses event delegation instead of inline onclick.
//
// v2.6 UX:
// - Manual entries highlighted with a boost badge (1.3x recall weight)
// - Tasks are post-its: completing deletes the entry
// - Doctor health banner shows actionable issues

(() => {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    entries: [],
    searchMode: false,
    currentEntryId: null,
    currentEntryData: null,
    filters: { type: "", source: "", scope: "", tier: "", project: "", agent: "", status: "" },
  };

  // ── DOM helpers ──────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  function esc(s) {
    if (s == null) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function el(tag, attrs = {}, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "dataset") Object.assign(n.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
    }
    for (const c of children) {
      if (c == null || c === false) continue;
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return n;
  }

  // ── API client ───────────────────────────────────────────────────────────
  async function api(path, opts) {
    const resp = await fetch(path, opts);
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const body = await resp.json();
        detail = body.error || JSON.stringify(body);
      } catch (_) { /* ignore */ }
      throw new Error(`${resp.status}: ${detail}`);
    }
    if (resp.status === 204) return null;
    return resp.json();
  }
  const apiGet = (p) => api(p);
  const apiPost = (p, d) => api(p, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(d),
  });
  const apiPatch = (p, d) => api(p, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(d),
  });
  const apiDelete = (p) => api(p, { method: "DELETE" });

  // ── Toast ────────────────────────────────────────────────────────────────
  function toast(msg, kind = "info") {
    const t = $("toast");
    t.textContent = msg;
    t.className = `toast toast-${kind} toast-visible`;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { t.className = "toast"; }, 3000);
  }

  // ── Date formatting ──────────────────────────────────────────────────────
  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch { return iso; }
  }

  // ── Initial loads ────────────────────────────────────────────────────────
  async function loadStatus() {
    try {
      const d = await apiGet("/api/status");
      $("stat-total").textContent = d.total + " entries";
      $("stat-version").textContent = "v" + d.version;
    } catch (e) { /* non-fatal */ }
  }

  async function loadProjects() {
    try {
      const d = await apiGet("/api/projects");
      const sel = $("filter-project");
      for (const name of Object.keys(d.projects || {})) {
        sel.appendChild(el("option", { value: name }, name));
      }
    } catch (e) { /* non-fatal */ }
  }

  async function loadAgents() {
    try {
      const d = await apiGet("/api/agents");
      const sel = $("filter-agent");
      for (const name of d.agents || []) {
        sel.appendChild(el("option", { value: name }, name));
      }
    } catch (e) { /* non-fatal */ }
  }

  async function loadDoctor() {
    try {
      const d = await apiGet("/api/doctor");
      const pill = $("health-pill");
      const label = $("health-label");
      const counts = d.counts || {};
      const warn = counts.warn || 0;
      const err = counts.error || 0;

      pill.hidden = false;
      if (err > 0) {
        pill.className = "health-pill health-error";
        label.textContent = `${err + warn} issues`;
      } else if (warn > 0) {
        pill.className = "health-pill health-warn";
        label.textContent = `${warn} warning${warn > 1 ? "s" : ""}`;
      } else {
        pill.className = "health-pill health-ok";
        label.textContent = "healthy";
      }

      // Auto-show banner only when there are warn/error items
      if (d.has_issues) {
        renderDoctorList(d.checks);
        $("doctor-banner").hidden = false;
      } else {
        $("doctor-banner").hidden = true;
      }
    } catch (e) { /* non-fatal */ }
  }

  function renderDoctorList(checks) {
    const list = $("doctor-list");
    list.innerHTML = "";
    for (const c of checks || []) {
      const status = c.status === "warning" ? "warn" : c.status;
      if (status !== "warn" && status !== "error") continue;
      const li = el("li", { class: `doctor-item doctor-${status}` },
        el("span", { class: "doctor-label" }, c.label || c.name || ""),
        el("span", { class: "doctor-msg" }, c.message || ""),
      );
      if (c.fix) li.appendChild(el("code", { class: "doctor-fix" }, c.fix));
      list.appendChild(li);
    }
  }

  // ── Entry list ───────────────────────────────────────────────────────────
  async function loadEntries() {
    const params = new URLSearchParams({ limit: "100" });
    for (const [key, val] of Object.entries(state.filters)) {
      if (val) params.set(key, val);
    }
    try {
      const d = await apiGet("/api/entries?" + params);
      state.entries = d.entries;
      renderEntries(d.entries, d.total, false);
    } catch (e) {
      $("entry-list").innerHTML = '<div class="loading">Error: ' + esc(e.message) + "</div>";
    }
  }

  async function doSearch() {
    const q = $("search-input").value.trim();
    if (!q) { clearSearch(); return; }
    const params = new URLSearchParams({ q, limit: "30" });
    if (state.filters.type) params.set("type", state.filters.type);
    if (state.filters.project) params.set("project", state.filters.project);
    if (state.filters.status) params.set("status", state.filters.status);

    $("entry-list").innerHTML = '<div class="loading">Searching…</div>';
    try {
      const d = await apiGet("/api/search?" + params);
      state.searchMode = true;
      const entries = (d.results || []).map((r) => ({
        id: r.id, title: r.title, type: r.type, scope: r.scope, tier: r.tier,
        tags: r.tags || [], project: r.project, status: r.status, priority: r.priority,
        decay_score: r.decay_score, body_preview: r.body || r.content,
        score: r.score, is_manual: r.is_manual, is_auto_capture: r.is_auto_capture,
        agent: r.agent,
      }));
      state.entries = entries;
      const extra = d.timed_out ? " (BM25 only)" : (d.bm25_only ? " (BM25)" : "");
      renderEntries(entries, d.count, true, extra);
    } catch (e) {
      $("entry-list").innerHTML = '<div class="loading">Search error: ' + esc(e.message) + "</div>";
    }
  }

  function clearSearch() {
    state.searchMode = false;
    closeDetail();
    loadEntries();
  }

  function applyFiltersThenReload() {
    for (const sel of $$("[data-filter]")) {
      state.filters[sel.dataset.filter] = sel.value;
    }
    if (state.searchMode) doSearch();
    else loadEntries();
  }

  function renderEntries(entries, total, isSearch, extra = "") {
    const list = $("entry-list");
    const count = $("result-count");

    if (!entries.length) {
      list.innerHTML = '<div class="loading">No entries found.</div>';
      count.textContent = "";
      return;
    }
    count.textContent = isSearch
      ? `${total} result${total !== 1 ? "s" : ""}${extra}`
      : `Showing ${entries.length} of ${total} entries`;

    list.innerHTML = "";
    for (const e of entries) {
      list.appendChild(renderEntryCard(e));
    }
  }

  function renderEntryCard(e) {
    const scoreText = e.score != null
      ? "score: " + Number(e.score).toFixed(3)
      : "decay: " + Number(e.decay_score || 0).toFixed(2);

    const card = el("div", {
      class: "entry-card" + (e.is_manual ? " is-manual" : " is-auto"),
      dataset: { id: e.id, action: "show-detail" },
    });

    // Header
    const header = el("div", { class: "entry-header" },
      el("span", { class: "entry-title" }, e.title || "(untitled)"),
      el("span", { class: "entry-score" }, scoreText),
    );
    card.appendChild(header);

    // Meta line
    const meta = el("div", { class: "entry-meta" });
    meta.appendChild(el("span", { class: "badge badge-tier badge-" + (e.tier || "hot") }, e.tier || "hot"));
    meta.appendChild(el("span", { class: "badge badge-type badge-" + (e.type || "memory") }, e.type || "memory"));
    meta.appendChild(el("span", { class: "badge badge-source " + (e.is_manual ? "badge-manual" : "badge-auto") },
      e.is_manual ? "manual ✦" : "auto"));
    if (e.priority) meta.appendChild(el("span", { class: "badge badge-priority-" + e.priority }, e.priority));
    if (e.status) meta.appendChild(el("span", { class: "badge badge-status" }, e.status));
    if (e.scope && e.scope !== "team") meta.appendChild(el("span", { class: "badge badge-scope" }, e.scope));
    if (e.project) meta.appendChild(el("span", { class: "badge badge-project" }, e.project));
    if (e.agent) meta.appendChild(el("span", { class: "badge badge-agent" }, "@" + e.agent));
    for (const tag of (e.tags || []).slice(0, 4)) {
      if (tag === "auto-capture") continue; // already shown via source badge
      meta.appendChild(el("span", { class: "tag" }, tag));
    }
    card.appendChild(meta);

    // Preview
    if (e.body_preview) {
      card.appendChild(el("div", { class: "entry-preview" }, e.body_preview));
    }
    return card;
  }

  // ── Detail (inline expand) ───────────────────────────────────────────────
  async function showDetail(id) {
    const existing = $("inline-detail-" + id);
    const card = document.querySelector(`.entry-card[data-id="${id}"]`);
    if (existing) {
      existing.remove();
      if (card) card.classList.remove("active");
      state.currentEntryId = null;
      state.currentEntryData = null;
      return;
    }
    // Close previously open detail
    $$(".inline-detail").forEach(n => n.remove());
    $$(".entry-card").forEach(c => c.classList.remove("active"));
    if (card) card.classList.add("active");

    try {
      const d = await apiGet("/api/entries/" + encodeURIComponent(id));
      state.currentEntryId = id;
      state.currentEntryData = d;
      const det = renderDetailPanel(id, d);
      if (card) {
        card.after(det);
        det.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    } catch (e) {
      toast("Load failed: " + e.message, "error");
    }
  }

  function renderDetailPanel(id, d) {
    const m = d.meta || {};
    const isManual = d.is_manual ?? !(m.tags || []).includes("auto-capture");

    const rows = [
      ["Type", m.type || "memory"],
      ["Scope", m.scope || "team"],
      ["Tier", m.tier || "—"],
      ["Source", isManual ? "manual (1.3× boost)" : "auto-capture"],
      ["Created", fmtDate(m.created)],
      ["Accessed", fmtDate(m.accessed)],
      ["Decay", Number(m.decay_score || 0).toFixed(4)],
      ["Tags", (m.tags || []).join(", ") || "—"],
      ["Agent", m.agent || "—"],
    ];
    if (m.priority) rows.push(["Priority", m.priority]);
    if (m.status) rows.push(["Status", m.status]);
    if (m.assignee) rows.push(["Assignee", m.assignee]);
    if (m.due_date) rows.push(["Due", m.due_date]);
    if (m.project) rows.push(["Project", m.project]);

    const dl = el("dl", { class: "detail-meta" });
    for (const [k, v] of rows) {
      dl.appendChild(el("dt", {}, k));
      dl.appendChild(el("dd", {}, String(v)));
    }

    const toolbar = el("div", { class: "detail-toolbar" },
      el("h2", {}, m.title || "(untitled)"),
      el("div", { class: "detail-actions" },
        el("button", { class: "btn-secondary btn-small", dataset: { action: "edit-current" } }, "Edit"),
        el("button", { class: "btn-danger btn-small", dataset: { action: "delete-current" } }, "Delete"),
        el("button", { class: "btn-icon", dataset: { action: "close-detail", id } }, "✕"),
      ),
    );

    const body = el("pre", { class: "detail-body" }, d.content || "");

    return el("div", { id: "inline-detail-" + id, class: "inline-detail" }, toolbar, dl, body);
  }

  function closeDetail() {
    $$(".inline-detail").forEach(n => n.remove());
    $$(".entry-card").forEach(c => c.classList.remove("active"));
    state.currentEntryId = null;
    state.currentEntryData = null;
  }

  // ── Tasks panel (post-it UX) ─────────────────────────────────────────────
  async function loadTasks() {
    try {
      const d = await apiGet("/api/entries?type=task&status=open&limit=100");
      // Also fetch in-progress
      const d2 = await apiGet("/api/entries?type=task&status=in-progress&limit=100");
      const tasks = [...d.entries, ...d2.entries];
      renderTasks(tasks);
    } catch (e) { /* non-fatal */ }
  }

  function renderTasks(tasks) {
    const list = $("task-list");
    list.innerHTML = "";
    if (!tasks.length) {
      list.appendChild(el("div", { class: "tasks-empty" }, "No active tasks."));
      return;
    }
    for (const t of tasks) {
      const item = el("div", { class: "task-item", dataset: { id: t.id } });
      item.appendChild(el("button", {
        class: "task-done",
        dataset: { action: "task-done", id: t.id },
        title: "Mark done (deletes post-it)",
      }, "✓"));
      const body = el("div", { class: "task-body" });
      body.appendChild(el("div", { class: "task-title" }, t.title || t.body_preview || "(untitled)"));
      const metaLine = el("div", { class: "task-meta" });
      if (t.priority) metaLine.appendChild(el("span", { class: "badge badge-priority-" + t.priority }, t.priority));
      if (t.status && t.status !== "open") metaLine.appendChild(el("span", { class: "badge badge-status" }, t.status));
      if (t.due_date) metaLine.appendChild(el("span", { class: "task-due" }, "due " + t.due_date));
      body.appendChild(metaLine);
      item.appendChild(body);
      list.appendChild(item);
    }
  }

  async function completeTask(id) {
    try {
      const resp = await apiPatch("/api/entries/" + encodeURIComponent(id), { status: "done" });
      if (resp && resp.deleted) {
        toast("Task completed (deleted)", "success");
      } else {
        toast("Task marked done", "success");
      }
      loadTasks();
      loadStatus();
      if (!state.searchMode) loadEntries();
    } catch (e) {
      toast("Failed: " + e.message, "error");
    }
  }

  // ── Create/Edit modal ────────────────────────────────────────────────────
  function openCreateModal(prefill = {}) {
    $("form-id").value = "";
    $("form-body").value = prefill.body || "";
    $("form-title").value = "";
    $("form-type").value = prefill.type || "memory";
    $("form-scope").value = "team";
    $("form-project").value = "";
    $("form-tags").value = "";
    $("form-agent").value = "";
    $("form-priority").value = "";
    $("form-status").value = prefill.status || "";
    $("form-assignee").value = "";
    $("form-due").value = "";
    $("modal-title").textContent = "New Entry";
    $("form-submit-btn").textContent = "Create";
    toggleTaskFields();
    $("modal-overlay").hidden = false;
    $("form-body").focus();
  }

  function openEditModal() {
    if (!state.currentEntryData) return;
    const d = state.currentEntryData;
    const m = d.meta || {};
    $("form-id").value = state.currentEntryId;
    $("form-body").value = d.content || "";
    $("form-title").value = m.title || "";
    $("form-type").value = m.type || "memory";
    $("form-scope").value = m.scope || "team";
    $("form-project").value = m.project || "";
    $("form-tags").value = (m.tags || []).filter(t => t !== "auto-capture").join(", ");
    $("form-agent").value = m.agent || "";
    $("form-priority").value = m.priority || "";
    $("form-status").value = m.status || "";
    $("form-assignee").value = m.assignee || "";
    $("form-due").value = m.due_date || "";
    $("modal-title").textContent = "Edit Entry";
    $("form-submit-btn").textContent = "Save";
    toggleTaskFields();
    $("modal-overlay").hidden = false;
    $("form-body").focus();
  }

  function closeModal() {
    $("modal-overlay").hidden = true;
  }

  function toggleTaskFields() {
    $("task-fields").hidden = $("form-type").value !== "task";
  }

  async function submitForm(ev) {
    ev.preventDefault();
    const id = $("form-id").value;
    const isEdit = !!id;

    const body = $("form-body").value.trim();
    if (!body) { toast("Content required", "error"); return; }

    const type = $("form-type").value;
    const status = $("form-status").value || null;

    // Warn before deleting a task via edit
    if (isEdit && type === "task" && (status === "done" || status === "wontfix")) {
      if (!confirm(`Setting status to '${status}' will delete this task (post-it behaviour). Continue?`)) return;
    }

    const payload = {
      body,
      title: $("form-title").value.trim() || null,
      type,
      scope: $("form-scope").value,
      tags: $("form-tags").value.trim()
        ? $("form-tags").value.split(",").map(t => t.trim()).filter(Boolean)
        : [],
      project: $("form-project").value.trim() || null,
      priority: $("form-priority").value || null,
      status,
      assignee: $("form-assignee").value.trim() || null,
      due_date: $("form-due").value || null,
    };

    try {
      if (isEdit) {
        // PATCH accepts the same field names except entry_type vs type handled server-side
        const resp = await apiPatch("/api/entries/" + encodeURIComponent(id), payload);
        closeModal();
        if (resp && resp.deleted) {
          toast("Entry deleted (task completed)", "success");
          closeDetail();
        } else {
          toast("Updated", "success");
          showDetail(id); // refresh detail
        }
      } else {
        await apiPost("/api/entries", payload);
        closeModal();
        toast("Created", "success");
      }
      loadStatus();
      loadTasks();
      if (!state.searchMode) loadEntries();
    } catch (e) {
      toast("Error: " + e.message, "error");
    }
  }

  async function deleteCurrent() {
    if (!state.currentEntryId) return;
    if (!confirm("Delete this entry? Cannot be undone.")) return;
    try {
      await apiDelete("/api/entries/" + encodeURIComponent(state.currentEntryId));
      toast("Deleted", "success");
      closeDetail();
      loadStatus();
      loadTasks();
      if (!state.searchMode) loadEntries();
    } catch (e) {
      toast("Delete failed: " + e.message, "error");
    }
  }

  // ── Event wiring (delegation) ────────────────────────────────────────────
  function wireEvents() {
    // Filter changes
    for (const sel of $$("[data-filter]")) {
      sel.addEventListener("change", applyFiltersThenReload);
    }

    // Type toggle in form
    $("form-type").addEventListener("change", toggleTaskFields);

    // Form submit
    $("entry-form").addEventListener("submit", submitForm);

    // Search input
    $("search-input").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") doSearch();
      if (ev.key === "Escape") { ev.target.value = ""; clearSearch(); }
    });

    // Delegated click handler
    document.addEventListener("click", (ev) => {
      const target = ev.target.closest("[data-action], [data-stop-propagation]");
      if (!target) return;

      if (target.hasAttribute("data-stop-propagation")) {
        ev.stopPropagation();
        if (!target.hasAttribute("data-action")) return;
      }

      const action = target.dataset.action;
      const id = target.dataset.id;

      switch (action) {
        case "search": doSearch(); break;
        case "new-entry": openCreateModal(); break;
        case "new-task": openCreateModal({ type: "task", status: "open" }); break;
        case "show-detail": if (id) showDetail(id); break;
        case "close-detail": if (id) showDetail(id); break; // same fn toggles
        case "edit-current": openEditModal(); break;
        case "delete-current": deleteCurrent(); break;
        case "task-done": if (id) { ev.stopPropagation(); completeTask(id); } break;
        case "close-modal": closeModal(); break;
        case "close-modal-backdrop":
          if (ev.target === $("modal-overlay")) closeModal();
          break;
        case "toggle-doctor":
        case "toggle-doctor-details":
          $("doctor-banner").hidden = false;
          $("doctor-list").hidden = !$("doctor-list").hidden;
          break;
        case "close-doctor-banner":
          $("doctor-banner").hidden = true;
          break;
      }
    });
  }

  // ── Boot ─────────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    wireEvents();
    loadStatus();
    loadProjects();
    loadAgents();
    loadDoctor();
    loadEntries();
    loadTasks();
  });
})();
