/* ═══════════════════════════════════════════════════════════════════════════
   FocusFlow — Frontend JS
   ═══════════════════════════════════════════════════════════════════════════ */

/* ─── State ─────────────────────────────────────────────────────────────── */
let tasks      = [];
let filter     = 'all';
let currentTask = null;
let analyzeTimeout = null;

/* ─── Boot ──────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  updateDate();
  loadUserInfo();
  loadTasks();
  loadReport();
  loadFocusTasks();
});

async function loadUserInfo() {
  try {
    const r = await fetch('/api/auth/me');
    if (r.status === 401) { window.location.href = '/login'; return; }
    const d = await r.json();
    document.getElementById('userName').textContent  = d.name || 'User';
    document.getElementById('userEmail').textContent = d.email || '';
    document.getElementById('userAvatar').textContent = (d.name || 'U')[0].toUpperCase();
  } catch(e) { console.error(e); }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
}

function updateDate() {
  const d = new Date();
  document.getElementById('pageDate').textContent =
    d.toLocaleDateString('en-GB', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

/* ─── Navigation ────────────────────────────────────────────────────────── */
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  document.querySelector(`[data-view="${name}"]`).classList.add('active');
  document.getElementById('pageTitle').textContent = {
    dashboard: 'Dashboard', tasks: 'My Tasks', focus: 'Focus Mode', insights: 'AI Insights'
  }[name];
  if (name === 'tasks')    renderTasks();
  if (name === 'focus')    loadFocusTasks();
  if (name === 'insights') loadReport();
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

/* ─── API helpers ───────────────────────────────────────────────────────── */
async function api(path, method='GET', body=null) {
  const opts = { method, headers: {'Content-Type':'application/json'} };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch('/api' + path, opts);
  if (r.status === 401) { window.location.href = '/login'; return {}; }
  return r.json();
}

/* ─── Load tasks ────────────────────────────────────────────────────────── */
async function loadTasks() {
  tasks = await api('/tasks');
  renderDashboard();
  renderTasks();
}

/* ─── Dashboard ─────────────────────────────────────────────────────────── */
async function renderDashboard() {
  const done      = tasks.filter(t => t.status === 'done');
  const inProg    = tasks.filter(t => t.status === 'in_progress');
  const now       = new Date().toISOString().split('T')[0];
  const overdue   = tasks.filter(t => t.status !== 'done' && t.due_date && t.due_date < now);

  document.getElementById('statTotal').textContent    = tasks.length;
  document.getElementById('statDone').textContent     = done.length;
  document.getElementById('statProgress').textContent = inProg.length;
  document.getElementById('statOverdue').textContent  = overdue.length;

  // Recent tasks (last 5)
  const recent = [...tasks].sort((a,b)=> b.created_at.localeCompare(a.created_at)).slice(0,5);
  const miniList = document.getElementById('recentTasks');
  if (!recent.length) {
    miniList.innerHTML = '<p class="muted" style="font-size:13px;padding:10px 0">No tasks yet — add your first one!</p>';
  } else {
    miniList.innerHTML = recent.map(t => `
      <div class="task-mini" onclick="openDetail('${t.id}')">
        <div class="task-mini-dot" style="background:${priorityColor(t.priority)}"></div>
        <span class="task-mini-title">${esc(t.title)}</span>
        <span class="task-mini-badge badge badge-status-${t.status}">${statusLabel(t.status)}</span>
      </div>`).join('');
  }
}

