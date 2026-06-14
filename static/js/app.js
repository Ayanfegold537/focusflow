/* ═══════════════════════════════════════════════════════════════════════════
   FocusFlow — Frontend JS (Enhanced)
   ═══════════════════════════════════════════════════════════════════════════ */

/* ─── State ─────────────────────────────────────────────────────────────── */
let tasks         = [];
let filter        = 'all';
let currentTask   = null;
let analyzeTimeout = null;

/* ─── Boot ──────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  updateDate();
  loadUserInfo();
  loadTasks();
  loadReport();
  loadFocusTasks();
});

function updateDate() {
  const d = new Date();
  document.getElementById('pageDate').textContent =
    d.toLocaleDateString('en-GB', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

/* ─── Auth ──────────────────────────────────────────────────────────────── */
async function loadUserInfo() {
  try {
    const r = await fetch('/api/auth/me');
    if (r.status === 401) { window.location.href = '/login'; return; }
    const d = await r.json();
    const name  = d.name  || 'User';
    const email = d.email || '';
    document.getElementById('userName').textContent  = name;
    document.getElementById('userEmail').textContent = email;
    document.getElementById('userAvatar').textContent = name[0].toUpperCase();
    // profile page
    document.getElementById('profileAvatarBig').textContent = name[0].toUpperCase();
    document.getElementById('profileNameBig').textContent   = name;
    document.getElementById('profileEmailBig').textContent  = email;
    if (d.created) {
      const joined = new Date(d.created).toLocaleDateString('en-GB',
        { day:'numeric', month:'long', year:'numeric' });
      document.getElementById('profileJoined').textContent = 'Member since ' + joined;
    }
    // greeting
    setGreeting(name);
  } catch(e) { console.error(e); }
}

function setGreeting(name) {
  const h = new Date().getHours();
  const g = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  const first = name.split(' ')[0];
  document.getElementById('greetingText').textContent = `${g}, ${first}! 👋`;
  const pending = tasks.filter(t => t.status !== 'done').length;
  const overdue = tasks.filter(t => t.status !== 'done' && t.due_date &&
    t.due_date < new Date().toISOString().split('T')[0]).length;
  let sub = 'Here is your productivity overview.';
  if (overdue > 0)       sub = `You have ${overdue} overdue task${overdue>1?'s':''} — let\'s tackle them first.`;
  else if (pending > 0)  sub = `You have ${pending} task${pending>1?'s':''} waiting. Let\'s get to work!`;
  else if (tasks.length) sub = 'All caught up! Great job staying on top of things.';
  document.getElementById('greetingSub').textContent = sub;
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
}

/* ─── API helpers ───────────────────────────────────────────────────────── */
async function api(path, method='GET', body=null) {
  const opts = { method, headers: {'Content-Type':'application/json'} };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch('/api' + path, opts);
  if (r.status === 401) { window.location.href = '/login'; return {}; }
  return r.json();
}

/* ─── Navigation ────────────────────────────────────────────────────────── */
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  document.querySelector(`[data-view="${name}"]`).classList.add('active');
  document.getElementById('pageTitle').textContent = {
    dashboard:'Dashboard', tasks:'My Tasks', focus:'Focus Mode',
    insights:'AI Insights', profile:'My Profile', assistant:'AI Assistant'
  }[name] || name;
  // close sidebar on mobile after navigation
  if (window.innerWidth <= 640) {
    document.getElementById('sidebar').classList.remove('open');
  }
  if (name === 'tasks')     renderTasks();
  if (name === 'focus')     loadFocusTasks();
  if (name === 'insights')  loadReport();
  if (name === 'profile')   loadProfileStats();
  if (name === 'assistant') initAssistant();
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

// close sidebar when clicking outside it on mobile
document.addEventListener('click', function(e) {
  const sidebar = document.getElementById('sidebar');
  const hamburger = document.querySelector('.hamburger');
  if (window.innerWidth <= 640 &&
      sidebar.classList.contains('open') &&
      !sidebar.contains(e.target) &&
      e.target !== hamburger) {
    sidebar.classList.remove('open');
  }
});

