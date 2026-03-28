/* Palaia WebUI - Phase 2 */
const API = '';
let currentEntries = [], searchMode = false, currentEntryId = null, currentEntryData = null;

document.addEventListener('DOMContentLoaded', () => {
    loadStatus(); loadProjects(); loadEntries();
    document.getElementById('search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch();
        if (e.key === 'Escape') { e.target.value = ''; clearSearch(); }
    });
});

async function api(path, opts) {
    const resp = await fetch(API + path, opts);
    if (!resp.ok) { const body = await resp.text(); throw new Error(body || 'API error: ' + resp.status); }
    return resp.json();
}
async function apiPost(p, d) { return api(p, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}); }
async function apiPatch(p, d) { return api(p, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}); }
async function apiDelete(p) { return api(p, {method:'DELETE'}); }

function showToast(msg, type) {
    type = type || 'info';
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast toast-' + type + ' toast-visible';
    setTimeout(function() { t.className = 'toast'; }, 3000);
}

async function loadStatus() {
    try {
        const d = await api('/api/status');
        document.getElementById('stat-total').textContent = d.total + ' entries';
        document.getElementById('stat-version').textContent = 'v' + d.version;
    } catch(e) { console.error('loadStatus:', e); }
}

async function loadProjects() {
    try {
        const d = await api('/api/projects');
        const sel = document.getElementById('filter-project');
        for (const n of Object.keys(d.projects || {})) {
            const o = document.createElement('option'); o.value = n; o.textContent = n; sel.appendChild(o);
        }
    } catch(e) { console.error('loadProjects:', e); }
}

async function loadEntries() {
    const p = new URLSearchParams();
    const type = document.getElementById('filter-type').value;
    const tier = document.getElementById('filter-tier').value;
    const proj = document.getElementById('filter-project').value;
    const stat = document.getElementById('filter-status').value;
    if (type) p.set('type', type); if (tier) p.set('tier', tier);
    if (proj) p.set('project', proj); if (stat) p.set('status', stat);
    p.set('limit', '100');
    try {
        const d = await api('/api/entries?' + p.toString());
        currentEntries = d.entries;
        renderEntries(d.entries, d.total);
    } catch(e) { document.getElementById('entry-list').innerHTML = '<div class="loading">Error loading</div>'; }
}

function doSearch() {
    const q = document.getElementById('search-input').value.trim();
    if (!q) { clearSearch(); return; }
    const p = new URLSearchParams({q:q, limit:'20'});
    const type = document.getElementById('filter-type').value;
    const proj = document.getElementById('filter-project').value;
    const stat = document.getElementById('filter-status').value;
    if (type) p.set('type', type); if (proj) p.set('project', proj); if (stat) p.set('status', stat);
    document.getElementById('entry-list').innerHTML = '<div class="loading">Searching...</div>';
    api('/api/search?' + p.toString()).then(d => {
        searchMode = true;
        const entries = d.results.map(r => ({
            id:r.id, title:r.title, type:r.type, scope:r.scope, tier:r.tier, tags:r.tags||[],
            project:r.project, status:r.status, priority:r.priority, decay_score:r.decay_score,
            body_preview:r.body, score:r.score
        }));
        currentEntries = entries;
        renderEntries(entries, d.count, true, d.timed_out ? ' (BM25 only)' : '');
    }).catch(e => { document.getElementById('entry-list').innerHTML = '<div class="loading">Search error</div>'; });
}
function clearSearch() { searchMode = false; closeDetail(); loadEntries(); }
function applyFilters() { if (searchMode) doSearch(); else loadEntries(); }

