// RelayDesk - Frontend Application

const API_BASE = '';

let currentProject = null;
let projects = [];
let evidenceLog = [];

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initModals();
    initButtons();
    loadProjects();
});

function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const view = item.dataset.view;
            switchView(view);
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
        });
    });
}

function switchView(viewName) {
    document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
    const target = document.getElementById(`${viewName}View`);
    if (target) target.classList.add('active');

    if (viewName === 'projects') {
        loadProjects();
    } else if (viewName === 'timeline' && currentProject) {
        loadProgress(currentProject.project_id);
    } else if (viewName === 'versions' && currentProject) {
        loadVersionStatus(currentProject.project_id);
    } else if (viewName === 'evidence') {
        renderEvidence();
    }
}

function initModals() {
    document.querySelectorAll('[data-modal]').forEach(trigger => {
        trigger.addEventListener('click', () => closeModal(trigger.dataset.modal));
    });
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal(modal.id);
        });
    });
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'flex';
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'none';
}

function initButtons() {
    document.getElementById('createProjectBtn')?.addEventListener('click', () => openModal('createProjectModal'));
    document.getElementById('confirmCreateProject')?.addEventListener('click', createProject);
    document.getElementById('loadDemoBtn')?.addEventListener('click', loadDemoData);
    document.getElementById('addProgressBtn')?.addEventListener('click', () => {
        if (currentProject) openModal('addProgressModal');
    });
    document.getElementById('confirmAddProgress')?.addEventListener('click', addProgress);
    document.getElementById('queryHandoffBtn')?.addEventListener('click', queryHandoff);

    document.getElementById('projectSelector')?.addEventListener('change', (e) => {
        if (e.target.value) selectProject(e.target.value);
    });
    document.getElementById('handoffProjectSelector')?.addEventListener('change', (e) => {
        if (e.target.value) currentProject = projects.find(p => p.project_id === e.target.value);
    });
    document.getElementById('versionsProjectSelector')?.addEventListener('change', (e) => {
        if (e.target.value) loadVersionStatus(e.target.value);
    });
}

// Evidence logging
function logEvidence(operation, data) {
    evidenceLog.unshift({
        operation,
        data,
        timestamp: new Date().toISOString(),
    });
    if (evidenceLog.length > 50) evidenceLog.length = 50;
    renderEvidence();
}

function renderEvidence() {
    const container = document.getElementById('evidenceList');
    if (!container) return;

    if (evidenceLog.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>暂无操作记录</p><p class="hint">执行 PowerContext 操作后，此处将显示实际返回的来源标识、查询结果及时间</p></div>';
        return;
    }

    container.innerHTML = evidenceLog.map(entry => `
        <div class="evidence-item">
            <div class="evidence-item-header">
                <span class="evidence-item-title">${escapeHtml(entry.operation)}</span>
                <span class="evidence-item-time">${formatDate(entry.timestamp)}</span>
            </div>
            <div class="evidence-item-content">${escapeHtml(JSON.stringify(entry.data, null, 2))}</div>
        </div>
    `).join('');
}

// API calls
async function apiCall(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });

    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const errData = await response.json();
            detail = errData.detail || detail;
        } catch (_) { /* use default */ }
        throw new Error(detail);
    }

    return await response.json();
}

// Projects
async function loadProjects() {
    try {
        const data = await apiCall('/api/projects');
        projects = data.projects || [];
        renderProjects();
        updateProjectSelectors();
    } catch (error) {
        showToast('加载项目失败: ' + error.message, 'error');
    }
}

function renderProjects() {
    const container = document.getElementById('projectsList');
    const emptyState = document.getElementById('projectsEmpty');
    if (!container) return;

    if (projects.length === 0) {
        container.style.display = 'none';
        if (emptyState) emptyState.style.display = 'block';
        return;
    }

    container.style.display = 'grid';
    if (emptyState) emptyState.style.display = 'none';

    container.innerHTML = projects.map(project => `
        <div class="card" onclick="selectProject('${escapeAttr(project.project_id)}')">
            <div class="card-header">
                <div>
                    <div class="card-title">${escapeHtml(project.name)}</div>
                    <div class="card-description">${escapeHtml(project.description || '无描述')}</div>
                    ${project.is_demo ? '<div class="demo-badge">虚构样例</div>' : ''}
                </div>
            </div>
            <div class="card-meta">
                <span>Scope: ${escapeHtml(project.scope_id ? project.scope_id.substring(0, 16) + '...' : 'N/A')}</span>
                <span>创建: ${formatDate(project.created_at)}</span>
            </div>
            <div class="card-actions">
                <button class="btn btn-secondary btn-small" onclick="event.stopPropagation(); viewProjectTimeline('${escapeAttr(project.project_id)}')">查看进展</button>
                <button class="btn btn-secondary btn-small" onclick="event.stopPropagation(); viewProjectVersions('${escapeAttr(project.project_id)}')">版本状态</button>
            </div>
        </div>
    `).join('');
}

