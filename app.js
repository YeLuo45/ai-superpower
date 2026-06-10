// ai-superpower Web UI JS
// API calls go to relative /api/* paths (proxied by the HTTP server)

const API_BASE = '/api';
const AISP_CONFIG = window.AISP_CONFIG || {};
let apiKey = localStorage.getItem('aisp_api_key') || AISP_CONFIG.api_key || '';
let currentPage = { projects: 1, proposals: 1, audit: 1 };

// ─── Init ─────────────────────────────────────────────────────────────────────

function initApiKey() {
    if (!apiKey && AISP_CONFIG.api_key) {
        apiKey = AISP_CONFIG.api_key;
        localStorage.setItem('aisp_api_key', apiKey);
    }
}

async function ensureKey() {
    initApiKey();
    if (!apiKey) {
        apiKey = prompt('Enter API Key (from ~/.ai-superpower/config.toml, saved in localStorage):') || '';
        if (apiKey) localStorage.setItem('aisp_api_key', apiKey);
    }
    if (!apiKey) throw new Error('No API Key — check Settings or ~/.ai-superpower/config.toml');
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

let _trendChart = null;
let _statusChart = null;

const CHART_COLORS = {
    projects: '#f472b6',
    proposals: '#60a5fa',
    status: ['#f472b6', '#60a5fa', '#4ade80', '#c084fc', '#fbbf24', '#f87171', '#94a3b8', '#fb923c'],
};

function renderRecentActivity(items) {
    const el = document.getElementById('recent-activity');
    if (!el) return;
    if (!items.length) { el.textContent = 'No activity yet.'; return; }
    el.innerHTML = items.map(e => `
        <div class="activity-item">
            <span class="op">${e.op}</span>
            <span class="entity">${e.entity}:${e.id}</span>
            ${e.field ? `<span class="field"> [${e.field}]</span>` : ''}
            ${e.old !== null ? `<span class="old">${e.old}</span>` : ''}
            ${e.new !== null ? `→ <span class="new">${e.new}</span>` : ''}
            <span style="color:#64748b;margin-left:0.5rem;font-size:0.75rem">${e.actor || ''}</span>
        </div>
    `).join('');
}

function renderTrendChart(trends) {
    const canvas = document.getElementById('trend-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    const labels = trends.projects_by_date.map(d => d.date.slice(5));
    if (_trendChart) _trendChart.destroy();
    _trendChart = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: '项目',
                    data: trends.projects_by_date.map(d => d.count),
                    borderColor: CHART_COLORS.projects,
                    backgroundColor: CHART_COLORS.projects + '33',
                    tension: 0.3,
                    fill: true,
                },
                {
                    label: '提案',
                    data: trends.proposals_by_date.map(d => d.count),
                    borderColor: CHART_COLORS.proposals,
                    backgroundColor: CHART_COLORS.proposals + '33',
                    tension: 0.3,
                    fill: true,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#94a3b8' } } },
            scales: {
                x: { ticks: { color: '#64748b', maxRotation: 45 }, grid: { color: '#2d3348' } },
                y: { beginAtZero: true, ticks: { color: '#64748b', stepSize: 1 }, grid: { color: '#2d3348' } },
            },
        },
    });
}

function renderStatusChart(byStatus) {
    const canvas = document.getElementById('status-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    const labels = Object.keys(byStatus);
    const values = Object.values(byStatus);
    if (_statusChart) _statusChart.destroy();
    if (!labels.length) {
        _statusChart = null;
        return;
    }
    _statusChart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: CHART_COLORS.status.slice(0, labels.length),
                borderColor: '#1a1d27',
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'right', labels: { color: '#94a3b8', boxWidth: 12 } } },
        },
    });
}

