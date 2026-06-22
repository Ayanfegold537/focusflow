from flask import Flask, request, jsonify, render_template, session, redirect
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os, uuid, random, functools, json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "focusflow_secret_key_2026_hnd")

# ── Database setup ────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Convert postgres:// to postgresql:// for SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

USE_DB = bool(DATABASE_URL)

if USE_DB:
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    def init_db():
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id VARCHAR(20) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    email VARCHAR(200) UNIQUE NOT NULL,
                    password VARCHAR(500) NOT NULL,
                    created TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS resets (
                    token VARCHAR(100) PRIMARY KEY,
                    email VARCHAR(200) NOT NULL,
                    expires TIMESTAMP NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_data (
                    user_id VARCHAR(20) PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()

    try:
        init_db()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"DB init error: {e}")

# ── File-based fallback (local dev) ──────────────────────────────────────────
else:
    BASE_DIR   = "data"
    USERS_FILE = f"{BASE_DIR}/users.json"
    DATA_DIR   = f"{BASE_DIR}/tasks"
    RESET_FILE = f"{BASE_DIR}/resets.json"

    def ensure_dirs():
        os.makedirs(BASE_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)

# ── User helpers ──────────────────────────────────────────────────────────────
def get_user_by_email(email):
    if USE_DB:
        with engine.connect() as conn:
            r = conn.execute(text(
                "SELECT id, name, email, password, created FROM users WHERE email = :e"),
                {"e": email}).fetchone()
            if r:
                return {"id":r[0],"name":r[1],"email":r[2],"password":r[3],"created":str(r[4])}
            return None
    else:
        ensure_dirs()
        if not os.path.exists(USERS_FILE):
            return None
        with open(USERS_FILE) as f:
            users = json.load(f)
        return users.get(email)

def create_user(uid, name, email, pw_hash):
    if USE_DB:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO users (id, name, email, password) VALUES (:id,:n,:e,:p)"),
                {"id":uid,"n":name,"e":email,"p":pw_hash})
            conn.commit()
    else:
        ensure_dirs()
        users = {}
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE) as f:
                users = json.load(f)
        users[email] = {"id":uid,"name":name,"email":email,
                        "password":pw_hash,"created":datetime.now().isoformat()}
        with open(USERS_FILE,"w") as f:
            json.dump(users, f, indent=2)

def update_user_password(email, new_hash):
    if USE_DB:
        with engine.connect() as conn:
            conn.execute(text("UPDATE users SET password=:p WHERE email=:e"),
                         {"p":new_hash,"e":email})
            conn.commit()
    else:
        ensure_dirs()
        with open(USERS_FILE) as f:
            users = json.load(f)
        if email in users:
            users[email]["password"] = new_hash
            with open(USERS_FILE,"w") as f:
                json.dump(users, f, indent=2)

# ── Reset token helpers ───────────────────────────────────────────────────────

def create_reset_token(token, email, expires):
    if USE_DB:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO resets (token,email,expires) VALUES (:t,:e,:x) "
                "ON CONFLICT (token) DO UPDATE SET email=:e, expires=:x"),
                {"t":token,"e":email,"x":expires})
            conn.commit()
    else:
        ensure_dirs()
        resets = {}
        if os.path.exists(RESET_FILE):
            with open(RESET_FILE) as f:
                resets = json.load(f)
        resets[token] = {"email":email,"expires":expires.isoformat()}
        with open(RESET_FILE,"w") as f:
            json.dump(resets, f, indent=2)

def get_reset_token(token):
    if USE_DB:
        with engine.connect() as conn:
            r = conn.execute(text(
                "SELECT email, expires FROM resets WHERE token=:t"),
                {"t":token}).fetchone()
            if r:
                return {"email":r[0],"expires":r[1]}
            return None
    else:
        ensure_dirs()
        if not os.path.exists(RESET_FILE):
            return None
        with open(RESET_FILE) as f:
            resets = json.load(f)
        rec = resets.get(token)
        if rec:
            rec["expires"] = datetime.fromisoformat(rec["expires"])
        return rec