function renderEntries(entries, total, isSearch, extra) {
    const list = document.getElementById('entry-list');
    const countEl = document.getElementById('result-count');
    if (!entries.length) { list.innerHTML = '<div class="loading">No entries found</div>'; countEl.textContent = ''; return; }
    countEl.textContent = isSearch
        ? total + ' result' + (total !== 1 ? 's' : '') + ' found' + (extra || '')
        : 'Showing ' + entries.length + ' of ' + total + ' entries';
    list.innerHTML = entries.map(function(e) {
        var sc = e.score != null ? 'score: '+e.score : 'decay: '+(e.decay_score||0).toFixed(2);
        var tags = (e.tags||[]).slice(0,3).map(function(t){return '<span class="tag">'+esc(t)+'</span>';}).join('');
        var pri = e.priority ? '<span class="badge badge-priority-'+e.priority+'">'+e.priority+'</span>' : '';
        return '<div class="entry-card" onclick="showDetail(\x27'+e.id+'\x27)" id="card-'+e.id+'">' 
          +'<div class="entry-header"><span class="entry-title">'+esc(e.title||'(untitled)')+'</span><span class="entry-score">'+sc+'</span></div>'
          +'<div class="entry-meta"><span class="badge badge-'+(e.tier||'hot')+'">'+(e.tier||'hot')+'</span>'
          +'<span class="badge badge-'+(e.type||'memory')+'">'+(e.type||'memory')+'</span>'+pri
          +(e.project?'<span>'+esc(e.project)+'</span>':'')
          +(e.status?'<span class="status-label">'+e.status+'</span>':'')+tags+'</div>'
          +'<div class="entry-preview">'+esc(e.body_preview||'')+'</div></div>';
    }).join('');
}

async function showDetail(id) {
    var existing = document.getElementById('inline-detail-'+id);
    if (existing) { existing.remove(); currentEntryId = null; currentEntryData = null;
        document.getElementById('card-'+id).classList.remove('active'); return; }
    document.querySelectorAll('.inline-detail').forEach(function(el) { el.remove(); });
    document.querySelectorAll('.entry-card').forEach(function(c) { c.classList.remove('active'); });
    var card = document.getElementById('card-'+id);
    if (card) card.classList.add('active');
    try {
        var d = await api('/api/entries/'+id);
        currentEntryId = id; currentEntryData = d;
        var m = d.meta || {};
        var fields = [
            ['Type', m.type||'memory'],['Scope', m.scope||'team'],['Tier', m.tier||'unknown'],
            ['Created', fmtDate(m.created)],['Accessed', fmtDate(m.accessed)],
            ['Decay', (m.decay_score||0).toFixed(4)],
            ['Tags', (m.tags||[]).join(', ')||'none'],['Agent', m.agent||'default']
        ];
        if (m.priority) fields.push(['Priority', '<span class="badge badge-priority-'+m.priority+'">'+esc(m.priority)+'</span>']);
        if (m.status) fields.push(['Status', m.status]);
        if (m.assignee) fields.push(['Assignee', m.assignee]);
        if (m.due_date) fields.push(['Due', m.due_date]);
        if (m.project) fields.push(['Project', m.project]);
        var metaHtml = fields.map(function(f) { return '<dt>'+f[0]+'</dt><dd>'+f[1]+'</dd>'; }).join('');
        var det = document.createElement('div');
        det.id = 'inline-detail-'+id;
        det.className = 'inline-detail';
        det.innerHTML = '<div class="detail-toolbar"><h2>'+esc(m.title||'(untitled)')+'</h2>'
            +'<div class="detail-actions">'
            +'<button class="btn-edit" onclick="editCurrentEntry()">\u270f\ufe0f Edit</button>'
            +'<button class="btn-delete" onclick="deleteCurrentEntry()">\ud83d\uddd1\ufe0f Delete</button>'
            +'<button class="btn-close" onclick="showDetail(\x27'+id+'\x27)">\u2715</button>'
            +'</div></div>'
            +'<dl class="detail-meta">'+metaHtml+'</dl>'
            +'<pre class="detail-body">'+esc(d.content||'')+'</pre>';
        card.after(det);
        det.scrollIntoView({behavior:'smooth', block:'nearest'});
    } catch(e) { console.error('showDetail:', e); }
}
function closeDetail() {
    document.querySelectorAll('.inline-detail').forEach(function(el) { el.remove(); });
    document.querySelectorAll('.entry-card').forEach(function(c) { c.classList.remove('active'); });
    currentEntryId = null; currentEntryData = null;
}

