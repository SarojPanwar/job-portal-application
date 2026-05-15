
"""
Job Portal Web Application
===========================
Main Flask application entry point.
All routes, authentication, and logic are defined here.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from flask.cli import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from functools import wraps
from datetime import datetime

# ─── App Configuration ──────────────────────────────────────────────────────
app = Flask(__name__)

from dotenv import load_dotenv
load_dotenv()
app.secret_key = os.getenv("app.secret_key","dev-only-fallback")
DATABASE = "job_portal.db"



# ─── Database Helpers ────────────────────────────────────────────────────────

def get_db():
    """Open a new database connection if not already open for this request."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row   # allows dict-like column access
    return db


@app.teardown_appcontext
def close_db(exception):
    """Automatically close DB connection at end of each request."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """Create all tables if they don't exist."""
    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT UNIQUE NOT NULL,
                email     TEXT UNIQUE NOT NULL,
                password  TEXT NOT NULL,
                role      TEXT NOT NULL DEFAULT 'seeker',
                company   TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                employer_id INTEGER NOT NULL,
                title       TEXT NOT NULL,
                company     TEXT NOT NULL,
                location    TEXT NOT NULL,
                category    TEXT NOT NULL,
                salary      TEXT,
                description TEXT NOT NULL,
                requirements TEXT,
                job_type    TEXT DEFAULT 'Full-time',
                is_active   INTEGER DEFAULT 1,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employer_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS applications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      INTEGER NOT NULL,
                seeker_id   INTEGER NOT NULL,
                cover_letter TEXT,
                status      TEXT DEFAULT 'Pending',
                applied_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id),
                FOREIGN KEY (seeker_id) REFERENCES users(id),
                UNIQUE(job_id, seeker_id)
            );
        """)

        # Create default admin account
        existing = db.execute("SELECT id FROM users WHERE role='admin'").fetchone()
        if not existing:
            db.execute(
                "INSERT INTO users (username, email, password, role) VALUES (?,?,?,?)",
                ("admin", "admin@jobportal.com",
                 generate_password_hash("admin12345"), "admin")
            )
        db.commit()


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
    db = get_db()
    recent_jobs = db.execute(
        """SELECT j.* FROM jobs j WHERE j.is_active = 1
           ORDER BY j.created_at DESC LIMIT 6"""
    ).fetchall()
    stats = {
        "jobs":      db.execute("SELECT COUNT(*) FROM jobs WHERE is_active=1").fetchone()[0],
        "employers": db.execute("SELECT COUNT(*) FROM users WHERE role='employer'").fetchone()[0],
        "seekers":   db.execute("SELECT COUNT(*) FROM users WHERE role='seeker'").fetchone()[0],
        "apps":      db.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
    }
    categories = db.execute(
        "SELECT category, COUNT(*) as cnt FROM jobs WHERE is_active=1 GROUP BY category ORDER BY cnt DESC LIMIT 8"
    ).fetchall()
    return render_template("index.html", recent_jobs=recent_jobs, stats=stats, categories=categories)


@app.route("/jobs")
def job_list():
    db = get_db()
    keyword  = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    category = request.args.get("category", "").strip()
    job_type = request.args.get("job_type", "").strip()

    query = "SELECT j.* FROM jobs j WHERE j.is_active = 1"
    params = []
    if keyword:
        query += " AND (j.title LIKE ? OR j.description LIKE ? OR j.company LIKE ?)"
        params += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
    if location:
        query += " AND j.location LIKE ?"
        params.append(f"%{location}%")
    if category:
        query += " AND j.category = ?"
        params.append(category)
    if job_type:
        query += " AND j.job_type = ?"
        params.append(job_type)
    query += " ORDER BY j.created_at DESC"

    jobs = db.execute(query, params).fetchall()
    categories = db.execute("SELECT DISTINCT category FROM jobs WHERE is_active=1").fetchall()
    return render_template("jobs.html", jobs=jobs, categories=categories,
                           keyword=keyword, location=location,
                           category=category, job_type=job_type)


@app.route("/jobs/<int:job_id>")
def job_detail(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=? AND is_active=1", (job_id,)).fetchone()
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for('job_list'))

    already_applied = False
    if session.get('role') == 'seeker':
        already_applied = db.execute(
            "SELECT id FROM applications WHERE job_id=? AND seeker_id=?",
            (job_id, session['user_id'])
        ).fetchone() is not None

    return render_template("job_detail.html", job=job, already_applied=already_applied)


# ─── Auth Routes ─────────────────────────────────────────────────────────────

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

        db = get_db()
        if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
            flash("Username already taken.", "danger")
            return redirect(url_for('register'))
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash("Email already registered.", "danger")
            return redirect(url_for('register'))

        db.execute(
            "INSERT INTO users (username, email, password, role, company) VALUES (?,?,?,?,?)",
            (username, email, generate_password_hash(password), role, company)
        )
        db.commit()
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
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

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


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    db  = get_db()
    uid = session["user_id"]

    if session["role"] == "seeker":
        applications = db.execute(
            """SELECT a.*, j.title, j.company, j.location, j.job_type
               FROM applications a JOIN jobs j ON a.job_id=j.id
               WHERE a.seeker_id=? ORDER BY a.applied_at DESC""",
            (uid,)
        ).fetchall()
        return render_template("dashboard_seeker.html", applications=applications)

    elif session["role"] == "employer":
        jobs = db.execute(
            "SELECT * FROM jobs WHERE employer_id=? ORDER BY created_at DESC", (uid,)
        ).fetchall()
        total_apps = db.execute(
            "SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id=j.id WHERE j.employer_id=?", (uid,)
        ).fetchone()[0]
        return render_template("dashboard_employer.html", jobs=jobs, total_apps=total_apps)

    elif session["role"] == "admin":
        users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        jobs  = db.execute(
            "SELECT j.*, u.username AS employer_name FROM jobs j JOIN users u ON j.employer_id=u.id ORDER BY j.created_at DESC"
        ).fetchall()
        apps  = db.execute(
            "SELECT a.*, j.title, u.username AS seeker_name FROM applications a JOIN jobs j ON a.job_id=j.id JOIN users u ON a.seeker_id=u.id ORDER BY a.applied_at DESC"
        ).fetchall()
        stats = {
            "users": len(users), "jobs": len(jobs), "apps": len(apps),
            "employers": sum(1 for u in users if u["role"] == "employer"),
            "seekers":   sum(1 for u in users if u["role"] == "seeker"),
        }
        return render_template("dashboard_admin.html", users=users, jobs=jobs, apps=apps, stats=stats)

    return redirect(url_for('index'))


# ─── Seeker Routes ───────────────────────────────────────────────────────────

@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
@login_required
@role_required("seeker")
def apply_job(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=? AND is_active=1", (job_id,)).fetchone()
    if not job:
        flash("Job not found or no longer active.", "danger")
        return redirect(url_for('job_list'))

    if db.execute("SELECT id FROM applications WHERE job_id=? AND seeker_id=?",
                  (job_id, session["user_id"])).fetchone():
        flash("You have already applied for this job.", "info")
        return redirect(url_for('job_detail', job_id=job_id))

    if request.method == "POST":
        cover_letter = request.form.get("cover_letter", "").strip()
        db.execute(
            "INSERT INTO applications (job_id, seeker_id, cover_letter) VALUES (?,?,?)",
            (job_id, session["user_id"], cover_letter)
        )
        db.commit()
        flash("Application submitted successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template("apply.html", job=job)


# ─── Employer Routes ─────────────────────────────────────────────────────────

@app.route("/post-job", methods=["GET", "POST"])
@login_required
@role_required("employer")
def post_job():
    if request.method == "POST":
        db = get_db()
        db.execute(
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
            )
        )
        db.commit()
        flash("Job posted successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template("post_job.html")


@app.route("/edit-job/<int:job_id>", methods=["GET", "POST"])
@login_required
@role_required("employer")
def edit_job(job_id):
    db  = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=? AND employer_id=?",
                     (job_id, session["user_id"])).fetchone()
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for('dashboard'))

    if request.method == "POST":
        db.execute(
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
            )
        )
        db.commit()
        flash("Job updated successfully!", "success")
        return redirect(url_for('dashboard'))

    return render_template("edit_job.html", job=job)


@app.route("/delete-job/<int:job_id>")
@login_required
@role_required("employer", "admin")
def delete_job(job_id):
    db = get_db()
    db.execute("UPDATE jobs SET is_active=0 WHERE id=?", (job_id,))
    db.commit()
    flash("Job removed.", "info")
    return redirect(url_for('dashboard'))


@app.route("/job-applications/<int:job_id>")
@login_required
@role_required("employer")
def job_applications(job_id):
    db  = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=? AND employer_id=?",
                     (job_id, session["user_id"])).fetchone()
    if not job:
        flash("Unauthorized.", "danger")
        return redirect(url_for('dashboard'))

    apps = db.execute(
        """SELECT a.*, u.username, u.email FROM applications a
           JOIN users u ON a.seeker_id=u.id WHERE a.job_id=? ORDER BY a.applied_at DESC""",
        (job_id,)
    ).fetchall()
    return render_template("job_applications.html", job=job, applications=apps)


@app.route("/update-status/<int:app_id>/<status>")
@login_required
@role_required("employer", "admin")
def update_status(app_id, status):
    if status not in ("Pending", "Reviewed", "Accepted", "Rejected"):
        flash("Invalid status.", "danger")
        return redirect(url_for('dashboard'))
    db = get_db()
    db.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
    db.commit()
    flash(f"Application marked as {status}.", "success")
    return redirect(request.referrer or url_for('dashboard'))


# ─── Admin Routes ────────────────────────────────────────────────────────────

@app.route("/admin/delete-user/<int:user_id>")
@login_required
@role_required("admin")
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        flash("Cannot delete yourself.", "danger")
        return redirect(url_for('dashboard'))
    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    flash("User deleted.", "info")
    return redirect(url_for('dashboard'))


@app.route("/admin/toggle-job/<int:job_id>")
@login_required
@role_required("admin")
def admin_toggle_job(job_id):
    db  = get_db()
    job = db.execute("SELECT is_active FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job:
        db.execute("UPDATE jobs SET is_active=? WHERE id=?", (1 - job["is_active"], job_id))
        db.commit()
        flash("Job status toggled.", "info")
    return redirect(url_for('dashboard'))


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("✅  Database initialized")
    print("👤  Admin login: admin@jobportal.com / admin12345")
    print("🚀  Starting server at http://127.0.0.1:5000")
    app.run()