/* ─── Overdue Banner ────────────────────────────────────────────────────── */
function checkOverdueBanner() {
  const now     = new Date().toISOString().split('T')[0];
  const overdue = tasks.filter(t => t.status !== 'done' && t.due_date && t.due_date < now);
  const banner  = document.getElementById('overdueBanner');
  if (overdue.length > 0) {
    document.getElementById('overdueText').textContent =
      `You have ${overdue.length} overdue task${overdue.length>1?'s':''} that need your attention.`;
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }
}

function hideOverdueBanner() {
  document.getElementById('overdueBanner').classList.add('hidden');
}

/* ─── Load tasks ────────────────────────────────────────────────────────── */
async function loadTasks() {
  tasks = await api('/tasks');
  if (!tasks) tasks = [];
  renderDashboard();
  renderTasks();
  updateNavBadges();
  checkOverdueBanner();
  setGreeting(document.getElementById('userName').textContent || 'there');
}

function updateNavBadges() {
  const pending = tasks.filter(t => t.status === 'pending').length;
  const badge   = document.getElementById('navBadgeTasks');
  if (pending > 0) {
    badge.textContent = pending;
    badge.style.display = 'inline-flex';
  } else {
    badge.style.display = 'none';
  }
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

  // colour overdue card red if > 0
  const overdueCard = document.getElementById('statOverdue').closest('.stat-card');
  if (overdue.length > 0) overdueCard.style.setProperty('--accent','#f43f5e');

  const recent    = [...tasks].sort((a,b)=> b.created_at.localeCompare(a.created_at)).slice(0,5);
  const miniList  = document.getElementById('recentTasks');
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
  if (!r || !r.insight) return;

  document.getElementById('insightBox').textContent      = r.insight;
  document.getElementById('motivationalText').textContent = r.motivational;
  document.getElementById('completionPct').textContent    = r.completion_rate + '%';
  document.getElementById('progressBarFill').style.width  = r.completion_rate + '%';
  document.getElementById('streakCount').textContent      = r.streak;

  const cats = {};
  tasks.forEach(t => { cats[t.category] = (cats[t.category]||0)+1; });
  document.getElementById('categoryBreakdown').innerHTML = Object.entries(cats)
    .map(([c,n]) => `<span class="cat-chip">${capitalize(c)}: ${n}</span>`).join('');

  document.getElementById('insightMainText').textContent  = r.insight;
  document.getElementById('insightRateVal').textContent   = r.completion_rate + '%';
  document.getElementById('insightStreakVal').textContent = r.streak + ' days';
  document.getElementById('insightFocusVal').textContent  = r.focus_minutes + ' min';
  document.getElementById('insightTopVal').textContent    = capitalize(r.top_category);

  const counts = {critical:0,high:0,medium:0,low:0};
  tasks.forEach(t => { if (counts[t.priority]!==undefined) counts[t.priority]++; });
  const total  = tasks.length || 1;
  const colors = {critical:'var(--red)',high:'var(--accent)',medium:'var(--yellow)',low:'var(--green)'};
  document.getElementById('priorityBars').innerHTML = Object.entries(counts).map(([p,n]) => `
    <div class="priority-bar-row">
      <span class="priority-bar-label">${capitalize(p)}</span>
      <div class="priority-bar-track">
        <div class="priority-bar-fill" style="width:${Math.round(n/total*100)}%;background:${colors[p]}"></div>
      </div>
      <span class="priority-bar-count">${n}</span>
    </div>`).join('');
}

/* ─── Profile ───────────────────────────────────────────────────────────── */
function loadProfileStats() {
  const done    = tasks.filter(t => t.status === 'done').length;
  const streak  = parseInt(document.getElementById('streakCount').textContent) || 0;
  const focus   = parseInt(document.getElementById('focusTotal').textContent)  || 0;
  document.getElementById('pstatTotal').textContent  = tasks.length;
  document.getElementById('pstatDone').textContent   = done;
  document.getElementById('pstatFocus').textContent  = focus;
  document.getElementById('pstatStreak').textContent = streak;
}