function showCreateForm() {
    ['form-id','form-body','form-title','form-tags','form-assignee','form-due'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('form-type').value = 'memory';
    document.getElementById('form-scope').value = 'team';
    ['form-priority','form-status'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('modal-title').textContent = 'New Entry';
    document.getElementById('form-submit-btn').textContent = 'Create Entry';
    toggleTaskFields();
    document.getElementById('modal-overlay').classList.add('visible');
    document.getElementById('form-body').focus();
}

function editCurrentEntry() {
    if (!currentEntryData) return;
    var d = currentEntryData, m = d.meta || {};
    document.getElementById('form-id').value = currentEntryId;
    document.getElementById('form-body').value = d.content || '';
    document.getElementById('form-title').value = m.title || '';
    document.getElementById('form-type').value = m.type || 'memory';
    document.getElementById('form-scope').value = m.scope || 'team';
    document.getElementById('form-tags').value = (m.tags || []).join(', ');
    document.getElementById('form-priority').value = m.priority || '';
    document.getElementById('form-status').value = m.status || '';
    document.getElementById('form-assignee').value = m.assignee || '';
    document.getElementById('form-due').value = m.due_date || '';
    document.getElementById('modal-title').textContent = 'Edit Entry';
    document.getElementById('form-submit-btn').textContent = 'Save Changes';
    toggleTaskFields();
    document.getElementById('modal-overlay').classList.add('visible');
    document.getElementById('form-body').focus();
}

function toggleTaskFields() {
    document.getElementById('task-fields').style.display =
        document.getElementById('form-type').value === 'task' ? 'block' : 'none';
}

function closeModal(ev) {
    if (ev && ev.target !== document.getElementById('modal-overlay')) return;
    document.getElementById('modal-overlay').classList.remove('visible');
}

async function submitEntryForm(ev) {
    ev.preventDefault();
    var id = document.getElementById('form-id').value, isEdit = !!id;
    var body = document.getElementById('form-body').value.trim();
    var title = document.getElementById('form-title').value.trim() || null;
    var type = document.getElementById('form-type').value;
    var scope = document.getElementById('form-scope').value;
    var raw = document.getElementById('form-tags').value.trim();
    var tags = raw ? raw.split(',').map(t => t.trim()).filter(Boolean) : [];
    var priority = document.getElementById('form-priority').value || null;
    var status = document.getElementById('form-status').value || null;
    var assignee = document.getElementById('form-assignee').value.trim() || null;
    var due = document.getElementById('form-due').value || null;
    try {
        if (isEdit) {
            var patch = {}; patch.tags = tags;
            if (body && body !== (currentEntryData && currentEntryData.content)) patch.body = body;
            if (title !== null) patch.title = title;
            if (type) patch.type = type;
            if (priority) patch.priority = priority;
            if (status) patch.status = status;
            if (assignee) patch.assignee = assignee;
            if (due) patch.due_date = due;
            await apiPatch('/api/entries/' + id, patch);
            showToast('Entry updated', 'success');
        } else {
            var pl = {body:body, type:type, scope:scope, tags:tags};
            if (title) pl.title = title;
            if (priority) pl.priority = priority;
            if (status) pl.status = status;
            if (assignee) pl.assignee = assignee;
            if (due) pl.due_date = due;
            await apiPost('/api/entries', pl);
            showToast('Entry created', 'success');
        }
        closeModal(); loadStatus(); loadEntries();
        if (isEdit && currentEntryId) showDetail(currentEntryId);
    } catch(e) { showToast('Error: ' + e.message, 'error'); }
    return false;
}

async function deleteCurrentEntry() {
    if (!currentEntryId || !confirm('Delete this entry? Cannot be undone.')) return;
    try {
        await apiDelete('/api/entries/' + currentEntryId);
        showToast('Entry deleted', 'success');
        closeDetail(); loadStatus(); loadEntries();
    } catch(e) { showToast('Delete failed: ' + e.message, 'error'); }
}

function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function fmtDate(iso) {
    if (!iso) return 'unknown';
    try { var d = new Date(iso); return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); }
    catch(x) { return iso; }
}
