// ai-superpower Web UI JS
// API calls go to relative /api/* paths (proxied by the HTTP server)

const API_BASE = '/api';
let apiKey = localStorage.getItem('aisp_api_key') || '';
let currentPage = { projects: 1, proposals: 1, audit: 1 };

// ─── Init ─────────────────────────────────────────────────────────────────────

async function ensureKey() {
    if (!apiKey) {
        apiKey = prompt('Enter API Key (saved in localStorage):') || '';
        if (apiKey) localStorage.setItem('aisp_api_key', apiKey);
    }
    if (!apiKey) alert('No API Key — set localStorage.aisp_api_key or reload and enter key');
}

// ─── API helpers ──────────────────────────────────────────────────────────────

async function api(method, path, body) {
    await ensureKey();
    const opts = {
        method,
        headers: { 'X-API-Key': apiKey, 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(API_BASE + path, opts);
    if (r.status === 401) { apiKey = ''; localStorage.removeItem('aisp_api_key'); throw new Error('Invalid API Key'); }
    if (r.status === 204) return null;
    const json = await r.json();
    if (!r.ok) throw new Error(json.detail || `HTTP ${r.status}`);
    return json;
}

// ─── Dashboard ───────────────────────────────────────────────────────────────

async function loadDashboard() {
    try {
        const [proj, prop, aud] = await Promise.all([
            api('GET', '/projects?page_size=1'),
            api('GET', '/proposals?page_size=1'),
            api('GET', '/audit?page_size=1'),
        ]);
        document.getElementById('project-count').textContent = proj.total;
        document.getElementById('proposal-count').textContent = prop.total;
        document.getElementById('audit-count').textContent = aud.total;

        // Recent audit entries
        const audData = await api('GET', '/audit?page_size=5');
        const el = document.getElementById('recent-activity');
        if (!audData.items.length) { el.textContent = 'No activity yet.'; return; }
        el.innerHTML = audData.items.reverse().map(e => `
            <div class="activity-item">
                <span class="op">${e.op}</span>
                <span class="entity">${e.entity}:${e.id}</span>
                ${e.field ? `<span class="field"> [${e.field}]</span>` : ''}
                ${e.old !== null ? `<span class="old">${e.old}</span>` : ''}
                ${e.new !== null ? `→ <span class="new">${e.new}</span>` : ''}
                <span style="color:#64748b;margin-left:0.5rem;font-size:0.75rem">${e.actor}</span>
            </div>
        `).join('');
    } catch (e) { document.getElementById('recent-activity').textContent = 'Error: ' + e.message; }
    // Load sync status too
    loadSyncStatus();
}

// ─── Projects ────────────────────────────────────────────────────────────────

async function loadProjects(page = 1) {
    currentPage.projects = page;
    const search = document.getElementById('search')?.value || '';
    const sortBy = document.getElementById('sort-by')?.value || 'last_update';
    const sortOrder = document.getElementById('sort-order')?.value || 'desc';
    const qs = `page=${page}&page_size=20` + (search ? `&search=${encodeURIComponent(search)}` : '') + `&sort_by=${sortBy}&sort_order=${sortOrder}`;
    try {
        const data = await api('GET', '/projects?' + qs);
        const el = document.getElementById('project-list');
        if (!data.items.length) { el.innerHTML = '<p>No projects found.</p>'; }
        else {
            el.innerHTML = `<table><thead><tr><th>ID</th><th>Name</th><th>Proposals</th><th>Git Repo</th><th>PRJ URL</th><th>Create At</th><th>Last Update</th><th></th></tr></thead><tbody>
                ${data.items.map(p => `<tr>
                    <td>${p.id}</td><td>${esc(p.name)}</td><td>${p.proposal_count}</td>
                    <td>${p.git_repo ? `<a href="${esc(p.git_repo)}" target="_blank">${esc(p.git_repo)}</a>` : '—'}</td>
                    <td>${p.prj_url ? `<a href="${esc(p.prj_url)}" target="_blank">${esc(p.prj_url)}</a>` : '—'}</td>
                    <td>${p.create_at || '—'}</td><td>${p.last_update}</td>
                    <td><button onclick="showProjectForm('${p.id}')">Edit</button></td>
                    <td><button onclick="deleteProject('${p.id}')" style="color:#f87171">Del</button></td>
                </tr>`).join('')}
            </tbody></table>`;
        }
        renderPagination('pagination', page, data.total, 20, loadProjects);
    } catch (e) { document.getElementById('project-list').textContent = 'Error: ' + e.message; }
}

async function showProjectDetail(id) {
    try {
        const p = await api('GET', '/projects/' + id);
        alert(`Project: ${p.name}\nID: ${p.id}\nGit: ${p.git_repo || '-'}\nPRJ URL: ${p.prj_url || '-'}\nPath: ${p.local_path || '-'}\nDesc: ${p.description || '-'}\nProposals: ${p.proposal_count}\nCreated: ${p.create_at || '-'}\nUpdated: ${p.last_update}`);
    } catch (e) { alert(e.message); }
}

function showProjectForm(id) {
    const title = id ? 'Edit Project' : 'New Project';
    document.getElementById('modal-title').textContent = title;
    document.getElementById('project-id').value = id || '';
    if (id) {
        api('GET', '/projects/' + id).then(p => {
            document.getElementById('name').value = p.name;
            document.getElementById('git_repo').value = p.git_repo || '';
            document.getElementById('local_path').value = p.local_path || '';
            document.getElementById('description').value = p.description || '';
            document.getElementById('prj_url').value = p.prj_url || '';
        });
    } else {
        document.getElementById('name').value = '';
        document.getElementById('git_repo').value = '';
        document.getElementById('local_path').value = '';
        document.getElementById('description').value = '';
        document.getElementById('prj_url').value = '';
    }
    document.getElementById('modal').classList.remove('hidden');
}

async function submitProjectForm(e) {
    e.preventDefault();
    const id = document.getElementById('project-id').value;
    const body = {
        name: document.getElementById('name').value,
        git_repo: document.getElementById('git_repo').value,
        prj_url: document.getElementById('prj_url').value,
        local_path: document.getElementById('local_path').value,
        description: document.getElementById('description').value,
    };
    try {
        if (id) await api('PUT', '/projects/' + id, body);
        else await api('POST', '/projects', body);
        closeModal();
        loadProjects(currentPage.projects);
    } catch (e) { alert('Error: ' + e.message); }
}

// ─── Proposals ────────────────────────────────────────────────────────────────

async function loadProposals(page = 1) {
    currentPage.proposals = page;
    const search = document.getElementById('search')?.value || '';
    const status = document.getElementById('status-filter')?.value || '';
    const sortBy = document.getElementById('sort-by')?.value || 'last_update';
    const sortOrder = document.getElementById('sort-order')?.value || 'desc';
    const qs = `page=${page}&page_size=20` +
        (search ? `&search=${encodeURIComponent(search)}` : '') +
        (status ? `&status=${encodeURIComponent(status)}` : '') +
        `&sort_by=${sortBy}&sort_order=${sortOrder}`;
    try {
        const data = await api('GET', '/proposals?' + qs);
        const el = document.getElementById('proposal-list');
        if (!data.items.length) { el.innerHTML = '<p>No proposals found.</p>'; }
        else {
            el.innerHTML = `<table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Stage</th><th>Owner</th><th>Project</th><th></th><th></th></tr></thead><tbody>
                ${data.items.map(p => `<tr>
                    <td>${p.id}</td><td>${esc(p.title)}</td>
                    <td><span class="badge badge-${esc(p.status)}">${p.status}</span></td>
                    <td>${p.stage || '—'}</td><td>${p.owner || '—'}</td><td>${p.project_id}</td>
                    <td><button onclick="showProposalForm('${p.id}')">Edit</button></td>
                    <td><button onclick="deleteProposal('${p.id}')" style="color:#f87171">Del</button></td>
                </tr>`).join('')}
            </tbody></table>`;
        }
        renderPagination('pagination', page, data.total, 20, loadProposals);
    } catch (e) { document.getElementById('proposal-list').textContent = 'Error: ' + e.message; }
}

async function showProposalDetail(id) {
    try {
        const p = await api('GET', '/proposals/' + id);
        const lines = [
            `Proposal: ${p.title}`, `ID: ${p.id}`, `Status: ${p.status}`, `Stage: ${p.stage || '-'}`,
            `Owner: ${p.owner || '-'}`, `Project: ${p.project_id} (${p.project_name})`,
            `Engine: ${p.engine || '-'}`, `Target: ${p.target || '-'}`, `Game Type: ${p.game_type || '-'}`,
            `Updated: ${p.last_update}`, `Notes: ${p.notes || '-'}`,
        ];
        alert(lines.join('\n'));
    } catch (e) { alert(e.message); }
}

function showProposalForm(id) {
    const title = id ? 'Edit Proposal' : 'New Proposal';
    document.getElementById('modal-title').textContent = title;
    document.getElementById('proposal-id').value = id || '';
    if (id) {
        api('GET', '/proposals/' + id).then(p => {
            document.getElementById('title').value = p.title;
            document.getElementById('project_id').value = p.project_id;
            document.getElementById('owner').value = p.owner || '';
            document.getElementById('stage').value = p.stage || '';
            document.getElementById('engine').value = p.engine || '';
            document.getElementById('target').value = p.target || '';
            document.getElementById('game_type').value = p.game_type || '';
            document.getElementById('notes').value = p.notes || '';
        });
    } else {
        ['title','project_id','owner','stage','engine','target','game_type','notes'].forEach(id => {
            document.getElementById(id).value = '';
        });
    }
    document.getElementById('modal').classList.remove('hidden');
}

async function submitProposalForm(e) {
    e.preventDefault();
    const id = document.getElementById('proposal-id').value;
    const body = {
        title: document.getElementById('title').value,
        project_id: document.getElementById('project_id').value,
        owner: document.getElementById('owner').value,
        stage: document.getElementById('stage').value,
        engine: document.getElementById('engine').value,
        target: document.getElementById('target').value,
        game_type: document.getElementById('game_type').value,
        notes: document.getElementById('notes').value,
    };
    try {
        if (id) await api('PUT', '/proposals/' + id + '/fields', body);
        else await api('POST', '/proposals', body);
        closeModal();
        loadProposals(currentPage.proposals);
    } catch (e) { alert('Error: ' + e.message); }
}

function loadStageOptions() {
    const stages = ['','ideation','prototype','alpha','beta','launch','operate'];
    const sel = document.getElementById('stage');
    if (!sel) return;
    sel.innerHTML = stages.map(s => `<option value="${s}">${s || '—'}</option>`).join('');
}

// ─── Audit ───────────────────────────────────────────────────────────────────

async function loadAudit(page = 1) {
    currentPage.audit = page;
    try {
        const data = await api('GET', `/audit?page=${page}&page_size=50`);
        const el = document.getElementById('audit-list');
        if (!data.items.length) { el.innerHTML = '<p>No audit entries.</p>'; }
        else {
            el.innerHTML = `<table><thead><tr><th>Time</th><th>Op</th><th>Entity</th><th>ID</th><th>Field</th><th>Old</th><th>New</th><th>Actor</th></tr></thead><tbody>
                ${data.items.map(e => `<tr>
                    <td>${e.ts ? e.ts.slice(0,19) : '-'}</td>
                    <td><span class="op">${e.op}</span></td>
                    <td>${e.entity}</td>
                    <td>${e.id}</td>
                    <td>${e.field || '-'}</td>
                    <td style="color:#f87171;text-decoration:line-through">${e.old ?? '-'}</td>
                    <td style="color:#4ade80">${e.new ?? '-'}</td>
                    <td><code>${e.actor || '-'}</code></td>
                </tr>`).join('')}
            </tbody></table>`;
        }
        renderPagination('pagination', page, data.total, 50, loadAudit);
    } catch (e) { document.getElementById('audit-list').textContent = 'Error: ' + e.message; }
}

// ─── Settings ────────────────────────────────────────────────────────────────

function showApiKey() {
    document.getElementById('api-key-display').textContent = apiKey || 'not set';
}

async function runBackup() {
    const out = document.getElementById('backup-output');
    out.textContent = 'Running backup...';
    try {
        out.textContent = 'Backup: configure in config.toml [backup] section.';
    } catch (e) { out.textContent = 'Error: ' + e.message; }
}

// ─── Sync Config (Settings) ─────────────────────────────────────────────────

async function loadSyncConfig() {
    const out = document.getElementById('sync-config-output');
    try {
        const cfg = await api('GET', '/sync/config');
        document.getElementById('sync-target-repo').value = cfg.sync_target_repo || '';
        document.getElementById('sync-enabled').checked = cfg.sync_enabled;
    } catch (e) { if (out) out.textContent = 'Error: ' + e.message; }
}

async function saveSyncConfig() {
    const out = document.getElementById('sync-config-output');
    out.textContent = 'Saving...';
    try {
        const body = {
            sync_target_repo: document.getElementById('sync-target-repo').value,
            sync_enabled: document.getElementById('sync-enabled').checked,
        };
        await api('POST', '/sync/config', body);
        out.textContent = 'Sync config saved.';
    } catch (e) { out.textContent = 'Error: ' + e.message; }
}

// ─── Sync Status / Export (Dashboard) ───────────────────────────────────────

async function loadSyncStatus() {
    try {
        const cfg = await api('GET', '/sync/config');
        document.getElementById('sync-target-repo-display').textContent = cfg.sync_target_repo || '—';
        document.getElementById('sync-enabled-display').textContent = cfg.sync_enabled ? 'Yes' : 'No';
        document.getElementById('sync-enabled-toggle').checked = cfg.sync_enabled;
        document.getElementById('sync-last-run-display').textContent = '—';
    } catch (e) { /* silently fail for dashboard */ }
}

async function triggerSyncExport() {
    const out = document.getElementById('sync-output');
    out.textContent = 'Triggering sync export...';
    try {
        const r = await api('POST', '/sync/export');
        out.textContent = JSON.stringify(r);
    } catch (e) { out.textContent = 'Error: ' + e.message; }
}

async function toggleSyncEnabled() {
    const enabled = document.getElementById('sync-enabled-toggle').checked;
    try {
        await api('POST', '/sync/config', { sync_enabled: enabled });
        document.getElementById('sync-enabled-display').textContent = enabled ? 'Yes' : 'No';
    } catch (e) { /* silent fail */ }
}

// ─── Modal ──────────────────────────────────────────────────────────────────

function closeModal() {
    document.getElementById('modal').classList.add('hidden');
}

// ─── Utils ──────────────────────────────────────────────────────────────────

function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderPagination(elId, page, total, pageSize, loadFn) {
    const totalPages = Math.ceil(total / pageSize);
    const el = document.getElementById(elId);
    if (!el || totalPages <= 1) { if (el) el.innerHTML = ''; return; }
    let html = '';
    if (page > 1) html += `<button onclick="(${loadFn.name})(${page-1})">← Prev</button>`;
    html += `<span style="padding:0.4rem 0.8rem">${page} / ${totalPages}</span>`;
    if (page < totalPages) html += `<button onclick="(${loadFn.name})(${page+1})">Next →</button>`;
    el.innerHTML = html;
}

// Close modal on outside click
document.addEventListener('click', e => {
    if (e.target.classList.contains('modal')) closeModal();
});

// ─── Delete ────────────────────────────────────────────────────────────────────

async function deleteProject(id) {
    if (!confirm(`Delete project ${id}?`)) return;
    try {
        await api('DELETE', '/projects/' + id);
        loadProjects(currentPage.projects);
    } catch (e) { alert('Error: ' + e.message); }
}

async function deleteProposal(id) {
    if (!confirm(`Delete proposal ${id}?`)) return;
    try {
        await api('DELETE', '/proposals/' + id);
        loadProposals(currentPage.proposals);
    } catch (e) { alert('Error: ' + e.message); }
}