async function changePassword() {
  const currentPw = document.getElementById('currentPw').value;
  const newPw     = document.getElementById('newPw').value;
  const confirmPw = document.getElementById('confirmPw').value;
  const errEl     = document.getElementById('pwError');
  const sucEl     = document.getElementById('pwSuccess');
  errEl.classList.add('hidden');
  sucEl.classList.add('hidden');
  if (!currentPw || !newPw || !confirmPw) {
    errEl.textContent = 'Please fill in all fields.';
    errEl.classList.remove('hidden'); return;
  }
  if (newPw !== confirmPw) {
    errEl.textContent = 'New passwords do not match.';
    errEl.classList.remove('hidden'); return;
  }
  if (newPw.length < 6) {
    errEl.textContent = 'New password must be at least 6 characters.';
    errEl.classList.remove('hidden'); return;
  }
  const r = await api('/auth/change-password', 'POST',
    { current_password: currentPw, new_password: newPw });
  if (r.error) {
    errEl.textContent = r.error;
    errEl.classList.remove('hidden');
  } else {
    sucEl.textContent = 'Password updated successfully!';
    sucEl.classList.remove('hidden');
    document.getElementById('currentPw').value = '';
    document.getElementById('newPw').value     = '';
    document.getElementById('confirmPw').value = '';
  }
}

/* ─── Task List ─────────────────────────────────────────────────────────── */
function filterTasks(f, el) {
  filter = f;
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  if (el) el.classList.add('active');
  renderTasks();
}