async function loadReport() {
  const r = await api('/report');

  document.getElementById('insightBox').textContent   = r.insight;
  document.getElementById('motivationalText').textContent = r.motivational;
  document.getElementById('completionPct').textContent = r.completion_rate + '%';
  document.getElementById('progressBarFill').style.width = r.completion_rate + '%';

  // streak badge
  document.getElementById('streakCount').textContent = r.streak;

  // category breakdown
  const cats  = {};
  tasks.forEach(t => { cats[t.category] = (cats[t.category]||0)+1; });
  document.getElementById('categoryBreakdown').innerHTML = Object.entries(cats)
    .map(([c,n]) => `<span class="cat-chip">${capitalize(c)}: ${n}</span>`).join('');

  // Insights view
  document.getElementById('insightMainText').textContent  = r.insight;
  document.getElementById('insightRateVal').textContent   = r.completion_rate + '%';
  document.getElementById('insightStreakVal').textContent = r.streak + ' days';
  document.getElementById('insightFocusVal').textContent  = r.focus_minutes + ' min';
  document.getElementById('insightTopVal').textContent    = capitalize(r.top_category);

  // Priority bars
  const counts = {critical:0, high:0, medium:0, low:0};
  tasks.forEach(t => { if (counts[t.priority] !== undefined) counts[t.priority]++; });
  const total  = tasks.length || 1;
  const colors = {critical:'var(--red)', high:'var(--accent)', medium:'var(--yellow)', low:'var(--green)'};
  document.getElementById('priorityBars').innerHTML = Object.entries(counts).map(([p,n]) => `
    <div class="priority-bar-row">
      <span class="priority-bar-label">${capitalize(p)}</span>
      <div class="priority-bar-track">
        <div class="priority-bar-fill" style="width:${Math.round(n/total*100)}%;background:${colors[p]}"></div>
      </div>
      <span class="priority-bar-count">${n}</span>
    </div>`).join('');
}

/* ─── Task List ─────────────────────────────────────────────────────────── */
function filterTasks(f, el) {
  filter = f;
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  renderTasks();
}

