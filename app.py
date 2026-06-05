from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
import json, os, uuid, random

app = Flask(__name__)
DATA_FILE = "data/tasks.json"

# ─── helpers ──────────────────────────────────────────────────────────────────

def load_data():
    if not os.path.exists(DATA_FILE):
        default = {"tasks": [], "sessions": [], "stats": {"total_completed": 0, "total_focus_minutes": 0, "streak": 0, "last_active": ""}}
        save_data(default)
        return default
    with open(DATA_FILE) as f:
        return json.load(f)

def save_data(data):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ─── AI logic (rule-based — no external API needed) ────────────────────────────

PRIORITY_KEYWORDS = {
    "critical": ["urgent", "asap", "emergency", "critical", "deadline", "overdue", "immediately", "today"],
    "high":     ["important", "must", "required", "exam", "submit", "present", "meeting", "project"],
    "medium":   ["should", "need", "review", "update", "check", "finish", "complete", "prepare"],
    "low":      ["maybe", "someday", "optional", "explore", "idea", "consider", "read", "watch"]
}

CATEGORY_KEYWORDS = {
    "academic":  ["study", "exam", "assignment", "lecture", "thesis", "research", "course", "class", "lab"],
    "personal":  ["gym", "health", "sleep", "family", "friend", "shopping", "cook", "clean", "exercise"],
    "work":      ["meeting", "report", "email", "client", "deadline", "project", "present", "call", "review"],
    "creative":  ["design", "write", "draw", "code", "build", "create", "develop", "plan", "sketch"],
    "finance":   ["pay", "budget", "money", "bill", "bank", "fee", "tax", "invoice", "purchase"]
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

    # Priority detection
    priority = "medium"
    for p, words in PRIORITY_KEYWORDS.items():
        if any(w in text for w in words):
            priority = p
            break

    # Category detection
    category = "general"
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in text for w in words):
            category = cat
            break

    # Estimate time (minutes) based on task type keywords
    duration = 30
    if any(w in text for w in ["thesis", "research", "project", "report", "exam"]):
        duration = 120
    elif any(w in text for w in ["review", "read", "study", "prepare", "write"]):
        duration = 60
    elif any(w in text for w in ["email", "check", "call", "pay", "submit"]):
        duration = 15

    # Generate subtasks
    subtasks = generate_subtasks(title, category)

    # Smart suggestion
    suggestion = generate_suggestion(title, priority, duration, category)

    return {
        "priority":   priority,
        "category":   category,
        "duration":   duration,
        "subtasks":   subtasks,
        "suggestion": suggestion
    }

def generate_subtasks(title, category):
    title_lower = title.lower()
    if category == "academic":
        return ["Gather all study materials", "Review key concepts", "Practice problems / draft outline", "Revise and finalize"]
    elif category == "work":
        return ["Define scope and requirements", "Draft initial version", "Review and refine", "Submit or present"]
    elif category == "creative":
        return ["Brainstorm ideas", "Create rough draft/sketch", "Iterate and improve", "Polish the final output"]
    elif category == "personal":
        return ["Set a specific time slot", "Prepare what's needed", "Execute the task", "Reflect on completion"]
    else:
        return ["Break the task into steps", "Work on the first step", "Review progress", "Mark complete"]

def generate_suggestion(title, priority, duration, category):
    tips = {
        "academic": f"Schedule a dedicated {duration}-min deep-work block. Remove distractions and use the Pomodoro technique.",
        "work":     f"Block {duration} minutes on your calendar. Communicate any dependencies early.",
        "personal": f"Try pairing this with an existing habit. Consistency beats intensity.",
        "creative": f"Start with a 10-min warm-up sketch or brainstorm before diving in for {duration} minutes.",
        "finance":  f"Set a timer for {duration} minutes — financial tasks feel bigger than they are.",
        "general":  f"Commit to {duration} minutes of focused work. You'll likely finish faster than expected."
    }
    return tips.get(category, tips["general"])