function updateProjectSelectors() {
    const selectors = [
        document.getElementById('projectSelector'),
        document.getElementById('handoffProjectSelector'),
        document.getElementById('versionsProjectSelector'),
    ];

    selectors.forEach(selector => {
        if (!selector) return;
        const currentValue = selector.value;
        selector.innerHTML = '<option value="">选择项目...</option>' +
            projects.map(p => `<option value="${escapeAttr(p.project_id)}">${escapeHtml(p.name)}</option>`).join('');
        if (currentValue) selector.value = currentValue;
    });
}

async function createProject() {
    const nameInput = document.getElementById('projectName');
    const descInput = document.getElementById('projectDescription');
    const name = nameInput?.value.trim();
    const description = descInput?.value.trim();

    if (!name) {
        showToast('请输入项目名称', 'warning');
        return;
    }

    try {
        const result = await apiCall('/api/projects', {
            method: 'POST',
            body: JSON.stringify({ name, description }),
        });

        logEvidence('create_project', {
            project_id: result.project_id,
            scope_id: result.scope_id,
            name: result.name,
            created_at: result.created_at,
        });

        showToast('项目创建成功', 'success');
        closeModal('createProjectModal');
        if (nameInput) nameInput.value = '';
        if (descInput) descInput.value = '';
        await loadProjects();
    } catch (error) {
        showToast('创建项目失败: ' + error.message, 'error');
    }
}

function selectProject(projectId) {
    currentProject = projects.find(p => p.project_id === projectId);
    if (currentProject) showToast(`已选择项目: ${currentProject.name}`, 'success');
}

function viewProjectTimeline(projectId) {
    selectProject(projectId);
    document.querySelector('[data-view="timeline"]')?.click();
    document.getElementById('projectSelector').value = projectId;
    loadProgress(projectId);
}

function viewProjectVersions(projectId) {
    selectProject(projectId);
    document.querySelector('[data-view="versions"]')?.click();
    document.getElementById('versionsProjectSelector').value = projectId;
    loadVersionStatus(projectId);
}

// Progress
async function loadProgress(projectId) {
    try {
        const data = await apiCall(`/api/projects/${projectId}/progress`);
        renderProgress(data.records || []);
        const addBtn = document.getElementById('addProgressBtn');
        if (addBtn) addBtn.style.display = 'flex';
    } catch (error) {
        showToast('加载进展失败: ' + error.message, 'error');
    }
}

function renderProgress(records) {
    const container = document.getElementById('timelineContent');
    if (!container) return;

    if (records.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>暂无进展记录</p><p class="hint">点击右下角 + 按钮添加新进展</p></div>';
        return;
    }

    container.innerHTML = `<div class="timeline">${records.map(record => `
        <div class="timeline-item">
            <div class="timeline-header">
                <div>
                    <div class="timeline-title">${escapeHtml(record.title)}</div>
                    <span class="record-kind-badge kind-${escapeAttr(record.record_kind || 'progress')}">${escapeHtml(recordKindLabel(record.record_kind))}</span>
                </div>
                <div class="timeline-time">${formatDate(record.recorded_at)}</div>
            </div>
            <div class="timeline-body">${escapeHtml(record.body)}</div>
            <div class="timeline-meta">
                ${record.owner ? `<span class="timeline-meta-item">负责人: ${escapeHtml(record.owner)}</span>` : ''}
                <span class="timeline-meta-item">${getStatusBadge(record.status)}</span>
                ${record.branch ? `<span class="timeline-meta-item">分支: ${escapeHtml(record.branch)}</span>` : ''}
                ${record.commit ? `<span class="timeline-meta-item">Commit: ${escapeHtml(record.commit.substring(0, 8))}</span>` : ''}
                ${record.evaluation_result ? `<span class="timeline-meta-item">评测: ${escapeHtml(record.evaluation_result)}</span>` : ''}
            </div>
            ${record.next_steps ? `<div class="timeline-meta-item" style="margin-top: 8px;">下一步: ${escapeHtml(record.next_steps)}</div>` : ''}
        </div>
    `).join('')}</div>`;
}