function renderTasks() {
  const search = (document.getElementById('searchInput')?.value || '').toLowerCase();
  let list = tasks;
  if (filter !== 'all') list = list.filter(t => t.status === filter);
  if (search) list = list.filter(t => t.title.toLowerCase().includes(search) ||
                                      (t.description||'').toLowerCase().includes(search));

  const grid  = document.getElementById('taskGrid');
  const empty = document.getElementById('emptyState');

  if (!list.length) {
    grid.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  grid.innerHTML = list.map(t => {
    const now    = new Date().toISOString().split('T')[0];
    const isOver = t.status !== 'done' && t.due_date && t.due_date < now;
    return `
    <div class="task-card priority-${t.priority} ${t.status==='done'?'done':''}"
         onclick="openDetail('${t.id}')">
      <div class="card-top">
        <div class="card-title ${t.status==='done'?'done':''}">${esc(t.title)}</div>
        <div class="card-badges">
          <span class="badge badge-${t.priority}">${t.priority}</span>
          <span class="badge badge-status-${t.status}">${statusLabel(t.status)}</span>
        </div>
      </div>
      ${t.description ? `<div class="card-desc">${esc(t.description)}</div>` : ''}
      <div class="card-footer">
        <span class="card-cat">${capitalize(t.category)}</span>
        <span>${isOver ? '⚠ Overdue' : t.due_date ? '📅 ' + t.due_date : '~' + t.duration + ' min'}</span>
      </div>
    </div>`;
  }).join('');
}

/* ─── Task Detail Modal ─────────────────────────────────────────────────── */
function openDetail(id) {
  currentTask = tasks.find(t => t.id === id);
  if (!currentTask) return;
  const t = currentTask;

  document.getElementById('detailTitle').textContent = t.title;
  document.getElementById('detailMeta').textContent  =
    `${capitalize(t.category)} • ${capitalize(t.priority)} priority • ~${t.duration} min • Created ${formatDate(t.created_at)}`;

  // Body
  document.getElementById('detailBody').innerHTML = `
    ${t.description ? `<p style="font-size:14px;color:var(--text-2);margin-bottom:16px;line-height:1.7">${esc(t.description)}</p>` : ''}
    <div class="ai-suggestion">
      <strong style="color:var(--accent);font-size:11px;text-transform:uppercase;letter-spacing:.5px">AI Suggestion</strong><br>
      ${esc(t.suggestion)}
    </div>
    <h4 style="font-family:var(--font-head);font-size:13px;margin-bottom:8px;color:var(--text-3);text-transform:uppercase;letter-spacing:.5px">Subtasks</h4>
    <div class="subtask-list" id="subtaskList">
      ${t.subtasks.map((s,i) => `
        <div class="subtask-item ${s.done?'done-sub':''}" onclick="toggleSubtask('${t.id}',${i})">
          <div class="subtask-cb">${s.done?'✓':''}</div>
          ${esc(s.text)}
        </div>`).join('')}
    </div>
    ${t.due_date ? `<p style="font-size:13px;color:var(--text-3);margin-top:14px">📅 Due: ${t.due_date}</p>` : ''}
  `;

  // Status buttons
  const statuses = ['pending','in_progress','done'];
  document.getElementById('statusBtns').innerHTML = statuses.map(s => `
    <button class="${t.status===s?'active-status':''}" onclick="setStatus('${t.id}','${s}')">
      ${statusLabel(s)}
    </button>`).join('');

  document.getElementById('detailOverlay').classList.add('open');
}

async function toggleSubtask(taskId, idx) {
  const updated = await api(`/subtask/${taskId}/${idx}`, 'PATCH');
  tasks = tasks.map(t => t.id === taskId ? updated : t);
  openDetail(taskId);          // re-render detail
  renderDashboard();
}

async function setStatus(taskId, status) {
  const updated = await api(`/tasks/${taskId}`, 'PATCH', {status});
  tasks = tasks.map(t => t.id === taskId ? updated : t);
  openDetail(taskId);
  renderTasks();
  renderDashboard();
  loadReport();
}

async function deleteCurrentTask() {
  if (!currentTask) return;
  await api(`/tasks/${currentTask.id}`, 'DELETE');
  tasks = tasks.filter(t => t.id !== currentTask.id);
  closeDetail();
  renderTasks();
  renderDashboard();
  loadReport();
}

function closeDetail(e) {
  if (e && e.target !== document.getElementById('detailOverlay')) return;
  document.getElementById('detailOverlay').classList.remove('open');
  currentTask = null;
}

/* ─── Add Task Modal ────────────────────────────────────────────────────── */
function openModal() {
  document.getElementById('taskTitle').value   = '';
  document.getElementById('taskDesc').value    = '';
  document.getElementById('taskDue').value     = '';
  document.getElementById('taskPriority').value = '';
  document.getElementById('aiPreviewBody').innerHTML =
    '<span class="muted">Start typing a task title to see AI suggestions…</span>';
  document.getElementById('modalOverlay').classList.add('open');
  document.getElementById('taskTitle').focus();
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modalOverlay')) return;
  document.getElementById('modalOverlay').classList.remove('open');
}

function liveAnalyze() {
  clearTimeout(analyzeTimeout);
  const title = document.getElementById('taskTitle').value.trim();
  if (!title) {
    document.getElementById('aiPreviewBody').innerHTML =
      '<span class="muted">Start typing a task title to see AI suggestions…</span>';
    return;
  }
  document.getElementById('aiPreviewBody').innerHTML =
    '<span class="muted">Analysing…</span>';
  analyzeTimeout = setTimeout(async () => {
    const r = await api('/analyze', 'POST', {
      title, description: document.getElementById('taskDesc').value
    });
    document.getElementById('aiPreviewBody').innerHTML = `
      <div class="ai-row">
        <div class="ai-item"><div class="ai-item-label">Priority</div><div class="ai-item-value">${capitalize(r.priority)}</div></div>
        <div class="ai-item"><div class="ai-item-label">Category</div><div class="ai-item-value">${capitalize(r.category)}</div></div>
        <div class="ai-item"><div class="ai-item-label">Est. Time</div><div class="ai-item-value">${r.duration} min</div></div>
      </div>
      <div class="ai-suggestion">${esc(r.suggestion)}</div>
      <div class="ai-subtasks">
        ${r.subtasks.map(s => `<div class="ai-subtask-item">${esc(s)}</div>`).join('')}
      </div>`;
  }, 450);
}

async function submitTask() {
  const title = document.getElementById('taskTitle').value.trim();
  if (!title) { document.getElementById('taskTitle').focus(); return; }
  const task = await api('/tasks', 'POST', {
    title,
    description: document.getElementById('taskDesc').value.trim(),
    due_date:    document.getElementById('taskDue').value,
    priority:    document.getElementById('taskPriority').value || null
  });
  tasks.unshift(task);
  closeModal();
  renderTasks();
  renderDashboard();
  loadReport();
}

/* ─── Focus Mode ────────────────────────────────────────────────────────── */
let timerInterval  = null;
let timerSeconds   = 25 * 60;
let timerTotal     = 25 * 60;
let timerRunning   = false;
let timerModeName  = 'Focus';
let selectedTaskId = null;
let sessionsToday  = 0;

function loadFocusTasks() {
  const pending = tasks.filter(t => t.status !== 'done').slice(0, 8);
  document.getElementById('focusTaskList').innerHTML = !pending.length
    ? '<p class="muted" style="font-size:13px;padding:10px 0">No pending tasks.</p>'
    : pending.map(t => `
      <div class="focus-task-item ${selectedTaskId===t.id?'selected':''}"
           id="ftask-${t.id}" onclick="selectFocusTask('${t.id}')">
        <strong style="font-size:13px">${esc(t.title)}</strong>
        <span style="font-size:11px;color:var(--text-3);margin-left:8px">~${t.duration} min</span>
      </div>`).join('');
}

function selectFocusTask(id) {
  selectedTaskId = id;
  document.querySelectorAll('.focus-task-item').forEach(el => el.classList.remove('selected'));
  const el = document.getElementById('ftask-' + id);
  if (el) el.classList.add('selected');
}

function setMode(mins, name, el) {
  if (timerRunning) return;
  timerSeconds  = mins * 60;
  timerTotal    = mins * 60;
  timerModeName = name;
  document.querySelectorAll('.option-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  updateTimerDisplay();
  document.getElementById('timerLabel').textContent = name;
  document.getElementById('timerArc').style.strokeDashoffset = '0';
  document.getElementById('timerArc').style.stroke =
    name === 'Focus' ? '#f97316' : name === 'Short Break' ? '#22c55e' : '#3b82f6';
}

function startTimer() {
  if (timerRunning) {
    clearInterval(timerInterval);
    timerRunning = false;
    document.getElementById('btnStart').textContent = '▶ Start';
    document.getElementById('timerLabel').textContent = 'Paused';
  } else {
    timerRunning = true;
    document.getElementById('btnStart').textContent = '⏸ Pause';
    document.getElementById('timerLabel').textContent = timerModeName;
    timerInterval = setInterval(tickTimer, 1000);
  }
}

function tickTimer() {
  timerSeconds--;
  updateTimerDisplay();
  updateTimerArc();
  if (timerSeconds <= 0) {
    clearInterval(timerInterval);
    timerRunning = false;
    document.getElementById('btnStart').textContent = '▶ Start';
    document.getElementById('timerLabel').textContent = 'Done!';
    if (timerModeName === 'Focus') {
      const mins = Math.round(timerTotal / 60);
      api('/focus/log', 'POST', {minutes: mins, task_id: selectedTaskId || ''});
      sessionsToday++;
      document.getElementById('focusSessions').textContent = sessionsToday;
      const total = parseInt(document.getElementById('focusTotal').textContent || '0') + mins;
      document.getElementById('focusTotal').textContent = total;
    }
  }
}

function updateTimerDisplay() {
  const m = Math.floor(timerSeconds / 60).toString().padStart(2,'0');
  const s = (timerSeconds % 60).toString().padStart(2,'0');
  document.getElementById('timerDisplay').textContent = `${m}:${s}`;
}

function updateTimerArc() {
  const circ   = 2 * Math.PI * 88;   // r=88
  const offset = circ * (1 - timerSeconds / timerTotal);
  document.getElementById('timerArc').style.strokeDashoffset = offset;
}

function resetTimer() {
  clearInterval(timerInterval);
  timerRunning = false;
  timerSeconds = timerTotal;
  document.getElementById('btnStart').textContent = '▶ Start';
  document.getElementById('timerLabel').textContent = 'Ready';
  updateTimerDisplay();
  document.getElementById('timerArc').style.strokeDashoffset = '0';
}

/* ─── Utility ───────────────────────────────────────────────────────────── */
function priorityColor(p) {
  return {critical:'#f43f5e', high:'#f97316', medium:'#facc15', low:'#22c55e'}[p] || '#555b72';
}

function statusLabel(s) {
  return {pending:'Pending', in_progress:'In Progress', done:'Done'}[s] || s;
}

function capitalize(s) {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1).replace('_',' ');
}

function formatDate(iso) {
  return new Date(iso).toLocaleDateString('en-GB', {day:'numeric', month:'short'});
}

function esc(str) {
  return (str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