async function loadDashboard() {
    const daysEl = document.getElementById('trend-days');
    const days = daysEl ? daysEl.value : 30;
    const errBanner = document.getElementById('dashboard-error');
    try {
        const stats = await api('GET', `/stats?days=${days}`);
        if (errBanner) errBanner.classList.add('hidden');
        document.getElementById('project-count').textContent = stats.totals.projects;
        document.getElementById('proposal-count').textContent = stats.totals.proposals;
        document.getElementById('today-project-count').textContent = stats.today.projects;
        document.getElementById('today-proposal-count').textContent = stats.today.proposals;
        document.getElementById('audit-count').textContent = stats.totals.audit_entries;
        renderTrendChart(stats.trends);
        renderStatusChart(stats.by_status);
        renderRecentActivity(stats.recent_activity || []);
    } catch (e) {
        if (errBanner) {
            errBanner.textContent = '加载失败: ' + e.message + ' — 请到 Settings 查看 API Key，或执行: curl -H "X-API-Key: <key>" ...';
            errBanner.classList.remove('hidden');
        }
        const el = document.getElementById('recent-activity');
        if (el) el.textContent = 'Error: ' + e.message;
    }
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

async function checkDuplicateProject() {
    const name = document.getElementById('name').value;
    const gitRepo = document.getElementById('git_repo').value;
    if (!name && !gitRepo) { alert('Enter name or git_repo first'); return; }
    try {
        const qs = new URLSearchParams({ name, git_repo: gitRepo }).toString();
        const result = await api('GET', '/projects/check-duplicate?' + qs);
        if (result.duplicate) {
            alert('Duplicate found: ' + result.reason + ', existing ID: ' + result.existing_id);
        } else {
            alert('No duplicate found');
        }
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
            el.innerHTML = `<table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Stage</th><th>Owner</th><th>Project</th><th>Created</th><th>Updated</th><th></th><th></th></tr></thead><tbody>
                ${data.items.map(p => `<tr>
                    <td>${p.id}</td><td>${esc(p.title)}</td>
                    <td><span class="badge badge-${esc(p.status)}">${p.status}</span></td>
                    <td>${p.stage || '—'}</td><td>${p.owner || '—'}</td><td>${p.project_id}</td>
                    <td>${p.create_at ? p.create_at.slice(5,10) : '—'}</td>
                    <td>${p.update_at ? p.update_at.slice(5,10) : '—'}</td>
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

// ─── Settings ──────────────────────────────────────────────────────────────────

function showApiKey() {
    initApiKey();
    document.getElementById('api-key-display').textContent = apiKey || AISP_CONFIG.api_key || 'not set';
}

async function runBackup() {
    const out = document.getElementById('backup-output');
    out.textContent = 'Running backup...';
    try {
        // No backup API yet — just show config
        out.textContent = 'Backup: configure in config.toml [backup] section.';
    } catch (e) { out.textContent = 'Error: ' + e.message; }
}

// ─── Sync Settings ────────────────────────────────────────────────────────────

async function loadSyncConfig() {
    const out = document.getElementById('sync-output');
    out.textContent = 'Loading...';
    try {
        const cfg = await api('GET', '/sync/config');
        if (document.getElementById('sync-api-key')) {
            document.getElementById('sync-api-key').value = '';
        }
        if (document.getElementById('sync-pages-repo')) {
            document.getElementById('sync-pages-repo').value = cfg.sync_target_repo || 'YeLuo45/ai-superpower';
        }
        if (document.getElementById('sync-prj-repo')) {
            const prjEl = document.getElementById('sync-prj-repo');
            // Read from /sync/status to get prj_repo
            try {
                const status = await api('GET', '/sync/status');
                prjEl.value = status.sync_prj_repo || 'YeLuo45/prj-proposals-manager';
            } catch {
                prjEl.value = 'YeLuo45/prj-proposals-manager';
            }
        }
        // Get frequency from /sync/status
        try {
            const status = await api('GET', '/sync/status');
            const freqMap = { 60: '1h', 360: '6h', 720: '12h', 1440: '1d', 0: 'off' };
            const freqEl = document.getElementById('sync-frequency');
            if (freqEl) {
                freqEl.value = freqMap[status.sync_interval_minutes] || 'off';
            }
            if (document.getElementById('sync-last-run')) {
                document.getElementById('sync-last-run').textContent = status.sync_last_run || '—';
            }
        } catch { /* ignore */ }
        out.textContent = 'Loaded.';
        setTimeout(() => { if (out.textContent === 'Loaded.') out.textContent = ''; }, 2000);
    } catch (e) {
        out.textContent = 'Error: ' + e.message;
    }
}

async function saveSyncConfig() {
    const out = document.getElementById('sync-output');
    out.textContent = 'Saving...';
    try {
        const pagesRepo = document.getElementById('sync-pages-repo')?.value || '';
        const prjRepo = document.getElementById('sync-prj-repo')?.value || '';
        const freq = document.getElementById('sync-frequency')?.value || 'off';
        const apiKeyVal = document.getElementById('sync-api-key')?.value || '';

        // Save target_repo + enabled via PUT /api/sync/config
        await api('PUT', '/sync/config', {
            sync_target_repo: pagesRepo,
            sync_enabled: freq !== 'off',
        });

        // Save frequency to config.toml via POST /api/sync/config (app updates in-memory)
        await api('POST', '/sync/config', {
            sync_frequency: freq,
            sync_prj_repo: prjRepo,
            sync_api_key: apiKeyVal,
        });

        out.textContent = 'Saved. Reload page to reflect changes.';
        setTimeout(() => { if (out.textContent.startsWith('Saved.')) out.textContent = ''; }, 3000);
    } catch (e) {
        out.textContent = 'Error: ' + e.message;
    }
}

async function runSyncNow() {
    const out = document.getElementById('sync-output');
    out.textContent = 'Syncing...';
    try {
        const result = await api('POST', '/sync/export', {});
        if (result.status === 'accepted' || result.status === 'done') {
            out.textContent = `Done. Exported ${result.proposals_count} proposals, ${result.projects_count} projects.\nFiles: ${result.files_created}\nLast run: ${result.export_last_run}`;
        } else {
            out.textContent = `Status: ${result.status}\n${result.message || ''}`;
        }
    } catch (e) {
        out.textContent = 'Error: ' + e.message;
    }
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

// ─── Merge ────────────────────────────────────────────────────────────────────

async function showMergeModal() {
    document.getElementById('merge-modal').classList.remove('hidden');
    // Load projects for target dropdown
    try {
        const data = await api('GET', '/projects?page_size=200');
        const sel = document.getElementById('target-project-id');
        sel.innerHTML = data.items.map(p => `<option value="${p.id}">${p.id} - ${p.name}</option>`).join('');
    } catch (e) { alert('Error loading projects: ' + e.message); }
}

function closeMergeModal() {
    document.getElementById('merge-modal').classList.add('hidden');
}

async function submitMergeForm(e) {
    e.preventDefault();
    const sourceName = document.getElementById('source-project-name').value;
    const targetId = document.getElementById('target-project-id').value;
    try {
        const result = await api('POST', '/proposals/merge-by-project', {
            source_project_name: sourceName,
            target_project_id: targetId,
        });
        alert('Merge done: ' + (result.message || JSON.stringify(result)));
        closeMergeModal();
        loadProposals(currentPage.proposals);
    } catch (e) { alert('Error: ' + e.message); }
}

// ─── Duplicate Project Scanner ─────────────────────────────────────────────
function showDuplicatesModal() {
    document.getElementById('duplicates-modal').classList.remove('hidden');
    scanDuplicates();
}

function closeDuplicatesModal() {
    document.getElementById('duplicates-modal').classList.add('hidden');
}

async function scanDuplicates() {
    const listEl = document.getElementById('duplicates-list');
    listEl.innerHTML = '<p style="color: #888;">⏳ Scanning...</p>';
    const caseInsensitive = document.getElementById('dup-case-insensitive').checked;
    try {
        const groups = await api('GET', `/projects/duplicates?case_insensitive=${caseInsensitive}`);
        if (!groups || groups.length === 0) {
            listEl.innerHTML = '<p style="color: green; padding: 16px;">✓ No duplicate project names found.</p>';
            return;
        }
        listEl.innerHTML = groups.map((g, gi) => renderGroup(g, gi)).join('');
        // Wire up per-group buttons
        groups.forEach((g, gi) => {
            const btn = document.getElementById(`merge-btn-${gi}`);
            if (btn) btn.onclick = () => mergeGroup(gi, g);
        });
    } catch (e) {
        listEl.innerHTML = `<p style="color: red;">Error: ${escapeHtml(e.message)}</p>`;
    }
}

function renderGroup(group, idx) {
    const rows = group.projects.map(p => `
        <tr>
            <td><code>${escapeHtml(p.id)}</code></td>
            <td>${escapeHtml(p.name)}</td>
            <td style="font-size: 0.85em; color: #666;">${escapeHtml(p.git_repo || '—')}</td>
            <td style="text-align: center;">${p.proposal_count}</td>
            <td style="font-size: 0.85em;">${escapeHtml(p.create_at || '')}</td>
            <td style="text-align: center;">
                <input type="radio" name="dup-target-${idx}" value="${escapeHtml(p.id)}" ${p === group.projects[0] ? 'checked' : ''}>
                <small>target</small>
            </td>
            <td style="text-align: center;">
                <input type="radio" name="dup-source-${idx}" value="${escapeHtml(p.id)}" ${p !== group.projects[0] ? 'checked' : ''}>
                <small>source</small>
            </td>
        </tr>
    `).join('');
    return `
        <div style="border: 1px solid #ddd; border-radius: 6px; padding: 12px; margin-bottom: 16px;">
            <h3 style="margin: 0 0 8px 0;">
                ${escapeHtml(group.name)}
                <span style="background: #fee; color: #c33; padding: 2px 8px; border-radius: 12px; font-size: 0.8em;">
                    ${group.count} duplicates
                </span>
            </h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
                <thead>
                    <tr style="border-bottom: 2px solid #ddd; text-align: left;">
                        <th>ID</th><th>Name</th><th>Git Repo</th><th style="text-align: center;">Proposals</th><th>Created</th><th>Keep</th><th>Merge from</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            <div style="margin-top: 12px; display: flex; justify-content: space-between; align-items: center;">
                <small style="color: #666;">
                    <b>Target</b> = canonical project to keep. <b>Source</b> = to absorb &amp; delete.
                </small>
                <button id="merge-btn-${idx}" class="primary" style="background: #c33; color: white;">
                    🔀 Merge source → target
                </button>
            </div>
        </div>
    `;
}

async function mergeGroup(idx, group) {
    const targetEl = document.querySelector(`input[name="dup-target-${idx}"]:checked`);
    const sourceEl = document.querySelector(`input[name="dup-source-${idx}"]:checked`);
    if (!targetEl || !sourceEl) {
        alert('Pick both a target and a source');
        return;
    }
    const targetId = targetEl.value;
    const sourceId = sourceEl.value;
    if (targetId === sourceId) {
        alert('Target and source cannot be the same project');
        return;
    }
    const sourceName = group.projects.find(p => p.id === sourceId)?.name || sourceId;
    if (!confirm(`Merge "${sourceName}" (${sourceId}) into ${targetId}?\n\n` +
                 `• All proposals from source will move to target\n` +
                 `• Source project will be DELETED\n` +
                 `• This action cannot be undone`)) return;
    try {
        const result = await api('POST', '/projects/merge', {
            target_id: targetId,
            source_id: sourceId,
            delete_source: true,
        });
        alert(`✓ Merge done!\n\n` +
              `• Moved ${result.merged_proposals} proposal(s)\n` +
              `• Source ${result.source_id} deleted: ${result.deleted_source}\n` +
              `• Audit logged`);
        await scanDuplicates();
        loadProjects(1);
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
