/* Palaia WebUI — Vanilla JS Application */

const API = '';  // Same origin

// State
let currentEntries = [];
let searchMode = false;

// Init
document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadProjects();
    loadEntries();

    document.getElementById('search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch();
        if (e.key === 'Escape') { e.target.value = ''; clearSearch(); }
    });
});

// API helper
async function api(path) {
    const resp = await fetch(API + path);
    if (!resp.ok) throw new Error('API error: ' + resp.status);
    return resp.json();
}

// Load status bar
async function loadStatus() {
    try {
        const data = await api('/api/status');
        document.getElementById('stat-total').textContent = data.total + ' entries';
        document.getElementById('stat-version').textContent = 'v' + data.version;
    } catch (e) {
        console.error('Failed to load status:', e);
    }
}

// Load project filter options
async function loadProjects() {
    try {
        const data = await api('/api/projects');
        const select = document.getElementById('filter-project');
        for (const name of Object.keys(data.projects || {})) {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        }
    } catch (e) {
        console.error('Failed to load projects:', e);
    }
}

// Load entry list
async function loadEntries() {
    const params = new URLSearchParams();
    const type = document.getElementById('filter-type').value;
    const tier = document.getElementById('filter-tier').value;
    const project = document.getElementById('filter-project').value;
    const status = document.getElementById('filter-status').value;
    if (type) params.set('type', type);
    if (tier) params.set('tier', tier);
    if (project) params.set('project', project);
    if (status) params.set('status', status);
    params.set('limit', '100');

    try {
        const data = await api('/api/entries?' + params.toString());
        currentEntries = data.entries;
        renderEntries(data.entries, data.total);
    } catch (e) {
        document.getElementById('entry-list').innerHTML =
            '<div class="loading">Error loading entries</div>';
    }
}

// Search
function doSearch() {
    const q = document.getElementById('search-input').value.trim();
    if (!q) { clearSearch(); return; }

    const params = new URLSearchParams({ q: q, limit: '20' });
    const type = document.getElementById('filter-type').value;
    const project = document.getElementById('filter-project').value;
    const status = document.getElementById('filter-status').value;
    if (type) params.set('type', type);
    if (project) params.set('project', project);
    if (status) params.set('status', status);

    document.getElementById('entry-list').innerHTML = '<div class="loading">Searching...</div>';

    api('/api/search?' + params.toString()).then(data => {
        searchMode = true;
        const entries = data.results.map(r => ({
            id: r.id, title: r.title, type: r.type, scope: r.scope,
            tier: r.tier, tags: r.tags || [], project: r.project,
            status: r.status, priority: r.priority,
            decay_score: r.decay_score, body_preview: r.body,
            score: r.score, bm25_score: r.bm25_score, embed_score: r.embed_score,
        }));
        currentEntries = entries;
        renderEntries(entries, data.count, true);
    }).catch(e => {
        document.getElementById('entry-list').innerHTML =
            '<div class="loading">Search error</div>';
    });
}

function clearSearch() {
    searchMode = false;
    document.getElementById('detail-panel').classList.remove('visible');
    loadEntries();
}

function applyFilters() {
    if (searchMode) doSearch();
    else loadEntries();
}

// Render entry cards
function renderEntries(entries, total, isSearch) {
    const list = document.getElementById('entry-list');
    const countEl = document.getElementById('result-count');

    if (entries.length === 0) {
        list.innerHTML = '<div class="loading">No entries found</div>';
        countEl.textContent = '';
        return;
    }

    countEl.textContent = isSearch
        ? total + ' result' + (total !== 1 ? 's' : '') + ' found'
        : 'Showing ' + entries.length + ' of ' + total + ' entries';

    list.innerHTML = entries.map(function(e) {
        var scoreText = e.score != null
            ? 'score: ' + e.score
            : 'decay: ' + (e.decay_score || 0).toFixed(2);
        var tags = (e.tags || []).slice(0, 3).map(function(t) {
            return '<span class="tag">' + escHtml(t) + '</span>';
        }).join('');
        return '<div class="entry-card" onclick="showDetail(\'' + e.id + '\')" id="card-' + e.id + '">'
            + '<div class="entry-header">'
            + '<span class="entry-title">' + escHtml(e.title || '(untitled)') + '</span>'
            + '<span class="entry-score">' + scoreText + '</span>'
            + '</div>'
            + '<div class="entry-meta">'
            + '<span class="badge badge-' + (e.tier || 'hot') + '">' + (e.tier || 'hot') + '</span>'
            + '<span class="badge badge-' + (e.type || 'memory') + '">' + (e.type || 'memory') + '</span>'
            + (e.project ? '<span>' + escHtml(e.project) + '</span>' : '')
            + (e.status ? '<span>' + e.status + '</span>' : '')
            + tags
            + '</div>'
            + '<div class="entry-preview">' + escHtml(e.body_preview || '') + '</div>'
            + '</div>';
    }).join('');
}

// Show entry detail
async function showDetail(id) {
    document.querySelectorAll('.entry-card').forEach(function(c) { c.classList.remove('active'); });
    var card = document.getElementById('card-' + id);
    if (card) card.classList.add('active');

    try {
        const data = await api('/api/entries/' + id);
        const panel = document.getElementById('detail-panel');
        const meta = data.meta || {};

        document.getElementById('detail-title').textContent = meta.title || '(untitled)';

        var fields = [
            ['Type', meta.type || 'memory'],
            ['Scope', meta.scope || 'team'],
            ['Tier', meta.tier || 'unknown'],
            ['Created', formatDate(meta.created)],
            ['Accessed', formatDate(meta.accessed)],
            ['Decay Score', (meta.decay_score || 0).toFixed(4)],
            ['Tags', (meta.tags || []).join(', ') || 'none'],
            ['Agent', meta.agent || 'default'],
        ];
        document.getElementById('detail-meta').innerHTML = fields.map(function(f) {
            return '<dt>' + f[0] + '</dt><dd>' + escHtml(String(f[1])) + '</dd>';
        }).join('');

        document.getElementById('detail-body').textContent = data.content || '';
        panel.classList.add('visible');
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (e) {
        console.error('Failed to load entry:', e);
    }
}

// Helpers
function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function formatDate(iso) {
    if (!iso) return 'unknown';
    try {
        var d = new Date(iso);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    } catch(ex) { return iso; }
}
