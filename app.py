import os, json, uuid, hashlib, functools, sqlite3, math
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
           f"; complexity {cx}/3 gives about {total} minutes, spread backwards over {days} day(s) before the deadline.")
    return kind, prio, total, steps, why

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
    kind, prio, total, steps, why = make_plan(title, due)
    if b.get("breakdown"):
        pid = add_task(session["uid"], title, due, kind, prio, total, why=why)
        for s in steps: add_task(session["uid"], s["title"], s["due"], kind, prio, s["minutes"], parent=pid)
    else:
        add_task(session["uid"], title, due, kind, prio, int(b.get("minutes") or 30))
    return jsonify(ok=True, why=why if b.get("breakdown") else ""), 201

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
    kind, prio, total, steps, why = make_plan(title, ""); cx = analyse(title, "")[2]
    res = {"title": title, "kind": kind, "difficulty": ["Easy", "Easy", "Medium", "Hard"][cx], "minutes": total, "steps": steps, "challenges": CHALLENGES[kind], "why": why}
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

if __name__ == "__main__": app.run(debug=True)
