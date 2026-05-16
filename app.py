
"""
Job Portal Web Application
===========================
Supports SQLite locally AND PostgreSQL on Render automatically.
No manual switching needed — just set DATABASE_URL on Render.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
import os
from functools import wraps

# ─── Detect which database to use ────────────────────────────────────────────
# On Render: DATABASE_URL env var is set automatically when you attach PostgreSQL
# Locally:   falls back to SQLite
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # ── PostgreSQL mode (Render production) ──────────────────────────────────
    import psycopg2
    import psycopg2.extras   # gives dict-like row access
    USE_POSTGRES = True
    # Render gives  "postgres://..."  but psycopg2 needs  "postgresql://..."
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    # ── SQLite mode (local development) ──────────────────────────────────────
    import sqlite3
    USE_POSTGRES = False
    DATABASE = "job_portal.db"

# ─── App setup ───────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("app.secret_key", "dev-secret-change-in-production")


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE LAYER  —  works identically for both SQLite and PostgreSQL
# The rest of the code never needs to know which one is running.
# ═══════════════════════════════════════════════════════════════════════════════

def get_db():
    """
    Return a database connection for this request.
    SQLite:     uses Flask's g object (one connection per request)
    PostgreSQL: opens a new connection each time (psycopg2 is thread-safe)
    """
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    else:
        db = getattr(g, '_database', None)
        if db is None:
            db = g._database = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row
        return db


@app.teardown_appcontext
def close_db(exception):
    """Close SQLite connection at end of request. (PostgreSQL closes per-query.)"""
    if not USE_POSTGRES:
        db = getattr(g, '_database', None)
        if db is not None:
            db.close()


def db_execute(query, params=(), fetchone=False, fetchall=False, commit=False):
    """
    Universal query runner — handles both SQLite and PostgreSQL transparently.

    SQLite uses  ?  as placeholder.
    PostgreSQL uses  %s  as placeholder.
    This function auto-converts so you only ever write  ?  in your queries.

    Usage:
        rows = db_execute("SELECT * FROM jobs WHERE id=?", (job_id,), fetchall=True)
        row  = db_execute("SELECT * FROM users WHERE email=?", (email,), fetchone=True)
        db_execute("INSERT INTO users (...) VALUES (?,?,?)", (...,), commit=True)
    """
    # Convert SQLite ? placeholders to PostgreSQL %s
    if USE_POSTGRES:
        query = query.replace("?", "%s")
        # PostgreSQL uses SERIAL instead of AUTOINCREMENT — handled in init_db
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(query, params)
        result = None
        if fetchone:
            result = cur.fetchone()
        elif fetchall:
            result = cur.fetchall()
        if commit:
            conn.commit()
        cur.close()
        conn.close()
        return result
    else:
        db = get_db()
        cur = db.execute(query, params)
        result = None
        if fetchone:
            result = cur.fetchone()
        elif fetchall:
            result = cur.fetchall()
        if commit:
            db.commit()
        return result


def db_executescript(sql_sqlite, sql_postgres=None):
    """
    Run a multi-statement SQL script.
    Provide separate versions for SQLite and PostgreSQL if syntax differs.
    """
    if USE_POSTGRES:
        script = sql_postgres or sql_sqlite
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(script)
        conn.commit()
        cur.close()
        conn.close()
    else:
        db = get_db()
        db.executescript(sql_sqlite)
        db.commit()


# ─── Table creation SQL ───────────────────────────────────────────────────────

SCHEMA_SQLITE = """
    CREATE TABLE IF NOT EXISTS users (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username   TEXT UNIQUE NOT NULL,
        email      TEXT UNIQUE NOT NULL,
        password   TEXT NOT NULL,
        role       TEXT NOT NULL DEFAULT 'seeker',
        company    TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS jobs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        employer_id  INTEGER NOT NULL,
        title        TEXT NOT NULL,
        company      TEXT NOT NULL,
        location     TEXT NOT NULL,
        category     TEXT NOT NULL,
        salary       TEXT,
        description  TEXT NOT NULL,
        requirements TEXT,
        job_type     TEXT DEFAULT 'Full-time',
        is_active    INTEGER DEFAULT 1,
        created_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (employer_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS applications (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       INTEGER NOT NULL,
        seeker_id    INTEGER NOT NULL,
        cover_letter TEXT,
        status       TEXT DEFAULT 'Pending',
        applied_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (job_id)    REFERENCES jobs(id),
        FOREIGN KEY (seeker_id) REFERENCES users(id),
        UNIQUE(job_id, seeker_id)
    );
"""

# PostgreSQL uses SERIAL (not AUTOINCREMENT) and TEXT (not INTEGER for booleans)
SCHEMA_POSTGRES = """
    CREATE TABLE IF NOT EXISTS users (
        id         SERIAL PRIMARY KEY,
        username   TEXT UNIQUE NOT NULL,
        email      TEXT UNIQUE NOT NULL,
        password   TEXT NOT NULL,
        role       TEXT NOT NULL DEFAULT 'seeker',
        company    TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS jobs (
        id           SERIAL PRIMARY KEY,
        employer_id  INTEGER NOT NULL REFERENCES users(id),
        title        TEXT NOT NULL,
        company      TEXT NOT NULL,
        location     TEXT NOT NULL,
        category     TEXT NOT NULL,
        salary       TEXT,
        description  TEXT NOT NULL,
        requirements TEXT,
        job_type     TEXT DEFAULT 'Full-time',
        is_active    INTEGER DEFAULT 1,
        created_at   TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS applications (
        id           SERIAL PRIMARY KEY,
        job_id       INTEGER NOT NULL REFERENCES jobs(id),
        seeker_id    INTEGER NOT NULL REFERENCES users(id),
        cover_letter TEXT,
        status       TEXT DEFAULT 'Pending',
        applied_at   TIMESTAMP DEFAULT NOW(),
        UNIQUE(job_id, seeker_id)
    );
"""


def init_db():
    """Create tables and default admin — runs on every startup safely."""
    with app.app_context():
        db_executescript(SCHEMA_SQLITE, SCHEMA_POSTGRES)

        
        admin_email    = os.environ.get("ADMIN_EMAIL")
        admin_password = os.environ.get("ADMIN_PASSWORD")

        existing = db_execute(
            "SELECT id FROM users WHERE role='admin'", fetchone=True
        )
        if not existing:
            db_execute(
                "INSERT INTO users (username, email, password, role) VALUES (?,?,?,?)",
                ("admin", admin_email,
                 generate_password_hash(admin_password), "admin"),
                commit=True
            )
    print(f" DB initialized ({'PostgreSQL' if USE_POSTGRES else 'SQLite'})")


# ─── Auth Decorators ─────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                flash("Access denied.", "danger")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ─── Context Processor ───────────────────────────────────────────────────────

@app.context_processor
def inject_user():
    return dict(
        current_user_id=session.get('user_id'),
        current_role=session.get('role'),
        current_username=session.get('username')
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    recent_jobs = db_execute(
        "SELECT * FROM jobs WHERE is_active=1 ORDER BY created_at DESC LIMIT 6",
        fetchall=True
    )
    stats = {
        "jobs":      (db_execute("SELECT COUNT(*) FROM jobs WHERE is_active=1", fetchone=True) or [0])[0],
        "employers": (db_execute("SELECT COUNT(*) FROM users WHERE role='employer'", fetchone=True) or [0])[0],
        "seekers":   (db_execute("SELECT COUNT(*) FROM users WHERE role='seeker'", fetchone=True) or [0])[0],
        "apps":      (db_execute("SELECT COUNT(*) FROM applications", fetchone=True) or [0])[0],
    }
    categories = db_execute(
        "SELECT category, COUNT(*) as cnt FROM jobs WHERE is_active=1 GROUP BY category ORDER BY cnt DESC LIMIT 8",
        fetchall=True
    )
    return render_template("index.html", recent_jobs=recent_jobs or [], stats=stats, categories=categories or [])


@app.route("/jobs")
def job_list():
    keyword  = request.args.get("keyword",  "").strip()
    location = request.args.get("location", "").strip()
    category = request.args.get("category", "").strip()
    job_type = request.args.get("job_type", "").strip()

    query  = "SELECT * FROM jobs WHERE is_active=1"
    params = []
    if keyword:
        query += " AND (title LIKE ? OR description LIKE ? OR company LIKE ?)"
        params += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    if category:
        query += " AND category=?"
        params.append(category)
    if job_type:
        query += " AND job_type=?"
        params.append(job_type)
    query += " ORDER BY created_at DESC"

    jobs       = db_execute(query, params, fetchall=True) or []
    categories = db_execute("SELECT DISTINCT category FROM jobs WHERE is_active=1", fetchall=True) or []
    return render_template("jobs.html", jobs=jobs, categories=categories,
                           keyword=keyword, location=location,
                           category=category, job_type=job_type)


@app.route("/jobs/<int:job_id>")
def job_detail(job_id):
    job = db_execute("SELECT * FROM jobs WHERE id=? AND is_active=1", (job_id,), fetchone=True)
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for('job_list'))

    already_applied = False
    if session.get('role') == 'seeker':
        already_applied = db_execute(
            "SELECT id FROM applications WHERE job_id=? AND seeker_id=?",
            (job_id, session['user_id']), fetchone=True
        ) is not None

    return render_template("job_detail.html", job=job, already_applied=already_applied)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email    = request.form["email"].strip()
        password = request.form["password"]
        role     = request.form["role"]
        company  = request.form.get("company", "").strip()

        if role not in ("seeker", "employer"):
            flash("Invalid role.", "danger")
            return redirect(url_for('register'))

        if db_execute("SELECT id FROM users WHERE username=?", (username,), fetchone=True):
            flash("Username already taken.", "danger")
            return redirect(url_for('register'))
        if db_execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True):
            flash("Email already registered.", "danger")
            return redirect(url_for('register'))

        db_execute(
            "INSERT INTO users (username, email, password, role, company) VALUES (?,?,?,?,?)",
            (username, email, generate_password_hash(password), role, company),
            commit=True
        )
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        email    = request.form["email"].strip()
        password = request.form["password"]
        user = db_execute("SELECT * FROM users WHERE email=?", (email,), fetchone=True)

        if user and check_password_hash(user["password"], password):
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            session["role"]     = user["role"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('dashboard'))
        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]

    if session["role"] == "seeker":
        applications = db_execute(
            """SELECT a.*, j.title, j.company, j.location, j.job_type
               FROM applications a JOIN jobs j ON a.job_id=j.id
               WHERE a.seeker_id=? ORDER BY a.applied_at DESC""",
            (uid,), fetchall=True
        ) or []
        return render_template("dashboard_seeker.html", applications=applications)

    elif session["role"] == "employer":
        jobs = db_execute(
            "SELECT * FROM jobs WHERE employer_id=? ORDER BY created_at DESC",
            (uid,), fetchall=True
        ) or []
        total_apps = (db_execute(
            "SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id=j.id WHERE j.employer_id=?",
            (uid,), fetchone=True
        ) or [0])[0]
        return render_template("dashboard_employer.html", jobs=jobs, total_apps=total_apps)

    elif session["role"] == "admin":
        users = db_execute("SELECT * FROM users ORDER BY created_at DESC", fetchall=True) or []
        jobs  = db_execute(
            "SELECT j.*, u.username AS employer_name FROM jobs j JOIN users u ON j.employer_id=u.id ORDER BY j.created_at DESC",
            fetchall=True
        ) or []
        apps  = db_execute(
            "SELECT a.*, j.title, u.username AS seeker_name FROM applications a JOIN jobs j ON a.job_id=j.id JOIN users u ON a.seeker_id=u.id ORDER BY a.applied_at DESC",
            fetchall=True
        ) or []
        stats = {
            "users":     len(users),
            "jobs":      len(jobs),
            "apps":      len(apps),
            "employers": sum(1 for u in users if u["role"] == "employer"),
            "seekers":   sum(1 for u in users if u["role"] == "seeker"),
        }
        return render_template("dashboard_admin.html", users=users, jobs=jobs, apps=apps, stats=stats)

    return redirect(url_for('index'))


# ═══════════════════════════════════════════════════════════════════════════════
# SEEKER ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
@login_required
@role_required("seeker")
def apply_job(job_id):
    job = db_execute("SELECT * FROM jobs WHERE id=? AND is_active=1", (job_id,), fetchone=True)
    if not job:
        flash("Job not found or no longer active.", "danger")
        return redirect(url_for('job_list'))

    if db_execute("SELECT id FROM applications WHERE job_id=? AND seeker_id=?",
                  (job_id, session["user_id"]), fetchone=True):
        flash("You have already applied for this job.", "info")
        return redirect(url_for('job_detail', job_id=job_id))

    if request.method == "POST":
        cover_letter = request.form.get("cover_letter", "").strip()
        db_execute(
            "INSERT INTO applications (job_id, seeker_id, cover_letter) VALUES (?,?,?)",
            (job_id, session["user_id"], cover_letter),
            commit=True
        )
        flash("Application submitted successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template("apply.html", job=job)


# ═══════════════════════════════════════════════════════════════════════════════
# EMPLOYER ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/post-job", methods=["GET", "POST"])
@login_required
@role_required("employer")
def post_job():
    if request.method == "POST":
        db_execute(
            """INSERT INTO jobs
               (employer_id, title, company, location, category, salary, description, requirements, job_type)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                session["user_id"],
                request.form["title"].strip(),
                request.form["company"].strip(),
                request.form["location"].strip(),
                request.form["category"].strip(),
                request.form.get("salary", "").strip(),
                request.form["description"].strip(),
                request.form.get("requirements", "").strip(),
                request.form.get("job_type", "Full-time"),
            ),
            commit=True
        )
        flash("Job posted successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template("post_job.html")


@app.route("/edit-job/<int:job_id>", methods=["GET", "POST"])
@login_required
@role_required("employer")
def edit_job(job_id):
    job = db_execute("SELECT * FROM jobs WHERE id=? AND employer_id=?",
                     (job_id, session["user_id"]), fetchone=True)
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        db_execute(
            """UPDATE jobs SET title=?, company=?, location=?, category=?,
               salary=?, description=?, requirements=?, job_type=? WHERE id=?""",
            (
                request.form["title"].strip(),
                request.form["company"].strip(),
                request.form["location"].strip(),
                request.form["category"].strip(),
                request.form.get("salary", "").strip(),
                request.form["description"].strip(),
                request.form.get("requirements", "").strip(),
                request.form.get("job_type", "Full-time"),
                job_id,
            ),
            commit=True
        )
        flash("Job updated successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template("edit_job.html", job=job)


@app.route("/delete-job/<int:job_id>")
@login_required
@role_required("employer", "admin")
def delete_job(job_id):
    db_execute("UPDATE jobs SET is_active=0 WHERE id=?", (job_id,), commit=True)
    flash("Job removed.", "info")
    return redirect(url_for('dashboard'))


@app.route("/job-applications/<int:job_id>")
@login_required
@role_required("employer")
def job_applications(job_id):
    job = db_execute("SELECT * FROM jobs WHERE id=? AND employer_id=?",
                     (job_id, session["user_id"]), fetchone=True)
    if not job:
        flash("Unauthorized.", "danger")
        return redirect(url_for('dashboard'))

    apps = db_execute(
        """SELECT a.*, u.username, u.email FROM applications a
           JOIN users u ON a.seeker_id=u.id WHERE a.job_id=? ORDER BY a.applied_at DESC""",
        (job_id,), fetchall=True
    ) or []
    return render_template("job_applications.html", job=job, applications=apps)


@app.route("/update-status/<int:app_id>/<status>")
@login_required
@role_required("employer", "admin")
def update_status(app_id, status):
    if status not in ("Pending", "Reviewed", "Accepted", "Rejected"):
        flash("Invalid status.", "danger")
        return redirect(url_for('dashboard'))
    db_execute("UPDATE applications SET status=? WHERE id=?", (status, app_id), commit=True)
    flash(f"Application marked as {status}.", "success")
    return redirect(request.referrer or url_for('dashboard'))


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/delete-user/<int:user_id>")
@login_required
@role_required("admin")
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        flash("Cannot delete yourself.", "danger")
        return redirect(url_for('dashboard'))
    db_execute("DELETE FROM users WHERE id=?", (user_id,), commit=True)
    flash("User deleted.", "info")
    return redirect(url_for('dashboard'))


@app.route("/admin/toggle-job/<int:job_id>")
@login_required
@role_required("admin")
def admin_toggle_job(job_id):
    job = db_execute("SELECT is_active FROM jobs WHERE id=?", (job_id,), fetchone=True)
    if job:
        db_execute("UPDATE jobs SET is_active=? WHERE id=?",
                   (1 - job["is_active"], job_id), commit=True)
        flash("Job status toggled.", "info")
    return redirect(url_for('dashboard'))


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

init_db()   # Always runs — whether `python app.py` or `gunicorn app:app`

if __name__ == "__main__":
    print(f" Database: {'PostgreSQL' if USE_POSTGRES else 'SQLite (local)'}")
    print("  http://127.0.0.1:5000")
    app.run(debug=True)