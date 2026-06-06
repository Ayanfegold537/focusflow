from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import json, os, uuid, random, functools

app = Flask(__name__)
app.secret_key = "focusflow_secret_key_2026_hnd_project"

USERS_FILE = "data/users.json"
DATA_DIR   = "data/tasks"

# ── helpers ───────────────────────────────────────────────────────────────────

def load_users():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            json.dump({}, f)
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def save_users(users):
    os.makedirs("data", exist_ok=True)
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def user_file(uid):
    os.makedirs(DATA_DIR, exist_ok=True)
    return f"{DATA_DIR}/{uid}.json"

def load_data(uid):
    path = user_file(uid)
    if not os.path.exists(path):
        default = {"tasks": [], "sessions": [], "stats": {
            "total_completed": 0, "total_focus_minutes": 0,
            "streak": 0, "last_active": ""}}
        save_data(uid, default)
        return default
    with open(path) as f:
        return json.load(f)

def save_data(uid, data):
    with open(user_file(uid), "w") as f:
        json.dump(data, f, indent=2)

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorized", "redirect": "/login"}), 401
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
            priority = p
            break
    category = "general"
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in text for w in words):
            category = cat
            break
    duration = 30
    if any(w in text for w in ["thesis","research","project","report","exam"]):
        duration = 120
    elif any(w in text for w in ["review","read","study","prepare","write"]):
        duration = 60
    elif any(w in text for w in ["email","check","call","pay","submit"]):
        duration = 15
    subtasks  = generate_subtasks(title, category)
    suggestion = generate_suggestion(title, priority, duration, category)
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

def generate_suggestion(title, priority, duration, category):
    tips = {
        "academic": f"Schedule a dedicated {duration}-min deep-work block. Remove distractions and use the Pomodoro technique.",
        "work":     f"Block {duration} minutes on your calendar. Communicate any dependencies early.",
        "personal": f"Try pairing this with an existing habit. Consistency beats intensity.",
        "creative": f"Start with a 10-min warm-up before diving in for {duration} minutes.",
        "finance":  f"Set a timer for {duration} minutes — financial tasks feel bigger than they are.",
        "general":  f"Commit to {duration} minutes of focused work. You'll likely finish faster than expected."
    }
    return tips.get(category, tips["general"])

def ai_productivity_report(tasks, stats):
    completed   = [t for t in tasks if t.get("status") == "done"]
    pending     = [t for t in tasks if t.get("status") == "pending"]
    overdue     = [t for t in tasks if t.get("status") == "pending" and
                   t.get("due_date") and t["due_date"] < datetime.now().strftime("%Y-%m-%d")]
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    by_category = {}
    for t in completed:
        c = t.get("category","general")
        by_category[c] = by_category.get(c,0)+1
    top_category    = max(by_category, key=by_category.get) if by_category else "general"
    completion_rate = round(len(completed)/max(len(tasks),1)*100)
    if completion_rate >= 75:
        insight = "Outstanding productivity! You're completing tasks at a high rate. Keep building on this momentum."
    elif completion_rate >= 50:
        insight = "You're making solid progress. Focus on clearing your pending high-priority tasks next."
    elif overdue:
        insight = f"You have {len(overdue)} overdue task(s). Address those first before adding new ones."
    else:
        insight = "Getting started is the hardest part. Pick your easiest task right now and knock it out."
    return {
        "completed":completion_rate,"pending":len(pending),"in_progress":len(in_progress),
        "overdue":len(overdue),"completion_rate":completion_rate,"top_category":top_category,
        "insight":insight,"streak":stats.get("streak",0),
        "focus_minutes":stats.get("total_focus_minutes",0),
        "motivational":random.choice(MOTIVATIONAL),
        "total": len(tasks), "done_count": len(completed)
    }

# ── AUTH ROUTES ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("index.html")

@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect("/")
    return render_template("auth.html", mode="login")

@app.route("/signup")
def signup_page():
    if "user_id" in session:
        return redirect("/")
    return render_template("auth.html", mode="signup")

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
    users = load_users()
    if email in users:
        return jsonify({"error":"An account with this email already exists."}), 409
    uid = str(uuid.uuid4())[:12]
    users[email] = {
        "id":       uid,
        "name":     name,
        "email":    email,
        "password": generate_password_hash(password),
        "created":  datetime.now().isoformat()
    }
    save_users(users)
    session["user_id"]    = uid
    session["user_name"]  = name
    session["user_email"] = email
    return jsonify({"ok":True,"name":name}), 201

@app.route("/api/auth/login", methods=["POST"])
def login():
    body     = request.json
    email    = (body.get("email","")).strip().lower()
    password = body.get("password","")
    users    = load_users()
    user     = users.get(email)
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error":"Invalid email or password."}), 401
    session["user_id"]    = user["id"]
    session["user_name"]  = user["name"]
    session["user_email"] = email
    return jsonify({"ok":True,"name":user["name"]}), 200

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok":True})

@app.route("/api/auth/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"error":"Not logged in"}), 401
    return jsonify({"name":session.get("user_name"),"email":session.get("user_email")})

# ── TASK ROUTES ───────────────────────────────────────────────────────────────

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

if __name__ == "__main__":
    app.run(debug=True, port=5000)