def ai_productivity_report(tasks, stats):
    completed   = [t for t in tasks if t.get("status") == "done"]
    pending     = [t for t in tasks if t.get("status") == "pending"]
    overdue     = [t for t in tasks if t.get("status") == "pending" and t.get("due_date") and t["due_date"] < datetime.now().strftime("%Y-%m-%d")]
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]

    by_category = {}
    for t in completed:
        c = t.get("category", "general")
        by_category[c] = by_category.get(c, 0) + 1

    top_category = max(by_category, key=by_category.get) if by_category else "general"
    completion_rate = round(len(completed) / max(len(tasks), 1) * 100)

    insight = ""
    if completion_rate >= 75:
        insight = "Outstanding productivity! You're completing tasks at a high rate. Keep building on this momentum."
    elif completion_rate >= 50:
        insight = "You're making solid progress. Focus on clearing your pending high-priority tasks next."
    elif overdue:
        insight = f"You have {len(overdue)} overdue task(s). Address those first before adding new ones."
    else:
        insight = "Getting started is the hardest part. Pick your easiest task right now and knock it out."

    return {
        "completed":       len(completed),
        "pending":         len(pending),
        "in_progress":     len(in_progress),
        "overdue":         len(overdue),
        "completion_rate": completion_rate,
        "top_category":    top_category,
        "insight":         insight,
        "streak":          stats.get("streak", 0),
        "focus_minutes":   stats.get("total_focus_minutes", 0),
        "motivational":    random.choice(MOTIVATIONAL)
    }

# ─── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    data = load_data()
    return jsonify(data["tasks"])

@app.route("/api/tasks", methods=["POST"])
def create_task():
    body = request.json
    analysis = ai_analyze_task(body.get("title", ""), body.get("description", ""))
    task = {
        "id":          str(uuid.uuid4())[:8],
        "title":       body.get("title", "Untitled"),
        "description": body.get("description", ""),
        "status":      "pending",
        "priority":    body.get("priority") or analysis["priority"],
        "category":    analysis["category"],
        "duration":    analysis["duration"],
        "subtasks":    [{"text": s, "done": False} for s in analysis["subtasks"]],
        "suggestion":  analysis["suggestion"],
        "due_date":    body.get("due_date", ""),
        "tags":        body.get("tags", []),
        "created_at":  datetime.now().isoformat(),
        "completed_at": ""
    }
    data = load_data()
    data["tasks"].append(task)
    save_data(data)
    return jsonify(task), 201

@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id):
    body = request.json
    data = load_data()
    for task in data["tasks"]:
        if task["id"] == task_id:
            task.update(body)
            if body.get("status") == "done" and not task.get("completed_at"):
                task["completed_at"] = datetime.now().isoformat()
                data["stats"]["total_completed"] = data["stats"].get("total_completed", 0) + 1
                # Update streak
                today = datetime.now().strftime("%Y-%m-%d")
                last = data["stats"].get("last_active", "")
                if last == (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"):
                    data["stats"]["streak"] = data["stats"].get("streak", 0) + 1
                elif last != today:
                    data["stats"]["streak"] = 1
                data["stats"]["last_active"] = today
            save_data(data)
            return jsonify(task)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    data = load_data()
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/subtask/<task_id>/<int:idx>", methods=["PATCH"])
def toggle_subtask(task_id, idx):
    data = load_data()
    for task in data["tasks"]:
        if task["id"] == task_id:
            task["subtasks"][idx]["done"] = not task["subtasks"][idx]["done"]
            save_data(data)
            return jsonify(task)
    return jsonify({"error": "Not found"}), 404

@app.route("/api/analyze", methods=["POST"])
def analyze():
    body = request.json
    result = ai_analyze_task(body.get("title", ""), body.get("description", ""))
    return jsonify(result)

@app.route("/api/report", methods=["GET"])
def report():
    data = load_data()
    return jsonify(ai_productivity_report(data["tasks"], data["stats"]))

@app.route("/api/focus/log", methods=["POST"])
def log_focus():
    body   = request.json
    mins   = body.get("minutes", 25)
    data   = load_data()
    data["stats"]["total_focus_minutes"] = data["stats"].get("total_focus_minutes", 0) + mins
    data["sessions"].append({"date": datetime.now().isoformat(), "minutes": mins, "task_id": body.get("task_id", "")})
    save_data(data)
    return jsonify({"ok": True, "total": data["stats"]["total_focus_minutes"]})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
