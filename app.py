import os, json, uuid, urllib.request, hashlib, functools, sqlite3, math
from datetime import date, datetime, timedelta
from statistics import median
from flask import Flask, request, jsonify, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
DB_URL = os.environ.get("DATABASE_URL", "")
for _p in ("postgres://", "postgresql://"):   # force the psycopg2 driver that requirements.txt installs
    if DB_URL.startswith(_p): DB_URL = "postgresql+psycopg2://" + DB_URL[len(_p):]

# One query helper: SQLite locally, PostgreSQL (Supabase) when DATABASE_URL is set.
# Every query uses :named parameters, so user input is never pasted into SQL.
if DB_URL:
    from sqlalchemy import create_engine, text
    engine = create_engine(DB_URL, pool_pre_ping=True)
    def q(sql, p=None, one=False):
        with engine.begin() as c:
            r = c.execute(text(sql), p or {})
            if not r.returns_rows: return None
            rows = [dict(x._mapping) for x in r]
            return (rows[0] if rows else None) if one else rows
else:
    def q(sql, p=None, one=False):
        c = sqlite3.connect(os.environ.get("DB_PATH", "focusflow.db")); c.row_factory = sqlite3.Row
        try:
            rows = [dict(x) for x in c.execute(sql, p or {}).fetchall()]; c.commit()
            return (rows[0] if rows else None) if one else rows
        finally: c.close()

for s in [
 "CREATE TABLE IF NOT EXISTS ff_users(id TEXT PRIMARY KEY,name TEXT,username TEXT UNIQUE,gender TEXT,dob TEXT,email TEXT UNIQUE,pw TEXT,created TEXT)",
 "CREATE TABLE IF NOT EXISTS ff_resets(token TEXT PRIMARY KEY,email TEXT,expires TEXT)",
 "CREATE TABLE IF NOT EXISTS ff_tasks(id TEXT PRIMARY KEY,uid TEXT,title TEXT,category TEXT,priority TEXT,effort TEXT,minutes INTEGER,due TEXT,status TEXT,postponed INTEGER,parent TEXT,why TEXT,created TEXT,done_at TEXT)",
 "CREATE TABLE IF NOT EXISTS ff_analyses(id TEXT PRIMARY KEY,uid TEXT,title TEXT,result TEXT,at TEXT)",
 "CREATE TABLE IF NOT EXISTS ff_sessions(id TEXT PRIMARY KEY,uid TEXT,task_id TEXT,minutes INTEGER,at TEXT)"]: q(s)

H = lambda t: hashlib.sha256(t.encode()).hexdigest()
now = lambda: datetime.now().isoformat(timespec="seconds")
today = lambda: date.today()

def need_login(f):
    @functools.wraps(f)
    def w(*a, **k):
        if "uid" not in session: return jsonify(error="Please log in."), 401
        return f(*a, **k)
    return w

# ---------- AI planning engine (rule-based, explainable) ----------
TYPES = {
 "writing": (["report","essay","thesis","dissertation","write","paper","article","proposal"],
   [("Define scope and outline",.10),("Gather and read sources",.25),("Write first draft",.35),("Revise and edit",.20),("Proofread and format",.10)]),
 "coding": (["app","website","code","program","build","develop","system","software","database"],
   [("Write requirements and plan",.10),("Design structure and screens",.15),("Build core features",.40),("Test and fix bugs",.20),("Deploy and document",.15)]),
 "exam": (["exam","test","revise","study","quiz"],
   [("List topics to cover",.10),("Learn each topic",.35),("Practise past questions",.30),("Review weak areas",.15),("Final recap",.10)]),
 "event": (["event","party","trip","wedding","conference","presentation","seminar","meeting"],
   [("Set goal and audience",.10),("Plan details and resources",.25),("Prepare materials",.30),("Rehearse or confirm",.20),("Deliver and follow up",.15)]),
 "fitness": (["gym","workout","exercise","diet","weight","fitness","training"], [("Set a clear target",.10),("Plan the weekly schedule",.20),("Prepare gear and meals",.20),("Do the sessions",.40),("Track progress and adjust",.10)]),
 "money": (["budget","save","bill","loan","invest","tax","money","fees"], [("List income and costs",.15),("Set a target amount",.15),("Make the payment or plan",.30),("Record it",.20),("Review next month",.20)]),
 "home": (["clean","laundry","repair","cook","moving","organise","organize","tidy"], [("List what needs doing",.10),("Gather supplies",.15),("Do the main job",.55),("Tidy up",.10),("Final check",.10)]),
 "shopping": (["buy","shop","order","gift","purchase"], [("Decide what you need",.15),("Compare options and prices",.30),("Set a budget",.15),("Buy or order",.25),("Check and keep the receipt",.15)]),
}
GENERIC = [("Clarify the goal",.10),("Break into parts",.20),("Do the main work",.45),("Review the result",.15),("Finish and submit",.10)]

