import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, g
import socket

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")  # set by Railway; absent = use SQLite
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    # Railway gives postgres:// but psycopg2 needs postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Database helpers ──────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        if USE_PG:
            g.db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            g.db = sqlite3.connect("goals.db", detect_types=sqlite3.PARSE_DECLTYPES)
            g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def q(sql):
    """Translate ? placeholders to %s for Postgres."""
    return sql.replace("?", "%s") if USE_PG else sql


def execute(sql, params=(), fetch=None, commit=False):
    db = get_db()
    if USE_PG:
        cur = db.cursor()
        cur.execute(q(sql), params)
        if commit:
            db.commit()
        if fetch == "all":
            return [dict(r) for r in cur.fetchall()]
        if fetch == "one":
            row = cur.fetchone()
            return dict(row) if row else None
        return cur
    else:
        cur = db.execute(sql, params)
        if commit:
            db.commit()
        if fetch == "all":
            return [dict(r) for r in cur.fetchall()]
        if fetch == "one":
            row = cur.fetchone()
            return dict(row) if row else None
        return cur


def init_db():
    if USE_PG:
        db = psycopg2.connect(DATABASE_URL)
        cur = db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id SERIAL PRIMARY KEY,
                month TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        db.commit()
        db.close()
    else:
        with sqlite3.connect("goals.db") as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    month TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            db.commit()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/goals")
def get_goals():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    rows = execute(
        "SELECT * FROM goals WHERE month = ? ORDER BY category, created_at",
        (month,), fetch="all"
    )
    return jsonify(rows)


@app.route("/api/goals", methods=["POST"])
def add_goal():
    data = request.get_json()
    month = data.get("month", datetime.now().strftime("%Y-%m"))
    category = data["category"]
    title = data["title"].strip()
    if not title:
        return jsonify({"error": "Title required"}), 400

    if USE_PG:
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO goals (month, category, title, completed, created_at) VALUES (%s,%s,%s,0,%s) RETURNING *",
            (month, category, title, datetime.now().isoformat())
        )
        db.commit()
        row = dict(cur.fetchone())
    else:
        cur = execute(
            "INSERT INTO goals (month, category, title, completed, created_at) VALUES (?,?,?,0,?)",
            (month, category, title, datetime.now().isoformat()), commit=True
        )
        row = execute("SELECT * FROM goals WHERE id = ?", (cur.lastrowid,), fetch="one")

    return jsonify(row), 201


@app.route("/api/goals/<int:goal_id>/toggle", methods=["PATCH"])
def toggle_goal(goal_id):
    row = execute("SELECT * FROM goals WHERE id = ?", (goal_id,), fetch="one")
    if not row:
        return jsonify({"error": "Not found"}), 404
    new_val = 0 if row["completed"] else 1
    execute("UPDATE goals SET completed = ? WHERE id = ?", (new_val, goal_id), commit=True)
    row = execute("SELECT * FROM goals WHERE id = ?", (goal_id,), fetch="one")
    return jsonify(row)


@app.route("/api/goals/<int:goal_id>", methods=["DELETE"])
def delete_goal(goal_id):
    execute("DELETE FROM goals WHERE id = ?", (goal_id,), commit=True)
    return jsonify({"ok": True})


# Called at import time so gunicorn-based deployments initialize the DB too
init_db()

# ── Entry point ───────────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    init_db()
    ip = get_local_ip()
    port = 5050
    print(f"\n  Goals Tracker running!")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{ip}:{port}  <-- open this on your phone\n")
    app.run(host="0.0.0.0", port=port, debug=False)
