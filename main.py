import os
from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from database import engine, SessionLocal, Base, DATABASE_URL, acquire_app_lock, release_app_lock
import models
import auth
from routers import auth_router, student_router, manager_router, admin_router, public_router

# Initialize database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="eDining Management System", version="1.0.0")

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware to prevent client-side caching of static files (index.html, app.js, etc.)
@app.middleware("http")
async def add_no_cache_header(request, call_next):
    # Reset per-request billing cache (rates/charges lookups) so each request
    # re-reads fresh data while keeping loop lookups cheap.
    import billing_helper
    billing_helper.request_cache_clear()
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Seed initial data if database is empty
def seed_data():
    db = SessionLocal()
    try:
        # Migration: add new columns if they don't exist
        from sqlalchemy import inspect, text
        inspector = inspect(db.bind)
        columns = [c["name"] for c in inspector.get_columns("users")]
        if "meal_preference" not in columns:
            db.execute(text("ALTER TABLE users ADD COLUMN meal_preference VARCHAR DEFAULT 'normal'"))
        if "fish_egg_pref" not in columns:
            db.execute(text("ALTER TABLE users ADD COLUMN fish_egg_pref VARCHAR DEFAULT 'normal'"))
            db.execute(text("ALTER TABLE users ADD COLUMN meat_pref VARCHAR DEFAULT 'normal'"))
        hall_cols = [c["name"] for c in inspector.get_columns("halls")]
        if "guest_charge_per_day" not in hall_cols:
            db.execute(text("ALTER TABLE halls ADD COLUMN guest_charge_per_day FLOAT DEFAULT 5.0"))
        menu_cols = [c["name"] for c in inspector.get_columns("daily_menu")]
        if "pangas_served" not in menu_cols:
            db.execute(text("ALTER TABLE daily_menu ADD COLUMN pangas_served BOOLEAN DEFAULT FALSE"))
            db.execute(text("ALTER TABLE daily_menu ADD COLUMN other_fish_served BOOLEAN DEFAULT FALSE"))
            db.execute(text("ALTER TABLE daily_menu ADD COLUMN mutton_served BOOLEAN DEFAULT FALSE"))
        cycle_cols = [c["name"] for c in inspector.get_columns("meal_cycles")]
        if "full_rate_days" not in cycle_cols:
            db.execute(text("ALTER TABLE meal_cycles ADD COLUMN full_rate_days VARCHAR DEFAULT '4'"))
        expense_cols = [c["name"] for c in inspector.get_columns("expenses")]
        if "paid" not in expense_cols:
            db.execute(text("ALTER TABLE expenses ADD COLUMN paid BOOLEAN DEFAULT TRUE"))
        Base.metadata.create_all(bind=engine)  # ensures new tables like inventory_payments exist
        db.commit()
        from sqlalchemy import inspect as _insp
        fee_cols = [c["name"] for c in _insp(db.bind).get_columns("daily_fee_overrides")]
        if "guest_charge" not in fee_cols:
            db.execute(text("ALTER TABLE daily_fee_overrides ADD COLUMN guest_charge FLOAT"))
            db.commit()
        
        # Check if halls exist
        if db.query(models.Hall).count() == 0:
            mukti = models.Hall(name="Muktijoddha Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
            ekushe = models.Hall(name="Amar Ekushe Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
            db.add(mukti)
            db.add(ekushe)
            db.commit()
            db.refresh(mukti)
            db.refresh(ekushe)
            
            # Create users
            # 1. Superadmin (credentials from env or defaults)
            admin_username = os.environ.get("ADMIN_USERNAME", "admin")
            admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
            admin_name = os.environ.get("ADMIN_NAME", "System Super Admin")
            admin_phone = os.environ.get("ADMIN_PHONE", "01711223344")
            admin = models.User(
                username=admin_username,
                password_hash=auth.get_password_hash(admin_password),
                role="superadmin",
                name=admin_name,
                phone=admin_phone,
                balance=0.0
            )
            
            # 2. Managers
            mgr1 = models.User(
                username="mukti_mgr",
                password_hash=auth.get_password_hash("manager123"),
                role="manager",
                hall_id=mukti.id,
                room_number="302",
                name="Sabbir Ahmed (Mukti Mgr)",
                phone="01911223344",
                balance=500.0,
                free_meal=True
            )
            mgr2 = models.User(
                username="ekushe_mgr",
                password_hash=auth.get_password_hash("manager123"),
                role="manager",
                hall_id=ekushe.id,
                room_number="205",
                name="Tanvir Hossain (Ekushe Mgr)",
                phone="01811223344",
                balance=500.0,
                free_meal=True
            )
            
            # 3. Students
            student1 = models.User(
                username="student1",
                password_hash=auth.get_password_hash("student123"),
                role="student",
                hall_id=mukti.id,
                room_number="102",
                name="Kamrul Islam",
                phone="01511223344",
                balance=1500.0
            )
            student2 = models.User(
                username="student2",
                password_hash=auth.get_password_hash("student123"),
                role="student",
                hall_id=mukti.id,
                room_number="103",
                name="Rakib Hasan",
                phone="01611223344",
                balance=2000.0
            )
            student3 = models.User(
                username="student3",
                password_hash=auth.get_password_hash("student123"),
                role="student",
                hall_id=ekushe.id,
                room_number="210",
                name="Sakib Al Hasan",
                phone="01311223344",
                balance=1200.0
            )
            
            db.add_all([admin, mgr1, mgr2, student1, student2, student3])
            db.commit()
            print("Database pre-seeded with sample data.")
    finally:
        db.close()

def migrate_db():
    from sqlalchemy import text
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            res = conn.execute(text("PRAGMA table_info(student_meal_statuses);")).fetchall()
            cols = [r[1] for r in res]
            if "is_deducted" not in cols:
                conn.execute(text("ALTER TABLE student_meal_statuses ADD COLUMN is_deducted BOOLEAN DEFAULT 0;"))
                print("Migration: Added is_deducted to student_meal_statuses")
            if "amount_deducted" not in cols:
                conn.execute(text("ALTER TABLE student_meal_statuses ADD COLUMN amount_deducted FLOAT DEFAULT 0.0;"))
                print("Migration: Added amount_deducted to student_meal_statuses")
                
            res_users = conn.execute(text("PRAGMA table_info(users);")).fetchall()
            cols_users = [r[1] for r in res_users]
            if "email" not in cols_users:
                conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR;"))
                print("Migration: Added email to users")
            if "status" not in cols_users:
                conn.execute(text("ALTER TABLE users ADD COLUMN status VARCHAR DEFAULT 'both';"))
                print("Migration: Added status to users")
                
            res_cycles = conn.execute(text("PRAGMA table_info(meal_cycles);")).fetchall()
            cols_cycles = [r[1] for r in res_cycles]
            if "start_date" not in cols_cycles:
                conn.execute(text("ALTER TABLE meal_cycles ADD COLUMN start_date VARCHAR;"))
                print("Migration: Added start_date to meal_cycles")
            if "end_date" not in cols_cycles:
                conn.execute(text("ALTER TABLE meal_cycles ADD COLUMN end_date VARCHAR;"))
                print("Migration: Added end_date to meal_cycles")

            res_expenses = conn.execute(text("PRAGMA table_info(expenses);")).fetchall()
            cols_expenses = [r[1] for r in res_expenses]
            if "meal_type" not in cols_expenses:
                conn.execute(text("ALTER TABLE expenses ADD COLUMN meal_type VARCHAR;"))
                print("Migration: Added meal_type to expenses")
                
            res_cycles2 = conn.execute(text("PRAGMA table_info(meal_cycles);")).fetchall()
            cols_cycles2 = [r[1] for r in res_cycles2]
            if "lunch_only_rate_percentage" not in cols_cycles2:
                conn.execute(text("ALTER TABLE meal_cycles ADD COLUMN lunch_only_rate_percentage FLOAT DEFAULT 0.4;"))
                print("Migration: Added lunch_only_rate_percentage to meal_cycles")
            if "dinner_only_rate_percentage" not in cols_cycles2:
                conn.execute(text("ALTER TABLE meal_cycles ADD COLUMN dinner_only_rate_percentage FLOAT DEFAULT 0.6;"))
                print("Migration: Added dinner_only_rate_percentage to meal_cycles")
    else:
        # PostgreSQL: check for missing columns via information_schema
        with engine.begin() as conn:
            existing = {r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'meal_cycles'"
            )).fetchall()}
            if "full_rate_days" not in existing:
                conn.execute(text("ALTER TABLE meal_cycles ADD COLUMN full_rate_days VARCHAR DEFAULT '4';"))
                print("Migration: Added full_rate_days to meal_cycles")