def analyse(title, due):
    t = title.lower(); words = t.split()
    kind, hits = "general", []
    for k, (kw, _) in TYPES.items():
        h = [w for w in kw if w in t]
        if len(h) > len(hits): kind, hits = k, h
    complexity = min(3, t.count(" and ") + t.count(",") + (1 if len(words) > 8 else 0) + (1 if kind != "general" else 0))
    total = 60 * (1 + complexity)
    days = max(1, (date.fromisoformat(due) - today()).days) if due else 7
    urgent = any(w in t for w in ["urgent","asap","today","deadline"]) or (due and days <= 2)
    return kind, hits, complexity, total, days, "high" if urgent else "medium"

def make_plan(title, due):
    kind, hits, cx, total, days, prio = analyse(title, due)
    steps, cum = [], 0
    for name, frac in (TYPES[kind][1] if kind != "general" else GENERIC):
        cum += frac
        steps.append({"title": name, "minutes": max(15, round(total * frac / 5) * 5),
                      "due": (today() + timedelta(days=math.ceil(cum * days))).isoformat()})
    why = (f"Detected a '{kind}' task" + (f" from the words {hits}" if hits else "") +
           f"; complexity {cx}/3 gives about {total} minutes, " + (f"spread backwards over {days} day(s) before the deadline." if due else "planned over a default 7-day window (add a due date to schedule it)."))
    return kind, prio, total, steps, why