def delete_reset_token(token):
    if USE_DB:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM resets WHERE token=:t"),{"t":token})
            conn.commit()
    else:
        ensure_dirs()
        if not os.path.exists(RESET_FILE):
            return
        with open(RESET_FILE) as f:
            resets = json.load(f)
        resets.pop(token, None)
        with open(RESET_FILE,"w") as f:
            json.dump(resets, f, indent=2)

# ── Task data helpers ─────────────────────────────────────────────────────────

def load_data(uid):
    if USE_DB:
        with engine.connect() as conn:
            r = conn.execute(text(
                "SELECT data FROM user_data WHERE user_id=:u"),
                {"u":uid}).fetchone()
            if r:
                return json.loads(r[0])
    else:
        ensure_dirs()
        path = f"{DATA_DIR}/{uid}.json"
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return {"tasks":[],"sessions":[],"stats":{
        "total_completed":0,"total_focus_minutes":0,"streak":0,"last_active":""}}

def save_data(uid, data):
    data_str = json.dumps(data)
    if USE_DB:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO user_data (user_id, data, updated)
                VALUES (:u, :d, NOW())
                ON CONFLICT (user_id) DO UPDATE SET data=:d, updated=NOW()
            """), {"u":uid,"d":data_str})
            conn.commit()
    else:
        ensure_dirs()
        with open(f"{DATA_DIR}/{uid}.json","w") as f:
            f.write(data_str)

# ── Auth decorator ────────────────────────────────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error":"Unauthorized","redirect":"/login"}), 401
        return f(*args, **kwargs)
    return decorated

def current_uid():
    return session.get("user_id")

# ── AI logic ──────────────────────────────────────────────────────────────────

PRIORITY_KEYWORDS = {
    "critical": ["urgent","asap","emergency","critical","deadline","overdue","immediately","today"],
    "high":     ["important","must","required","exam","submit","present","meeting","project"],
    "medium":   ["should","need","review","update","check","finish","complete","prepare"],
    "low":      ["maybe","someday","optional","explore","idea","consider","read","watch"]
}
CATEGORY_KEYWORDS = {
    "academic":  ["study","exam","assignment","lecture","thesis","research","course","class","lab"],
    "personal":  ["gym","health","sleep","family","friend","shopping","cook","clean","exercise"],
    "work":      ["meeting","report","email","client","deadline","project","present","call","review"],
    "creative":  ["design","write","draw","code","build","create","develop","plan","sketch"],
    "finance":   ["pay","budget","money","bill","bank","fee","tax","invoice","purchase"]
}
MOTIVATIONAL = [
    "You're building momentum — keep going! 🔥",
    "Small steps lead to big results. Stay focused.",
    "Every task you complete is a win. Nice work!",
    "Discipline beats motivation every single day.",
    "Your future self is cheering you on right now.",
    "Progress, not perfection. You're doing great.",
    "One task at a time. That's how mountains are moved.",
]

def ai_analyze_task(title, description=""):
    text = (title + " " + description).lower()
    priority = "medium"
    for p, words in PRIORITY_KEYWORDS.items():
        if any(w in text for w in words):
            priority = p; break
    category = "general"
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in text for w in words):
            category = cat; break
    duration = 30
    if any(w in text for w in ["thesis","research","project","report","exam"]):
        duration = 120
    elif any(w in text for w in ["review","read","study","prepare","write"]):
        duration = 60
    elif any(w in text for w in ["email","check","call","pay","submit"]):
        duration = 15
    subtasks   = generate_subtasks(title, category)
    suggestion = generate_suggestion(priority, duration, category)
    return {"priority":priority,"category":category,"duration":duration,
            "subtasks":subtasks,"suggestion":suggestion}

def generate_subtasks(title, category):
    if category == "academic":
        return ["Gather all study materials","Review key concepts",
                "Practice problems / draft outline","Revise and finalize"]
    elif category == "work":
        return ["Define scope and requirements","Draft initial version",
                "Review and refine","Submit or present"]
    elif category == "creative":
        return ["Brainstorm ideas","Create rough draft/sketch",
                "Iterate and improve","Polish the final output"]
    elif category == "personal":
        return ["Set a specific time slot","Prepare what is needed",
                "Execute the task","Reflect on completion"]
    else:
        return ["Break the task into steps","Work on the first step",
                "Review progress","Mark complete"]

def generate_suggestion(priority, duration, category):
    tips = {
        "academic": f"Schedule a dedicated {duration}-min deep-work block. Use the Pomodoro technique.",
        "work":     f"Block {duration} minutes on your calendar. Communicate dependencies early.",
        "personal": f"Pair this with an existing habit. Consistency beats intensity.",
        "creative": f"Start with a 10-min warm-up before diving in for {duration} minutes.",
        "finance":  f"Set a timer for {duration} minutes — financial tasks feel bigger than they are.",
        "general":  f"Commit to {duration} minutes of focused work. You will likely finish faster than expected."
    }
    return tips.get(category, tips["general"])

def ai_productivity_report(tasks, stats):
    completed   = [t for t in tasks if t.get("status") == "done"]
    pending     = [t for t in tasks if t.get("status") == "pending"]
    overdue     = [t for t in tasks if t.get("status") != "done" and
                   t.get("due_date") and t["due_date"] < datetime.now().strftime("%Y-%m-%d")]
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    by_cat      = {}
    for t in completed:
        c = t.get("category","general")
        by_cat[c] = by_cat.get(c,0)+1
    top_cat  = max(by_cat, key=by_cat.get) if by_cat else "general"
    rate     = round(len(completed)/max(len(tasks),1)*100)
    if rate >= 75:
        insight = "Outstanding productivity! You're completing tasks at a high rate. Keep building on this momentum."
    elif rate >= 50:
        insight = "You're making solid progress. Focus on clearing your pending high-priority tasks next."
    elif overdue:
        insight = f"You have {len(overdue)} overdue task(s). Address those first before adding new ones."
    else:
        insight = "Getting started is the hardest part. Pick your easiest task right now and knock it out."
    return {
        "completed":len(completed),"pending":len(pending),"in_progress":len(in_progress),
        "overdue":len(overdue),"completion_rate":rate,"top_category":top_cat,
        "insight":insight,"streak":stats.get("streak",0),
        "focus_minutes":stats.get("total_focus_minutes",0),
        "motivational":random.choice(MOTIVATIONAL),
        "total":len(tasks),"done_count":len(completed)
    }

# ── Page routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("index.html")

@app.route("/login")
def login_page():
    if "user_id" in session: return redirect("/")
    return render_template("auth.html", mode="login")

@app.route("/signup")
def signup_page():
    if "user_id" in session: return redirect("/")
    return render_template("auth.html", mode="signup")

@app.route("/forgot-password")
def forgot_page():
    if "user_id" in session: return redirect("/")
    return render_template("auth.html", mode="forgot")

@app.route("/reset-password")
def reset_page():
    token = request.args.get("token","")
    return render_template("auth.html", mode="reset", token=token)

# ── Auth API ──────────────────────────────────────────────────────────────────

@app.route("/api/auth/signup", methods=["POST"])
def signup():
    body     = request.json
    name     = (body.get("name","")).strip()
    email    = (body.get("email","")).strip().lower()
    password = body.get("password","")
    if not name or not email or not password:
        return jsonify({"error":"All fields are required."}), 400
    if len(password) < 6:
        return jsonify({"error":"Password must be at least 6 characters."}), 400
    try:
        existing = get_user_by_email(email)
        if existing:
            return jsonify({"error":"An account with this email already exists."}), 409
        uid = str(uuid.uuid4())[:12]
        create_user(uid, name, email, generate_password_hash(password))
        session["user_id"]    = uid
        session["user_name"]  = name
        session["user_email"] = email
        return jsonify({"ok":True,"name":name}), 201
    except Exception as e:
        return jsonify({"error":f"Signup failed: {str(e)}"}), 500

@app.route("/api/auth/login", methods=["POST"])
def login():
    body     = request.json
    email    = (body.get("email","")).strip().lower()
    password = body.get("password","")
    try:
        user = get_user_by_email(email)
        if not user or not check_password_hash(user["password"], password):
            return jsonify({"error":"Invalid email or password."}), 401
        session["user_id"]    = user["id"]
        session["user_name"]  = user["name"]
        session["user_email"] = email
        return jsonify({"ok":True,"name":user["name"]}), 200
    except Exception as e:
        return jsonify({"error":f"Login failed: {str(e)}"}), 500

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok":True})

@app.route("/api/auth/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"error":"Not logged in"}), 401
    try:
        user = get_user_by_email(session.get("user_email",""))
        return jsonify({
            "name":    session.get("user_name"),
            "email":   session.get("user_email"),
            "created": str(user.get("created","")) if user else ""
        })
    except:
        return jsonify({"name":session.get("user_name"),"email":session.get("user_email"),"created":""})

@app.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
    body  = request.json
    email = (body.get("email","")).strip().lower()
    try:
        user = get_user_by_email(email)
        if user:
            token   = str(uuid.uuid4()).replace("-","")
            expires = datetime.now() + timedelta(hours=1)
            create_reset_token(token, email, expires)
            reset_link = f"/reset-password?token={token}"
            return jsonify({"ok":True,"reset_link":reset_link})
        return jsonify({"ok":True,"message":"If that email exists, a reset link has been generated."})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    body   = request.json
    token  = body.get("token","")
    new_pw = body.get("new_password","")
    if not token or not new_pw:
        return jsonify({"error":"Invalid request."}), 400
    if len(new_pw) < 6:
        return jsonify({"error":"Password must be at least 6 characters."}), 400
    try:
        record = get_reset_token(token)
        if not record:
            return jsonify({"error":"Invalid or expired reset link."}), 400
        expires = record["expires"]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        if datetime.now() > expires:
            delete_reset_token(token)
            return jsonify({"error":"This reset link has expired. Please request a new one."}), 400
        user = get_user_by_email(record["email"])
        if not user:
            return jsonify({"error":"Account not found."}), 404
        update_user_password(record["email"], generate_password_hash(new_pw))
        delete_reset_token(token)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/auth/change-password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return jsonify({"error":"Unauthorized"}), 401
    body       = request.json
    current_pw = body.get("current_password","")
    new_pw     = body.get("new_password","")
    if not current_pw or not new_pw:
        return jsonify({"error":"All fields are required."}), 400
    if len(new_pw) < 6:
        return jsonify({"error":"New password must be at least 6 characters."}), 400
    try:
        user = get_user_by_email(session.get("user_email",""))
        if not user or not check_password_hash(user["password"], current_pw):
            return jsonify({"error":"Current password is incorrect."}), 401
        update_user_password(session["user_email"], generate_password_hash(new_pw))
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ── Task API ──────────────────────────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    data = load_data(current_uid())
    return jsonify(data["tasks"])

@app.route("/api/tasks", methods=["POST"])
@login_required
def create_task():
    body     = request.json
    analysis = ai_analyze_task(body.get("title",""), body.get("description",""))
    task = {
        "id":           str(uuid.uuid4())[:8],
        "title":        body.get("title","Untitled"),
        "description":  body.get("description",""),
        "status":       "pending",
        "priority":     body.get("priority") or analysis["priority"],
        "category":     analysis["category"],
        "duration":     analysis["duration"],
        "subtasks":     [{"text":s,"done":False} for s in analysis["subtasks"]],
        "suggestion":   analysis["suggestion"],
        "due_date":     body.get("due_date",""),
        "tags":         body.get("tags",[]),
        "created_at":   datetime.now().isoformat(),
        "completed_at": ""
    }
    data = load_data(current_uid())
    data["tasks"].append(task)
    save_data(current_uid(), data)
    return jsonify(task), 201

@app.route("/api/tasks/<task_id>", methods=["PATCH"])
@login_required
def update_task(task_id):
    body = request.json
    data = load_data(current_uid())
    for task in data["tasks"]:
        if task["id"] == task_id:
            task.update(body)
            if body.get("status") == "done" and not task.get("completed_at"):
                task["completed_at"] = datetime.now().isoformat()
                data["stats"]["total_completed"] = data["stats"].get("total_completed",0)+1
                today = datetime.now().strftime("%Y-%m-%d")
                last  = data["stats"].get("last_active","")
                if last == (datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d"):
                    data["stats"]["streak"] = data["stats"].get("streak",0)+1
                elif last != today:
                    data["stats"]["streak"] = 1
                data["stats"]["last_active"] = today
            save_data(current_uid(), data)
            return jsonify(task)
    return jsonify({"error":"Not found"}), 404

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    data = load_data(current_uid())
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    save_data(current_uid(), data)
    return jsonify({"ok":True})

@app.route("/api/subtask/<task_id>/<int:idx>", methods=["PATCH"])
@login_required
def toggle_subtask(task_id, idx):
    data = load_data(current_uid())
    for task in data["tasks"]:
        if task["id"] == task_id:
            task["subtasks"][idx]["done"] = not task["subtasks"][idx]["done"]
            save_data(current_uid(), data)
            return jsonify(task)
    return jsonify({"error":"Not found"}), 404

@app.route("/api/analyze", methods=["POST"])
@login_required
def analyze():
    body = request.json
    return jsonify(ai_analyze_task(body.get("title",""), body.get("description","")))

@app.route("/api/report", methods=["GET"])
@login_required
def report():
    data = load_data(current_uid())
    return jsonify(ai_productivity_report(data["tasks"], data["stats"]))

@app.route("/api/focus/log", methods=["POST"])
@login_required
def log_focus():
    body = request.json
    mins = body.get("minutes",25)
    data = load_data(current_uid())
    data["stats"]["total_focus_minutes"] = data["stats"].get("total_focus_minutes",0)+mins
    data["sessions"].append({"date":datetime.now().isoformat(),"minutes":mins,
                              "task_id":body.get("task_id","")})
    save_data(current_uid(), data)
    return jsonify({"ok":True,"total":data["stats"]["total_focus_minutes"]})

@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    body    = request.json
    message = (body.get("message") or "").strip().lower()
    history = body.get("history", [])
    username = session.get("user_name", "User").split()[0]

    # Load user task context
    try:
        data       = load_data(current_uid())
        tasks_list = data.get("tasks", [])
        pending    = [t for t in tasks_list if t.get("status") == "pending"]
        done       = [t for t in tasks_list if t.get("status") == "done"]
        overdue    = [t for t in tasks_list if t.get("status") != "done" and
                      t.get("due_date","") and
                      t["due_date"] < datetime.now().strftime("%Y-%m-%d")]
    except:
        pending, done, overdue, tasks_list = [], [], [], []

    def task_summary():
        if not tasks_list:
            return "You have no tasks yet. Add your first task using the + New Task button."
        lines = [f"You currently have {len(tasks_list)} tasks:"]
        if pending:
            lines.append(f"• {len(pending)} pending: " + ", ".join([t['title'] for t in pending[:3]]))
        if done:
            lines.append(f"• {len(done)} completed — great work!")
        if overdue:
            lines.append(f"• ⚠ {len(overdue)} overdue — address these first!")
        return " ".join(lines)

    # ── Knowledge base ─────────────────────────────────────────────────────
    def get_reply(msg):
        # Greetings
        if any(w in msg for w in ["hello","hi ","hey","good morning","good afternoon","good evening","how are you","what's up","sup"]):
            return f"Hello {username}! 👋 I'm your FocusFlow productivity assistant. I'm here to help you stay focused, manage your tasks, and build better habits. What would you like help with today?"

        # Tasks overview
        if any(w in msg for w in ["my tasks","how many tasks","task list","show tasks","what tasks"]):
            return task_summary()

        # Overdue
        if any(w in msg for w in ["overdue","late","behind","missed deadline"]):
            if overdue:
                titles = ", ".join([t['title'] for t in overdue[:3]])
                return f"⚠ You have {len(overdue)} overdue task(s): {titles}. Here is what to do:\n\n• Open each overdue task immediately\n• Either complete it now or reschedule the due date\n• Use the Pomodoro timer to power through them one at a time\n• Overdue tasks harm your completion rate — tackle them before adding new ones."
            return "Great news — you have no overdue tasks! Keep staying on top of your deadlines. 🎉"

        # Focus / concentration
        if any(w in msg for w in ["focus","concentrate","distract","attention","focused","focusin"]):
            return f"Here are proven strategies to stay focused, {username}:\n\n• **Use the Pomodoro timer** in FocusFlow — work for 25 minutes, then take a 5-minute break\n• Put your phone on silent and away from your desk\n• Close unnecessary browser tabs before starting\n• Work on one task at a time — multitasking reduces productivity by up to 40%\n• Study or work in a consistent location so your brain associates it with focus\n• Use the Focus Mode in FocusFlow to select exactly what you are working on"

        # Pomodoro
        if any(w in msg for w in ["pomodoro","timer","25 min","time block","work interval"]):
            return "The **Pomodoro Technique** is a time management method that works like this:\n\n• Work for **25 minutes** with full concentration\n• Take a **5-minute break**\n• After 4 sessions, take a **15-minute long break**\n• Repeat\n\nFocusFlow has a built-in Pomodoro timer in the **Focus Mode** section. Select a task, click Start, and the timer counts down. Your sessions are automatically logged so you can track how much focused time you put in each day."

        # Prioritisation
        if any(w in msg for w in ["priorit","important first","which task","what to work","start with","urgent"]):
            if pending:
                critical = [t for t in pending if t.get("priority") == "critical"]
                high     = [t for t in pending if t.get("priority") == "high"]
                if critical:
                    return f"Based on your tasks, start with your **Critical** priority tasks first:\n\n• {critical[0]['title']}\n\nThe AI has already detected these as urgent. After completing critical tasks, move to your {len(high)} high-priority tasks. Always finish the hardest or most important task before checking emails or doing easy tasks."
            return f"Here is how to prioritise your tasks, {username}:\n\n• **Critical** — do these immediately, today\n• **High** — do these next, same day if possible\n• **Medium** — schedule these for this week\n• **Low** — do these when everything else is done\n\nFocusFlow's AI automatically assigns priority when you create a task based on keywords like 'urgent', 'deadline', and 'exam'."

        # Procrastination
        if any(w in msg for w in ["procrastinat","lazy","motivat","can't start","dont want","don't feel","no energy","stuck"]):
            return f"Procrastination is completely normal, {username} — here is how to beat it:\n\n• **The 2-minute rule**: if a task takes less than 2 minutes, do it right now\n• **Just start**: commit to working for only 5 minutes. You will almost always continue\n• **Break it down**: large tasks feel overwhelming. Use FocusFlow's AI subtasks to see the small steps\n• **Remove friction**: open the task, set the timer, and begin before your brain can object\n• **Reward yourself**: after completing a difficult task, give yourself a small reward\n\nRemember — action creates motivation, not the other way around."

        # Study tips
        if any(w in msg for w in ["study","exam","revision","revise","learn","memorise","memorize","read","lecture","assignment"]):
            return f"Here are effective study strategies for you, {username}:\n\n• **Active recall**: instead of re-reading notes, close the book and write down what you remember\n• **Spaced repetition**: review material after 1 day, 3 days, 1 week, then 1 month\n• **Pomodoro sessions**: use FocusFlow's Focus Mode for 25-minute study blocks\n• **Teach it**: explain the topic to someone else — if you can teach it, you know it\n• **Past questions**: always practice with past exam questions in your final days\n• **Create tasks in FocusFlow** for each topic so you track what you have covered"

        # Time management
        if any(w in msg for w in ["time management","manage time","schedule","plan my day","daily routine","productive day"]):
            return f"Here is a productive daily routine framework, {username}:\n\n• **Morning**: review your FocusFlow task list, identify your top 3 priorities for the day\n• **First 2 hours**: tackle your most important or most difficult task first (peak energy time)\n• **Midday**: handle emails, meetings, and medium-priority tasks\n• **Afternoon**: use Pomodoro sessions for focused work blocks\n• **Evening**: review what you completed, update task statuses, plan tomorrow\n\nThe key principle: protect your peak energy hours for your most important work."

        # Deadline
        if any(w in msg for w in ["deadline","due date","submit","submission","running out of time"]):
            return f"Deadline pressure advice for {username}:\n\n• **Set the due date in FocusFlow** so it shows up as a reminder on your task card\n• Break the work into subtasks — FocusFlow's AI does this automatically when you create a task\n• Work backwards from the deadline to set mini-milestones\n• Start earlier than you think you need to — things always take longer\n• If the deadline is very close: stop planning and start doing. Use the Pomodoro timer and work continuously"

        # Streak / habit
        if any(w in msg for w in ["streak","habit","consistent","daily","routine","every day"]):
            return f"Building consistent habits, {username}:\n\n• FocusFlow tracks your **daily streak** — try to complete at least one task every day to keep it going\n• Habits take an average of 66 days to form — be patient with yourself\n• **Habit stacking**: attach a new habit to an existing one (e.g. 'After breakfast I will open FocusFlow and review my tasks')\n• Make it easy: keep FocusFlow open in your browser so it is always one click away\n• Track your progress — your streak counter in FocusFlow shows how consistent you have been"

        # What is FocusFlow
        if any(w in msg for w in ["focusflow","what is this app","how does this work","what can you do","features","help me use"]):
            return "**FocusFlow** is an AI-Assisted Task and Productivity Management App. Here is what it does:\n\n• **Dashboard** — see all your task stats and AI productivity insights\n• **My Tasks** — create, manage, and track all your tasks with AI-assigned priorities\n• **Focus Mode** — Pomodoro timer to help you work in focused 25-minute blocks\n• **AI Insights** — analyses your task data and gives personalised recommendations\n• **My Profile** — view your stats and change your password\n\nTo get started, click **+ New Task** at the top right and type a task title. The AI will automatically analyse it!"

        # Completion / done
        if any(w in msg for w in ["completed","finished","done","accomplished","achieved"]):
            if done:
                return f"Amazing work, {username}! 🎉 You have completed {len(done)} task(s) so far. That is real progress!\n\n• Keep marking tasks as Done when you finish them to track your completion rate\n• Check your **AI Insights** page to see your productivity analytics\n• Every completed task builds momentum — keep going!"
            return f"You are just getting started, {username}! Add your first task and mark it as Done when you complete it. Your completion rate and streak will start building from there. 💪"

        # Motivation
        if any(w in msg for w in ["motivat","encourage","inspire","tired","exhausted","give up","stressed","overwhelm"]):
            messages_list = [
                f"You are doing better than you think, {username}. Every task you complete — no matter how small — is progress. Keep going.",
                f"The fact that you are here trying to manage your productivity puts you ahead of most people. Don't stop now, {username}.",
                f"Discipline beats motivation every single day. You don't need to feel ready — just start. The motivation will follow.",
                f"Break it down into the smallest possible step and do just that one thing. That's how big goals get achieved, {username}.",
            ]
            import random
            return random.choice(messages_list)

        # Stress / anxiety
        if any(w in msg for w in ["stress","anxious","anxiety","worried","nervous","panic","overwhelm"]):
            return f"It is okay to feel overwhelmed sometimes, {username}. Here is what helps:\n\n• **Write everything down**: open FocusFlow and create a task for every single thing on your mind. Getting it out of your head reduces anxiety immediately\n• **Pick just one thing**: look at your task list and pick the single most important task. Ignore everything else temporarily\n• **Take a break**: use the 5-minute break mode in Focus Mode to step away and breathe\n• **Progress reduces stress**: the moment you complete even one task, you will feel better\n\nYou can handle this — one task at a time."

        # Default / unknown
        return f"I'm your FocusFlow productivity assistant, {username}. I can help you with:\n\n• **Task prioritisation** — which tasks to work on first\n• **Focus strategies** — how to concentrate and avoid distractions\n• **Study tips** — effective learning techniques\n• **Time management** — how to plan your day\n• **Motivation** — encouragement when you feel stuck\n• **Pomodoro technique** — how to use the Focus Mode timer\n• **Your tasks** — ask me about your current task list\n\nWhat would you like help with?"

    reply = get_reply(message)
    return jsonify({"ok": True, "reply": reply})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