import asyncio

async def periodic_deductions_task():
    """
    Background worker that runs every 30 minutes to call deduct_passed_meals.
    A PostgreSQL advisory lock ensures only one worker runs it (deduct is
    idempotent per status via is_deducted, but the lock avoids races across workers).
    """
    while True:
        await asyncio.sleep(1800) # Sleep first, run periodically
        db = SessionLocal()
        token = None
        try:
            token = acquire_app_lock(db, key=0xED1_51)
            if token is None:
                print("Background Task: another worker holds the deduction lock; skipping.")
                continue
            import billing_helper
            billing_helper.deduct_passed_meals(db)
            print("Background Task: Successfully completed periodic deductions of passed meals.")
        except Exception as e:
            print(f"Background Task Error: {e}")
        finally:
            release_app_lock(token)
            db.close()

@app.on_event("startup")
async def startup_event():
    # Raise FastAPI/Starlette threadpool for sync endpoints so many
    # concurrent requests can run at once instead of queueing on ~40 threads.
    import anyio
    try:
        anyio.to_thread.current_default_thread_limiter().total_tokens = int(
            os.environ.get("APP_THREADPOOL_SIZE", "500")
        )
    except Exception as e:
        print("Could not raise threadpool size:", e)
    # Migrations + seeding are guarded so only one worker runs them at startup.
    db = SessionLocal()
    token = None
    try:
        token = acquire_app_lock(db, key=0xED1_50)
        if token is None:
            print("Startup init: another worker is migrating/seeding; skipping.")
            return
        migrate_db()
        seed_data()
        # Import manual data from Excel (skip if file doesn't exist, e.g. in Docker)
        import import_helper
        db2 = SessionLocal()
        try:
            if os.path.exists(r"old_data\data.xlsx") or os.path.exists("old_data/data.xlsx"):
                import_helper.import_manual_data(db2)
            else:
                print("No Excel data file found. Skipping manual import.")
        finally:
            db2.close()
    finally:
        release_app_lock(token)
        db.close()

    # Start the periodic deductions background worker
    asyncio.create_task(periodic_deductions_task())


# Mount API Routers
app.include_router(auth_router.router, prefix="/api")
app.include_router(student_router.router, prefix="/api")
app.include_router(manager_router.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")
app.include_router(public_router.router, prefix="/api")

# Create static folder if not exists
os.makedirs("static", exist_ok=True)

# Serve static assets (js, css, images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve frontend HTML pages explicitly
@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

@app.get("/search")
async def serve_search():
    return FileResponse("static/search.html")

# Also serve approve page
@app.get("/approve")
async def serve_approve():
    return FileResponse("static/approve.html")