def groq_chat(messages, **kw):
    """Call Groq, trying a second model if the first is unavailable. Returns (text, error)."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key: return None, "No GROQ_API_KEY is set on the server."
    err = ""
    for model in dict.fromkeys([os.environ.get("GROQ_MODEL", "").strip() or "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]):
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=json.dumps(dict(model=model, messages=messages, **kw)).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "FocusFlow/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r: return json.loads(r.read())["choices"][0]["message"]["content"], ""
        except urllib.error.HTTPError as e:
            err = f"Groq error {e.code}: " + e.read().decode()[:160]
            if e.code in (401, 403): break      # bad key: another model will not help
        except Exception as e:
            err = f"Could not reach Groq: {e}"; break
    app.logger.warning(err); return None, err

SYS = ("You are a task-planning assistant inside a productivity app. Reply with JSON only: "
 '{"is_task":true,"message":"if not a task: one kind sentence suggesting how to rephrase it as an action","category":"writing|coding|exam|event|fitness|money|home|shopping|personal|general",'
 '"difficulty":"Easy|Medium|Hard","steps":[{"title":"short action","minutes":30}],"challenges":["three realistic obstacles"],"tip":"one practical tip"}. '
 "Use 4 to 7 concrete steps in a sensible order. If the input is a question or not an actionable task, set is_task to false.")

def groq_plan(title, due):
    txt, err = groq_chat([{"role": "system", "content": SYS}, {"role": "user", "content": title}], temperature=0.3, response_format={"type": "json_object"})
    if not txt: return None
    try:
        d = json.loads(txt)
        if not d.get("is_task", True): return {"is_task": False, "message": str(d.get("message") or "Try describing an action you can complete.")}
        steps = [{"title": str(x["title"])[:90], "minutes": max(5, min(600, int(x.get("minutes") or 30)))} for x in d["steps"] if isinstance(x, dict) and x.get("title")][:7]
        if len(steps) < 3: return None
        total = sum(x["minutes"] for x in steps); days = max(1, (date.fromisoformat(due) - today()).days) if due else 7; cum = 0
        for x in steps:
            cum += x["minutes"]; x["due"] = (today() + timedelta(days=math.ceil(cum / total * days))).isoformat()
        diff = d.get("difficulty") if d.get("difficulty") in ("Easy", "Medium", "Hard") else "Medium"
        return {"is_task": True, "kind": str(d.get("category") or "general")[:20], "difficulty": diff, "minutes": total, "steps": steps,
                "challenges": [str(c)[:90] for c in (d.get("challenges") or [])][:4] or CHALLENGES["general"],
                "why": "Planned by Groq AI. " + str(d.get("tip") or ""), "source": "Groq AI"}
    except Exception as e:
        app.logger.warning("Groq failed, using rule-based planner: %s", e); return None

QWORDS = ("how ", "what ", "why ", "who ", "when ", "where ", "should ", "can i ", "is it ")
def plan_for(title, due):
    p = groq_plan(title, due)
    if p: return p
    if title.lower().startswith(QWORDS) or title.strip().endswith("?"):
        return {"is_task": False, "message": "That looks like a question, not a task. Try an action, e.g. 'Plan a study timetable for next week'."}
    kind, prio, total, steps, why = make_plan(title, due)
    return {"is_task": True, "kind": kind, "difficulty": ["Easy", "Easy", "Medium", "Hard"][analyse(title, due)[2]], "minutes": total, "steps": steps,
            "challenges": CHALLENGES.get(kind, CHALLENGES["general"]), "why": why, "source": "Rule-based planner"}

def effort_of(minutes): return "high" if minutes > 90 else "medium" if minutes > 30 else "low"

# ---------- Auth ----------
@app.route("/")
def index(): return render_template("index.html")

@app.post("/api/signup")
def signup():
    b = request.json or {}; name, email, pw = (b.get("name") or "").strip(), (b.get("email") or "").strip().lower(), b.get("password") or ""
    un = (b.get("username") or "").strip().lower()
    if not name or not un or "@" not in email or len(pw) < 8: return jsonify(error="Name, username, valid email and a password of 8+ characters are required."), 400
    if q("SELECT id FROM ff_users WHERE username=:u", {"u": un}, one=True): return jsonify(error="That username is taken."), 409
    if q("SELECT id FROM ff_users WHERE email=:e", {"e": email}, one=True): return jsonify(error="That email is already registered."), 409
    uid = uuid.uuid4().hex[:12]
    q("INSERT INTO ff_users(id,name,username,gender,dob,email,pw,created) VALUES(:i,:n,:un,:g,:d,:e,:p,:c)", {"i": uid, "n": name, "un": un, "g": b.get("gender") or "", "d": b.get("dob") or "", "e": email, "p": generate_password_hash(pw), "c": now()})
    session.update(uid=uid, name=name); return jsonify(name=name), 201

@app.post("/api/login")
def login():
    b = request.json or {}; k = (b.get("email") or "").strip().lower(); u = q("SELECT * FROM ff_users WHERE email=:e OR username=:e", {"e": k}, one=True)
    if not u or not check_password_hash(u["pw"], b.get("password") or ""): return jsonify(error="Invalid email or password."), 401
    session.update(uid=u["id"], name=u["name"]); return jsonify(name=u["name"])

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/me")
@need_login
def me(): return jsonify(name=session["name"])

@app.post("/api/forgot")
def forgot():
    email = ((request.json or {}).get("email") or "").strip().lower(); link = None
    if q("SELECT id FROM ff_users WHERE email=:e", {"e": email}, one=True):
        tok = uuid.uuid4().hex + uuid.uuid4().hex
        q("INSERT INTO ff_resets(token,email,expires) VALUES(:t,:e,:x)", {"t": H(tok), "e": email, "x": (datetime.now() + timedelta(hours=1)).isoformat()})
        link = "/?token=" + tok   # no email server configured, so the link is shown on screen
    return jsonify(ok=True, link=link)

@app.post("/api/reset")
def reset():
    b = request.json or {}; pw = b.get("password") or ""
    r = q("SELECT * FROM ff_resets WHERE token=:t", {"t": H(b.get("token") or "")}, one=True)
    if len(pw) < 8: return jsonify(error="Password must be 8+ characters."), 400
    if not r or datetime.fromisoformat(r["expires"]) < datetime.now(): return jsonify(error="Link invalid or expired."), 400
    q("UPDATE ff_users SET pw=:p WHERE email=:e", {"p": generate_password_hash(pw), "e": r["email"]})
    q("DELETE FROM ff_resets WHERE token=:t", {"t": r["token"]}); return jsonify(ok=True)

# ---------- Tasks ----------
@app.get("/api/tasks")
@need_login
def tasks(): return jsonify(q("SELECT * FROM ff_tasks WHERE uid=:u ORDER BY created", {"u": session["uid"]}))

def add_task(uid, title, due, cat, prio, mins, parent=None, why=""):
    tid = uuid.uuid4().hex[:10]
    q("INSERT INTO ff_tasks(id,uid,title,category,priority,effort,minutes,due,status,postponed,parent,why,created) VALUES(:i,:u,:t,:c,:p,:e,:m,:d,'open',0,:pa,:w,:cr)",
      {"i": tid, "u": uid, "t": title, "c": cat, "p": prio, "e": effort_of(mins), "m": mins, "d": due or "", "pa": parent, "w": why, "cr": now()})
    return tid

@app.post("/api/tasks")
@need_login
def create_task():
    b = request.json or {}; title = (b.get("title") or "").strip(); due = b.get("due") or ""
    if not title: return jsonify(error="Title is required."), 400
    if due:
        try: date.fromisoformat(due)
        except ValueError: return jsonify(error="Bad date."), 400
    an = analyse(title, due); prio = an[5]; why = ""
    if b.get("breakdown"):
        p = plan_for(title, due)
        if not p["is_task"]: return jsonify(error=p["message"]), 400
        pid = add_task(session["uid"], title, due, p["kind"], prio, p["minutes"], why=p["why"]); why = p["why"]
        for st in p["steps"]: add_task(session["uid"], st["title"], st["due"], p["kind"], prio, st["minutes"], parent=pid)
    else:
        add_task(session["uid"], title, due, an[0], prio, int(b.get("minutes") or 30))
    return jsonify(ok=True, why=why), 201

@app.patch("/api/tasks/<tid>")
@need_login
def update_task(tid):
    b = request.json or {}; t = q("SELECT * FROM ff_tasks WHERE id=:i AND uid=:u", {"i": tid, "u": session["uid"]}, one=True)
    if not t: return jsonify(error="Not found."), 404
    if "status" in b and b["status"] in ("open", "progress", "done", "archived"):
        q("UPDATE ff_tasks SET status=:s,done_at=:d WHERE id=:i", {"s": b["status"], "d": now() if b["status"] == "done" else None, "i": tid})
    if b.get("due"):   # moving a deadline later counts as a postponement
        late = t["due"] and b["due"] > t["due"]
        q("UPDATE ff_tasks SET due=:d,postponed=postponed+:n WHERE id=:i", {"d": b["due"], "n": 1 if late else 0, "i": tid})
    return jsonify(ok=True)

@app.delete("/api/tasks/<tid>")
@need_login
def delete_task(tid):
    q("DELETE FROM ff_tasks WHERE (id=:i OR parent=:i) AND uid=:u", {"i": tid, "u": session["uid"]}); return jsonify(ok=True)

# ---------- Energy-matched "what should I do now?" ----------
@app.get("/api/next")
@need_login
def next_task():
    lvl = {"low": 1, "medium": 2, "high": 3}; en = lvl.get(request.args.get("energy"), 2)
    avail = int(request.args.get("minutes") or 0); rows = q("SELECT * FROM ff_tasks WHERE uid=:u", {"u": session["uid"]})
    parents = {r["parent"] for r in rows if r["parent"]}; out = []
    for t in rows:
        if t["status"] not in ("open", "progress") or t["id"] in parents: continue
        left = (date.fromisoformat(t["due"]) - today()).days if t["due"] else None
        urg = .2 if left is None else 1 if left < 0 else .9 if left <= 1 else .7 if left <= 3 else .5 if left <= 7 else .3
        pr = {"high": 1, "medium": .6, "low": .3}.get(t["priority"], .5)
        fit = 1 - .35 * abs(en - lvl[t["effort"]]); tf = 1 if not avail or t["minutes"] <= avail else .4
        out.append({"id": t["id"], "title": t["title"], "minutes": t["minutes"], "score": round(.4*urg + .25*pr + .2*fit + .15*tf, 2),
                    "reason": f"urgency {urg}, priority {pr}, energy fit {round(fit,2)}, time fit {tf}"})
    return jsonify(sorted(out, key=lambda x: -x["score"])[:3])

# ---------- Focus sessions and insights ----------
@app.post("/api/sessions")
@need_login
def log_session():
    b = request.json or {}; m = int(b.get("minutes") or 0)
    if m > 0: q("INSERT INTO ff_sessions(id,uid,task_id,minutes,at) VALUES(:i,:u,:t,:m,:a)", {"i": uuid.uuid4().hex[:10], "u": session["uid"], "t": b.get("task_id") or "", "m": m, "a": now()})
    return jsonify(ok=True)

@app.get("/api/insights")
@need_login
def insights():
    rows = q("SELECT * FROM ff_tasks WHERE uid=:u", {"u": session["uid"]}); ses = q("SELECT minutes FROM ff_sessions WHERE uid=:u ORDER BY at DESC", {"u": session["uid"]})
    done = [r for r in rows if r["status"] == "done"]; post = {}
    for r in rows: post[r["category"]] = post.get(r["category"], 0) + (r["postponed"] or 0)
    top = max(post, key=post.get) if post and max(post.values()) else None
    overdue = [r for r in rows if r["status"] == "open" and r["due"] and r["due"] < today().isoformat()]
    rec = round(min(50, max(15, median([s["minutes"] for s in ses[:10]]))) ) if ses else 25
    msg = (f"You postponed {post[top]} '{top}' deadline(s). Try scheduling those first." if top else "No postponement pattern yet. Keep deadlines steady.")
    return jsonify(total=len(rows), done=len(done), rate=round(100 * len(done) / len(rows)) if rows else 0, overdue=len(overdue),
                   focus=sum(s["minutes"] for s in ses), progress=len([r for r in rows if r["status"] == "progress"]), archived=len([r for r in rows if r["status"] == "archived"]),
                   monthly={m: len([r for r in done if (r["done_at"] or "")[:7] == m]) for m in sorted({(r["done_at"] or "")[:7] for r in done if r["done_at"]})}, postponed=post, message=msg, suggested_session=rec)

# ---------- AI Task Assistant (analysis history) ----------
CHALLENGES = {"writing": ["Procrastinating on the first draft", "Finding reliable sources", "Leaving too little time to revise"],
 "coding": ["Scope creep", "Debugging unexpected errors", "Underestimating testing time"],
 "exam": ["Covering every topic in time", "Re-reading instead of practising", "Exam anxiety"],
 "event": ["Last-minute changes", "Coordinating people and resources", "Going over budget"],
 "general": ["An unclear goal", "Distractions", "Underestimating the time needed"]}

@app.post("/api/analyze")
@need_login
def analyze():
    title = ((request.json or {}).get("title") or "").strip()
    if not title: return jsonify(error="Describe the task first."), 400
    res = plan_for(title, "")
    if not res["is_task"]: return jsonify(res)
    res["title"] = title
    q("INSERT INTO ff_analyses(id,uid,title,result,at) VALUES(:i,:u,:t,:r,:a)", {"i": uuid.uuid4().hex[:10], "u": session["uid"], "t": title, "r": json.dumps(res), "a": now()})
    return jsonify(res)

@app.get("/api/analyses")
@need_login
def analyses(): return jsonify([dict(json.loads(r["result"]), id=r["id"], at=r["at"]) for r in q("SELECT * FROM ff_analyses WHERE uid=:u ORDER BY at DESC", {"u": session["uid"]})][:15])

@app.delete("/api/analyses")
@need_login
def clear_analyses():
    q("DELETE FROM ff_analyses WHERE uid=:u AND (id=:i OR :i='')", {"u": session["uid"], "i": request.args.get("id", "")}); return jsonify(ok=True)

@app.get("/api/inbox")
@need_login
def inbox():
    out = []
    for t in q("SELECT * FROM ff_tasks WHERE uid=:u AND status IN ('open','progress') AND due<>''", {"u": session["uid"]}):
        d = (date.fromisoformat(t["due"]) - today()).days
        if d < 0: out.append(f"Overdue by {-d} day(s): {t['title']}")
        elif d <= 1: out.append(f"Due {'today' if d == 0 else 'tomorrow'}: {t['title']}")
    return jsonify(out)

@app.get("/api/profile")
@need_login
def profile():
    u = q("SELECT name,username,email,gender,dob,created FROM ff_users WHERE id=:i", {"i": session["uid"]}, one=True); return jsonify(u)

@app.patch("/api/profile")
@need_login
def edit_profile():
    b = request.json or {}; q("UPDATE ff_users SET name=:n,gender=:g,dob=:d WHERE id=:i", {"n": (b.get("name") or session["name"]).strip(), "g": b.get("gender") or "", "d": b.get("dob") or "", "i": session["uid"]})
    session["name"] = (b.get("name") or session["name"]).strip(); return jsonify(ok=True)

@app.post("/api/password")
@need_login
def change_pw():
    b = request.json or {}; u = q("SELECT pw FROM ff_users WHERE id=:i", {"i": session["uid"]}, one=True)
    if not check_password_hash(u["pw"], b.get("current") or ""): return jsonify(error="Current password is wrong."), 401
    if len(b.get("new") or "") < 8: return jsonify(error="New password must be 8+ characters."), 400
    q("UPDATE ff_users SET pw=:p WHERE id=:i", {"p": generate_password_hash(b["new"]), "i": session["uid"]}); return jsonify(ok=True)

# ---------- General AI Chat (any topic) ----------
KB = [(("focus", "concentrat", "distract"), "Work in 25-minute focus blocks, silence your phone and do one thing at a time. The Focus Timer in this app can help."),
 (("pomodoro",), "Pomodoro: work 25 minutes, rest 5, and after four rounds rest 15. Open Focus Timer to start one."),
 (("procrastinat", "motivat", "stuck"), "Start with just 5 minutes on the smallest step. Momentum usually follows."),
 (("study", "exam", "revis"), "Use active recall and past questions, review after 1 day, 3 days and 1 week, and study in 25-minute blocks."),
 (("stress", "overwhelm", "anxious"), "Write everything down, pick the single most important item, and take a 5-minute break first.")]
KB_DEFAULT = "I can only answer a few productivity topics right now (focus, pomodoro, motivation, study, stress). Connect the Groq key to chat about anything."

@app.post("/api/chat")
@need_login
def chat():
    msgs = [{"role": m["role"], "content": str(m["content"])[:2000]} for m in ((request.json or {}).get("messages") or [])[-12:]
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    if not msgs or msgs[-1]["role"] != "user": return jsonify(error="Type a message first."), 400
    tasks = ", ".join(t["title"] for t in q("SELECT title FROM ff_tasks WHERE uid=:u AND parent IS NULL AND status IN ('open','progress') LIMIT 5", {"u": session["uid"]})) or "none"
    sysmsg = ("You are FocusFlow Assistant inside a productivity app. Help with anything the user asks: questions, explanations, writing and editing, study help, planning, coding, ideas, summaries and advice. "
              f"Be accurate, friendly and concise, and say so if you are unsure. The user is {session['name']}. Their open tasks: {tasks}.")
    txt, err = groq_chat([{"role": "system", "content": sysmsg}] + msgs, temperature=0.6, max_tokens=900)
    if txt: return jsonify(reply=txt, source="Groq AI")
    last = msgs[-1]["content"].lower()
    return jsonify(reply=next((a for k, a in KB if any(w in last for w in k)), KB_DEFAULT), source="Offline helper", note=err)

if __name__ == "__main__": app.run(debug=True)