function renderTasks() {
  const search = (document.getElementById('searchInput')?.value || '').toLowerCase();
  let list     = tasks;
  if (filter !== 'all') list = list.filter(t => t.status === filter);
  if (search) list = list.filter(t =>
    t.title.toLowerCase().includes(search) ||
    (t.description||'').toLowerCase().includes(search) ||
    (t.category||'').toLowerCase().includes(search));

  const grid  = document.getElementById('taskGrid');
  const empty = document.getElementById('emptyState');

  if (!list.length) {
    grid.innerHTML = '';
    empty.classList.remove('hidden');
    const msg = search ? `No tasks matching "<strong>${esc(search)}</strong>"` :
                filter !== 'all' ? `No ${filter.replace('_',' ')} tasks.` :
                'No tasks yet. Hit <strong>+ New Task</strong> to start.';
    document.getElementById('emptyStateMsg').innerHTML = msg;
    return;
  }
  empty.classList.add('hidden');

  grid.innerHTML = list.map(t => {
    const now    = new Date().toISOString().split('T')[0];
    const isOver = t.status !== 'done' && t.due_date && t.due_date < now;
    return `
    <div class="task-card priority-${t.priority} ${t.status==='done'?'done':''} ${isOver?'overdue-card':''}"
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
        <span class="${isOver?'overdue-label':''}">${isOver?'⚠ Overdue':t.due_date?'📅 '+t.due_date:'~'+t.duration+' min'}</span>
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

  document.getElementById('detailBody').innerHTML = `
    ${t.description ? `<p style="font-size:14px;color:var(--text-2);margin-bottom:16px;line-height:1.7">${esc(t.description)}</p>` : ''}
    <div class="ai-suggestion">
      <strong style="color:var(--accent);font-size:11px;text-transform:uppercase;letter-spacing:.5px">AI Suggestion</strong><br>
      ${esc(t.suggestion)}
    </div>
    <h4 style="font-family:var(--font-head);font-size:13px;margin-bottom:8px;color:var(--text-3);text-transform:uppercase;letter-spacing:.5px">
      Subtasks — <span style="color:var(--text-2)">${t.subtasks.filter(s=>s.done).length}/${t.subtasks.length} done</span>
    </h4>
    <div class="subtask-list" id="subtaskList">
      ${t.subtasks.map((s,i) => `
        <div class="subtask-item ${s.done?'done-sub':''}" onclick="toggleSubtask('${t.id}',${i})">
          <div class="subtask-cb">${s.done?'✓':''}</div>
          ${esc(s.text)}
        </div>`).join('')}
    </div>
    ${t.due_date ? `<p style="font-size:13px;color:var(--text-3);margin-top:14px">📅 Due: ${t.due_date}</p>` : ''}
    ${t.completed_at ? `<p style="font-size:13px;color:var(--green);margin-top:6px">✓ Completed: ${formatDate(t.completed_at)}</p>` : ''}
  `;

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
  openDetail(taskId);
  renderDashboard();
}

async function setStatus(taskId, status) {
  const wasNotDone = tasks.find(t => t.id === taskId)?.status !== 'done';
  const updated    = await api(`/tasks/${taskId}`, 'PATCH', {status});
  tasks = tasks.map(t => t.id === taskId ? updated : t);
  if (status === 'done' && wasNotDone) showCelebration();
  openDetail(taskId);
  renderTasks();
  renderDashboard();
  loadReport();
  updateNavBadges();
  checkOverdueBanner();
}

async function deleteCurrentTask() {
  if (!currentTask) return;
  await api(`/tasks/${currentTask.id}`, 'DELETE');
  tasks = tasks.filter(t => t.id !== currentTask.id);
  closeDetail();
  renderTasks();
  renderDashboard();
  loadReport();
  updateNavBadges();
  checkOverdueBanner();
}

function closeDetail(e) {
  if (e && e.target !== document.getElementById('detailOverlay')) return;
  document.getElementById('detailOverlay').classList.remove('open');
  currentTask = null;
}

/* ─── Edit Task Modal ───────────────────────────────────────────────────── */
function openEditModal() {
  if (!currentTask) return;
  const t = currentTask;
  document.getElementById('editTitle').value    = t.title;
  document.getElementById('editDesc').value     = t.description || '';
  document.getElementById('editDue').value      = t.due_date || '';
  document.getElementById('editPriority').value = t.priority;
  document.getElementById('editOverlay').classList.add('open');
}

async function saveEdit() {
  if (!currentTask) return;
  const title    = document.getElementById('editTitle').value.trim();
  const desc     = document.getElementById('editDesc').value.trim();
  const due_date = document.getElementById('editDue').value;
  const priority = document.getElementById('editPriority').value;
  if (!title) { document.getElementById('editTitle').focus(); return; }
  const updated  = await api(`/tasks/${currentTask.id}`, 'PATCH',
    { title, description: desc, due_date, priority });
  tasks = tasks.map(t => t.id === currentTask.id ? updated : t);
  currentTask = updated;
  closeEdit();
  openDetail(updated.id);
  renderTasks();
  renderDashboard();
}

function closeEdit(e) {
  if (e && e.target !== document.getElementById('editOverlay')) return;
  document.getElementById('editOverlay').classList.remove('open');
}

/* ─── Add Task Modal ────────────────────────────────────────────────────── */
function openModal() {
  document.getElementById('taskTitle').value    = '';
  document.getElementById('taskDesc').value     = '';
  document.getElementById('taskDue').value      = '';
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
  document.getElementById('aiPreviewBody').innerHTML = '<span class="muted">Analysing…</span>';
  analyzeTimeout = setTimeout(async () => {
    const r = await api('/analyze', 'POST', {
      title, description: document.getElementById('taskDesc').value
    });
    if (!r || !r.priority) return;
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
  const task  = await api('/tasks', 'POST', {
    title,
    description: document.getElementById('taskDesc').value.trim(),
    due_date:    document.getElementById('taskDue').value,
    priority:    document.getElementById('taskPriority').value || null
  });
  if (!task || !task.id) return;
  tasks.unshift(task);
  closeModal();
  renderTasks();
  renderDashboard();
  loadReport();
  updateNavBadges();
  checkOverdueBanner();
}

/* ─── Celebration ───────────────────────────────────────────────────────── */
function showCelebration() {
  const el = document.getElementById('celebration');
  el.classList.remove('hidden');
  el.classList.add('show');
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.classList.add('hidden'), 400);
  }, 2500);
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
    ? '<p class="muted" style="font-size:13px;padding:10px 0">No pending tasks. Add a task first!</p>'
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
    document.getElementById('timerLabel').textContent = 'Done! 🎉';
    if (timerModeName === 'Focus') {
      const mins = Math.round(timerTotal / 60);
      api('/focus/log', 'POST', { minutes: mins, task_id: selectedTaskId || '' });
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
  const circ   = 2 * Math.PI * 88;
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
  return {critical:'#f43f5e',high:'#f97316',medium:'#facc15',low:'#22c55e'}[p]||'#555b72';
}
function statusLabel(s) {
  return {pending:'Pending',in_progress:'In Progress',done:'Done'}[s]||s;
}
function capitalize(s) {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1).replace('_',' ');
}
function formatDate(iso) {
  return new Date(iso).toLocaleDateString('en-GB',{day:'numeric',month:'short'});
}
function esc(str) {
  return (str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function togglePwField(id, btn) {
  const input = document.getElementById(id);
  if (input.type === 'password') {
    input.type = 'text';
    btn.textContent = '🙈';
  } else {
    input.type = 'password';
    btn.textContent = '👁';
  }
}

/* ─── AI Assistant ──────────────────────────────────────────────────────── */
let chatHistory = [];
let chatWaiting = false;

function initAssistant() {
  const avatar = document.getElementById('userAvatar');
  if (avatar) window._userInitial = avatar.textContent.trim() || '?';
}

function sendSuggestion(btn) {
  const text = btn.textContent;
  const input = document.getElementById('chatInput');
  if (input) input.value = text;
  document.getElementById('chatSuggestions').style.display = 'none';
  sendMessage();
}

function handleChatKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

async function sendMessage() {
  if (chatWaiting) return;
  const input   = document.getElementById('chatInput');
  const message = (input.value || '').trim();
  if (!message) return;

  document.getElementById('chatSuggestions').style.display = 'none';
  appendMessage('user', message);
  chatHistory.push({ role: 'user', content: message });
  input.value = '';
  input.style.height = 'auto';

  chatWaiting = true;
  const sendBtn = document.getElementById('chatSendBtn');
  if (sendBtn) sendBtn.disabled = true;

  const statusEl = document.getElementById('assistantStatus');
  if (statusEl) { statusEl.textContent = 'Thinking…'; statusEl.classList.add('typing'); }

  const typingId = appendTyping();

  try {
    const r = await fetch('/api/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        message:  message,
        messages: chatHistory.slice(-10),
        history:  chatHistory.slice(-10)
      })
    });
    const d = await r.json();
    removeTyping(typingId);
    if (d.error) {
      appendMessage('assistant', '⚠ ' + d.error);
    } else {
      const reply = d.reply || d.message || 'I could not generate a response. Please try again.';
      appendMessage('assistant', reply);
      chatHistory.push({ role: 'assistant', content: reply });
    }
  } catch(e) {
    removeTyping(typingId);
    appendMessage('assistant', '⚠ Network error. Please check your connection and try again.');
  }

  chatWaiting = false;
  if (sendBtn) sendBtn.disabled = false;
  if (statusEl) { statusEl.textContent = 'Ready to help'; statusEl.classList.remove('typing'); }
}

function appendMessage(role, text) {
  const container = document.getElementById('chatMessages');
  if (!container) return;
  const div       = document.createElement('div');
  div.className   = `chat-message ${role === 'user' ? 'user-msg' : 'assistant-msg'}`;
  const initial   = window._userInitial || '?';
  div.innerHTML   = `
    <div class="msg-avatar">${role === 'user' ? initial : '✦'}</div>
    <div class="msg-bubble">${formatMessage(text)}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function appendTyping() {
  const container = document.getElementById('chatMessages');
  if (!container) return 'no-typing';
  const id  = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.id    = id;
  div.className = 'chat-message assistant-msg';
  div.innerHTML = `
    <div class="msg-avatar">✦</div>
    <div class="msg-bubble">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function formatMessage(text) {
  if (!text) return '';
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.*?)\*/g,'<em>$1</em>')
    .replace(/^[-•] (.*$)/gm,'<li>$1</li>')
    .replace(/(<li>[\s\S]*<\/li>)/,'<ul>$1</ul>')
    .replace(/\n\n/g,'</p><p>')
    .replace(/\n/g,'<br>')
    .replace(/^(.+)/,'<p>$1</p>');
}

function clearChat() {
  chatHistory = [];
  const container = document.getElementById('chatMessages');
  if (container) {
    container.innerHTML = `
      <div class="chat-message assistant-msg">
        <div class="msg-avatar">✦</div>
        <div class="msg-bubble"><p>Chat cleared! How can I help you today?</p></div>
      </div>`;
  }
  const sug = document.getElementById('chatSuggestions');
  if (sug) sug.style.display = 'flex';
}

function togglePwField(id, btn) {
  const input = document.getElementById(id);
  if (!input) return;
  input.type = input.type === 'password' ? 'text' : 'password';
  btn.textContent = input.type === 'password' ? '👁' : '🙈';
}