function recordKindLabel(kind) {
    const labels = { progress: '进展', code: '代码版本', evaluation: '评测' };
    return labels[kind] || '进展';
}

async function addProgress() {
    if (!currentProject) {
        showToast('请先选择项目', 'warning');
        return;
    }

    const title = document.getElementById('progressTitle')?.value.trim();
    const body = document.getElementById('progressBody')?.value.trim();
    const owner = document.getElementById('progressOwner')?.value.trim();
    const status = document.getElementById('progressStatus')?.value;
    const recordKind = document.getElementById('progressRecordKind')?.value || 'progress';
    const branch = document.getElementById('progressBranch')?.value.trim();
    const commit = document.getElementById('progressCommit')?.value.trim();
    const evaluation = document.getElementById('progressEvaluation')?.value.trim();
    const nextSteps = document.getElementById('progressNextSteps')?.value.trim();

    if (!title || !body) {
        showToast('标题和正文为必填项', 'warning');
        return;
    }

    try {
        const result = await apiCall('/api/progress', {
            method: 'POST',
            body: JSON.stringify({
                project_id: currentProject.project_id,
                title,
                body,
                owner: owner || null,
                status: status || '进行中',
                next_steps: nextSteps || '',
                branch: branch || null,
                commit: commit || null,
                evaluation_result: evaluation || null,
                record_kind: recordKind,
            }),
        });

        logEvidence('create_progress', {
            progress_id: result.progress_id,
            project_id: result.project_id,
            record_kind: result.record_kind,
            source_ref: result.source_ref,
            source_sequence: result.source_sequence,
            recorded_at: result.recorded_at,
        });

        showToast('进展记录已保存', 'success');
        closeModal('addProgressModal');

        ['progressTitle', 'progressBody', 'progressOwner', 'progressBranch', 'progressCommit', 'progressEvaluation', 'progressNextSteps'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const kindSelect = document.getElementById('progressRecordKind');
        if (kindSelect) kindSelect.value = 'progress';

        await loadProgress(currentProject.project_id);
    } catch (error) {
        showToast('保存进展失败: ' + error.message, 'error');
    }
}

// Handoff query
async function queryHandoff() {
    const projectSelector = document.getElementById('handoffProjectSelector');
    const questionInput = document.getElementById('handoffQuestion');
    const resultBox = document.getElementById('handoffResult');
    const loadingEl = document.getElementById('handoffLoading');

    const projectId = projectSelector?.value;
    const question = questionInput?.value.trim();

    if (!projectId) { showToast('请选择项目', 'warning'); return; }
    if (!question) { showToast('请输入问题', 'warning'); return; }

    if (loadingEl) loadingEl.style.display = 'block';
    if (resultBox) resultBox.style.display = 'none';

    try {
        const result = await apiCall('/api/handoff/query', {
            method: 'POST',
            body: JSON.stringify({ project_id: projectId, question }),
        });

        logEvidence('query_handoff', {
            project_id: result.project_id,
            question: result.question,
            context_items_count: result.context_items?.length || 0,
            sources_count: result.sources?.length || 0,
            prepared_context_status: result.prepared_context?.status,
            source_refs: (result.sources || []).map(source => source.source_ref),
            memory_refs: (result.context_items || []).map(item => item.memory_ref),
            entry_ids: (result.context_items || []).map(item => item.entry_id),
            summary: result.summary,
            timestamp: result.timestamp,
        });

        renderHandoffResult(result);
        if (resultBox) resultBox.style.display = 'block';
    } catch (error) {
        showToast('查询失败: ' + error.message, 'error');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

function renderHandoffResult(result) {
    const resultBox = document.getElementById('handoffResult');
    if (!resultBox) return;

    const hasMatches = result.context_items && result.context_items.length > 0;
    const hasSources = result.sources && result.sources.length > 0;
    const hasRecent = result.recent_progress && result.recent_progress.length > 0;
    const preparedReady = result.prepared_context && result.prepared_context.status === 'ready';

    resultBox.innerHTML = `
        <div class="result-section">
            <h4>摘要</h4>
            <div class="result-item">
                <div class="result-item-content">${escapeHtml(result.summary)}</div>
            </div>
        </div>

        ${hasMatches ? `
            <div class="result-section">
                <h4>PowerContext 记忆命中 (${result.context_items.length})</h4>
                ${result.context_items.map(item => `
                    <details class="result-item">
                        <summary>
                            <strong>Entry:</strong> ${escapeHtml(item.entry_id)} | Score: ${(item.score || 0).toFixed(2)}
                        </summary>
                        <div class="result-item-content" style="margin-top: 8px;">${escapeHtml(item.content)}</div>
                        <div style="margin-top: 8px; font-size: 12px; color: var(--text-gray);">
                            artifact_id: ${escapeHtml(item.memory_ref?.artifact_id || 'N/A')}<br>
                            revision: ${escapeHtml(String(item.memory_ref?.revision || 'N/A'))}
                        </div>
                    </details>
                `).join('')}
            </div>
        ` : ''}

        ${hasSources ? `
            <div class="result-section">
                <h4>来源引用 (${result.sources.length}) - 原生 SourceRef 链路</h4>
                ${result.sources.map(source => `
                    <details class="result-item citation-item">
                        <summary>
                            <strong>${escapeHtml(source.title)}</strong>
                            <span class="record-kind-badge kind-${escapeAttr(source.record_kind || 'progress')}" style="margin-left: 8px;">${escapeHtml(recordKindLabel(source.record_kind))}</span>
                        </summary>
                        <div class="result-item-content" style="margin-top: 8px;">${escapeHtml(source.body)}</div>
                        <div style="margin-top: 8px; font-size: 12px; color: var(--text-gray);">
                            状态: ${getStatusBadge(source.status)} | 时间: ${formatDate(source.recorded_at)}<br>
                            progress_id: ${escapeHtml(source.progress_id)}<br>
                            source_ref: ${escapeHtml(JSON.stringify(source.source_ref))}<br>
                            memory_ref: ${escapeHtml(JSON.stringify(source.memory_ref))}<br>
                            entry_id: ${escapeHtml(source.entry_id || 'N/A')}<br>
                            entry_version_id: ${escapeHtml(source.entry_version_id || 'N/A')}
                        </div>
                    </details>
                `).join('')}
            </div>
        ` : ''}

        ${preparedReady ? `
            <div class="result-section">
                <h4>Prepared Context (PowerContext 生成，非模型推理)</h4>
                <details class="result-item">
                    <summary>状态: ${escapeHtml(result.prepared_context.status)} - 展开查看</summary>
                    <pre class="prepared-context-content">${escapeHtml(result.prepared_context.content || '')}</pre>
                    <div style="margin-top: 8px; font-size: 12px; color: var(--text-gray);">
                        ${escapeHtml(result.prepared_context.note || '')}
                    </div>
                </details>
            </div>
        ` : ''}

        ${hasRecent ? `
            <div class="result-section">
                <h4>最近进展 (非查询匹配)</h4>
                ${result.recent_progress.map(rp => `
                    <div class="result-item recent-progress-item">
                        <div class="result-item-title">${escapeHtml(rp.title)}</div>
                        <div class="result-item-content">${escapeHtml(rp.body)}</div>
                        <div style="margin-top: 4px; font-size: 12px; color: var(--text-gray);">
                            ${escapeHtml(rp.note || '最近进展')} | ${formatDate(rp.recorded_at)}
                        </div>
                    </div>
                `).join('')}
            </div>
        ` : ''}

        <div style="margin-top: 16px; text-align: right;">
            <button class="btn btn-secondary btn-small" onclick="copyHandoffResult()">复制摘要</button>
            <button class="btn btn-secondary btn-small" onclick="downloadHandoffResult()">下载 JSON</button>
        </div>
    `;

    window._lastHandoffResult = result;
}

function copyHandoffResult() {
    if (!window._lastHandoffResult) return;
    const r = window._lastHandoffResult;
    const text = `交接查询结果\n\n问题: ${r.question}\n摘要: ${r.summary}\n\n来源数量: ${r.sources?.length || 0}\n记忆条目: ${r.context_items?.length || 0}\nPrepared context: ${r.prepared_context?.status || 'N/A'}`;
    navigator.clipboard.writeText(text).then(() => showToast('已复制到剪贴板', 'success')).catch(() => showToast('复制失败', 'error'));
}

function downloadHandoffResult() {
    if (!window._lastHandoffResult) return;
    const json = JSON.stringify(window._lastHandoffResult, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `handoff-${window._lastHandoffResult.project_id}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('已下载', 'success');
}

// Version status
async function loadVersionStatus(projectId) {
    const container = document.getElementById('versionsContent');
    if (container) container.innerHTML = '<div class="loading-state">加载中...</div>';
    try {
        const result = await apiCall(`/api/projects/${projectId}/versions`);

        logEvidence('get_version_status', {
            project_id: result.project_id,
            has_no_code_records: result.has_no_code_records,
            has_no_evaluation_records: result.has_no_evaluation_records,
            has_unevaluated_updates: result.has_unevaluated_updates,
            branch_differs: result.branch_differs,
            commit_differs: result.commit_differs,
            status_description: result.status_description,
            latest_code_commit: result.latest_code?.commit,
            latest_eval_commit: result.latest_evaluation?.commit,
        });

        renderVersionStatus(result);
    } catch (error) {
        if (container) container.innerHTML = `<div class="error-state">加载版本状态失败: ${escapeHtml(error.message)}</div>`;
    }
}

function renderVersionStatus(result) {
    const container = document.getElementById('versionsContent');
    if (!container) return;

    container.innerHTML = `
        <div class="version-status-description">
            <strong>状态:</strong> ${escapeHtml(result.status_description)}
        </div>

        <div class="version-comparison">
            <div class="version-box">
                <h4>最新代码版本</h4>
                ${result.latest_code ? `
                    <div class="version-info">
                        <div class="version-info-item"><strong>Commit:</strong> ${escapeHtml(result.latest_code.commit)}</div>
                        ${result.latest_code.branch ? `<div class="version-info-item"><strong>分支:</strong> ${escapeHtml(result.latest_code.branch)}</div>` : ''}
                        <div class="version-info-item"><strong>时间:</strong> ${formatDate(result.latest_code.recorded_at)}</div>
                        <div class="version-info-item"><strong>Progress ID:</strong> ${escapeHtml(result.latest_code.progress_id)}</div>
                    </div>
                ` : '<div class="version-info"><p>暂无代码版本记录</p></div>'}
            </div>

            <div class="version-box">
                <h4>最近评测版本</h4>
                ${result.latest_evaluation ? `
                    <div class="version-info">
                        <div class="version-info-item"><strong>评测结果:</strong> ${escapeHtml(result.latest_evaluation.evaluation_result)}</div>
                        ${result.latest_evaluation.commit ? `<div class="version-info-item"><strong>Commit:</strong> ${escapeHtml(result.latest_evaluation.commit)}</div>` : ''}
                        ${result.latest_evaluation.branch ? `<div class="version-info-item"><strong>分支:</strong> ${escapeHtml(result.latest_evaluation.branch)}</div>` : ''}
                        <div class="version-info-item"><strong>时间:</strong> ${formatDate(result.latest_evaluation.recorded_at)}</div>
                    </div>
                ` : '<div class="version-info"><p>暂无评测记录</p></div>'}
            </div>
        </div>

        ${result.has_no_code_records ? `
            <div class="version-warning warning-info">暂无代码版本记录</div>
        ` : ''}

        ${result.has_no_evaluation_records && !result.has_no_code_records ? `
            <div class="version-warning warning-severe">有代码版本但从未评测</div>
        ` : ''}

        ${result.has_unevaluated_updates ? `
            <div class="version-warning warning-amber">
                有未评测更新
                ${result.branch_differs ? '，分支不同' : ''}
                ${result.commit_differs ? '，commit 不同' : ''}
            </div>
        ` : ''}

        <div class="version-counts">
            进展记录: ${result.total_progress_records} | 代码记录: ${result.total_code_records} | 评测记录: ${result.total_evaluation_records}
        </div>
    `;
}

// Demo data
async function loadDemoData() {
    const btn = document.getElementById('loadDemoBtn');
    if (btn) { btn.disabled = true; btn.textContent = '加载中...'; }
    try {
        const result = await apiCall('/api/demo/load', {
            method: 'POST',
            body: JSON.stringify({}),
        });

        logEvidence('load_demo_data', {
            status: result.status,
            project_id: result.project_id,
            records_created: result.records_created,
            message: result.message,
        });

        if (result.status === 'already_loaded') {
            showToast(result.message, 'warning');
        } else {
            showToast(`${result.message}（虚构样例，非本作品实测效果）`, 'success');
        }
        await loadProjects();
    } catch (error) {
        showToast('加载演示数据失败: ' + error.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '载入演示数据'; }
    }
}

// Utilities
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function escapeAttr(text) {
    if (!text) return '';
    return String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatDate(dateString) {
    if (!dateString) return '未知';
    try {
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return dateString;
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            timeZoneName: 'short',
        });
    } catch {
        return dateString;
    }
}

function getStatusBadge(status) {
    const statusMap = {
        '已完成': 'status-completed',
        '进行中': 'status-in-progress',
        '待处理': 'status-pending',
        '已阻塞': 'status-blocked',
    };
    const className = statusMap[status] || 'status-pending';
    return `<span class="status-badge ${className}">${escapeHtml(status || '未知')}</span>`;
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(400px)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
