# eDining - Hall & Dining Management System

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**eDining** is a comprehensive, production-ready dining and mess hall management platform built for university halls, student dormitories, and shared mess operations. It automates daily meal tracking, dynamic cost calculations, bKash deposits, expense reconciliation, automated background balance deductions, and PDF billing statement generation.

---

## 🚀 Key Features

### 1. 🍽️ Smart Meal Tracking & Toggles
- **Flexible Meal Modes**: Students can toggle between `both` (lunch & dinner), `lunch_only`, `dinner_only`, or `off` daily.
- **Cut-off Deadlines**: Configurable daily cut-off times prevent last-minute meal state tampering.
- **Special Dietary Preferences**: Tracks egg alternatives, meat preferences (beef, mutton, chicken), and vegetarian flags.

### 2. 💰 Dynamic Billing & Cost Reconciliation Engine
- **Flexible Rate Calculation**: Automatically distributes shared daily groceries, utilities, and manager charges across consuming units.
- **Weighted Meal Costs**: Accurately splits costs according to lunch/dinner budget ratios.
- **Guest Meal Management**: Separate guest meal counts with custom hall surcharges.
- **Automated Daily Deductions**: Background scheduler automatically deducts daily dining expenses from student balances.
- **Negative Balance Handling & Cycle Rollover**: Balances smoothly transition into consecutive billing cycles.

### 3. 💳 bKash Deposits & Financial Auditing
- **Automated & Manual Deposit Flows**: Students can claim payments using bKash Transaction IDs (TrxID).
- **Manager Approval Dashboard**: Managers can inspect, approve, or reject deposits with complete audit logs.
- **Ledger System**: Complete immutable financial transaction history for every user.

### 4. 📄 Professional PDF Receipt & Bill Generation
- **Automated Mess Bills**: Clean, printable billing summaries for students and hall notice boards.
- **Barcoded Receipts**: Digital bills generated using `fpdf2` and `python-barcode`.

### 5. 👥 Multi-Tier Role-Based Access Control
- **Superadmin / Admin**: Create & manage halls, assign hall managers, oversee global platform financials.
- **Hall Manager**: Open/close meal cycles, record daily food expenses, manage student deposits, inspect meal attendance sheets.
- **Student**: View live balance, update meal preferences, track monthly ledgers, and download receipts.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Database**: PostgreSQL 16 (production/Docker) or SQLite (lightweight local testing)
- **Frontend**: Clean Vanilla JavaScript SPA with modern CSS and reactive UI
- **Containerization**: Docker, Docker Compose
- **PDF Generation**: `fpdf2`, `python-barcode`
- **Security**: Password hashing via `bcrypt`, JWT-based authentication via `pyjwt`

---

## ⚡ Quick Start (Docker - Recommended)

The easiest way to get eDining up and running is with Docker and Docker Compose.

### Windows
Double-click `setup.bat` or run:
```cmd
setup.bat
```

### Linux / macOS
Run the setup shell script:
```bash
chmod +x setup.sh
./setup.sh
```

### Or using Docker Compose directly
1. Create your `.env` configuration:
   ```bash
   cp .env.example .env
   ```
2. Build and run:
   ```bash
   docker compose up -d --build
   ```

Once started, access the web portal at:
👉 **[http://localhost:8090](http://localhost:8090)**

---

## 💻 Manual Setup (Without Docker)

If you prefer running without Docker using a local Python virtual environment and SQLite:

### 1. Clone the repository
```bash
git clone https://github.com/kh0kamoni/eDining.git
cd eDining
```

### 2. Create a Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
*(By default, without a `DATABASE_URL` set, the app will automatically use a local SQLite file `dining.db` and auto-seed initial sample data).*

### 5. Start the Server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## 🔑 First-Time Setup & Account Management

### 1. Super Admin Account Creation
On first-time setup (via `setup.bat`, `./setup.sh`, or `.env`), the system prompts you to configure the initial **Super Admin** account:
- **Username**: Configured during setup (default: `admin`)
- **Password**: Configured during setup (default: `admin123`)
- **Role**: `superadmin`

> [!IMPORTANT]
> **No hardcoded username or password**: There are no hardcoded credentials baked into the system. The Super Admin username and password are set exclusively by the user who initializes the project during first-time setup.

### 2. Setting Up Subsequent Accounts
To maintain a clean and isolated system, **no dummy managers or student accounts are created by default**. All other accounts are provisioned and managed by the Super Admin:

1. **Dining Halls**:
   - Log into the dashboard with your Super Admin credentials.
   - Go to **Admin Panel** $\rightarrow$ **Tables** $\rightarrow$ **Halls**.
   - Create and configure your institution's dining halls (rates, manager charges, guest policies).
2. **Hall Managers & Staff**:
   - Go to **Admin Panel** $\rightarrow$ **Tables** $\rightarrow$ **Users**.
   - Click **Add Row** to create managers, assign them to halls, and grant manager permissions.
3. **Students**:
   - **Bulk Import**: Go to **Admin Panel** $\rightarrow$ **Users** and click **Bulk Add Users** to paste rooms, names, and phone numbers in bulk.
   - **Self-Registration**: If the `signup` feature flag is enabled in the Admin Panel, students can register directly from the login page.
   - **Single Add**: Add individual students directly via the Users table.

### 3. Pre-Seeding Existing Halls & Users via CSV
The system includes an automated migration and pre-seeding mechanism for existing institutional setups:
- **`halls.csv`**: Contains pre-configured dining halls, guest rates, manager charges, and guest charges.
  - When present, the setup wizard interactively asks if you want to initialize halls from `halls.csv`.
- **`users.csv`**: Contains existing user accounts, roles (`manager`, `student`), room numbers, dietary preferences, balances, and password hashes.
  - When present, the setup wizard interactively asks if you want to initialize users from `users.csv`.
- **Password Support**: Supports both existing bcrypt hashes (e.g., `$2b$...`) and plaintext passwords (hashed automatically).
- **Idempotent**: Existing halls and users with duplicate identifiers are safely skipped without overwriting.
- **Manual / CLI Import**: You can also run or re-run imports at any time via CLI:
  ```bash
  # Import users (and auto-resolve halls)
  python import_helper.py users.csv
  ```

---

## 👨‍🍳 Manager Guide: Starting a New Month & Daily Operations

When a new manager logs into the system for their assigned dining hall, here is the complete step-by-step workflow:

### 1. Starting a New Meal Cycle
1. **Log in**: Sign into the portal with your manager account.
2. **Dashboard Overview**: If no meal cycle is running, the dashboard displays `No Active Cycle` with a **Create Cycle** button.
3. **Create Cycle**:
   - Click **Create Cycle**.
   - Choose the target **Month** (e.g., `2026-10`).
   - Set the daily **Cutoff Time** (e.g., `20:00` / 8:00 PM) after which students cannot toggle meals for the next day.
   - *(Optional)* Specify custom **Start Date** and **End Date** if running a mid-month or non-standard cycle.
   - Set lunch/dinner cost allocation percentages (defaults to `50% / 50%`).
4. **Activate**:
   - Click **Start Cycle**. The system automatically seeds meal schedules for all students enrolled in your hall based on their default dining status (`both`, `lunch_only`, `dinner_only`).
   - Click **Activate Cycle** when ready for live operations.

### 2. Daily Manager Routines
- **Log Daily Expenses (Bazar)**:
  - Go to **Expenses** $\rightarrow$ **Add Expense** (or **Batch Add**).
  - Enter item category (`bazar`, `spice`, `gas`, `staff_wage`), description, and amount.
  - The system dynamically updates the live running meal rate in real time.
- **Update Daily Menu**:
  - Open **Daily Menu**. Enter lunch and dinner dishes.
  - Toggle dietary flags if fish, pangas, beef, or mutton are served. The system automatically honors student dietary preferences (egg substitutions, alternative proteins).
- **Print Daily Attendance Sheet**:
  - Click **Print Meal Sheet** for the date.
  - A clean, print-optimized grid organized by room number is generated for dining hall staff to tick attendance.
- **Manage Deposits**:
  - **Cash Deposits**: Record cash collected in **Deposits** $\rightarrow$ **Add Deposit**.
  - **bKash Payments**: Review and approve student-submitted bKash transactions.
  - Balance updates instantly and confirmation emails are dispatched automatically.

### 3. Month-End Billing & Closing Cycle
1. **Review Ledger & Financial Summary**:
   - Check **Financial Summary** to view total expenses, guest contributions, total paying units, and running meal rate.
   - Review the **Profit / Money Flow** statement to confirm total cash in hand versus bank/mobile banking balances.
2. **Close Cycle**:
   - Click **Close Cycle**. The billing engine reconciles exact daily meal costs and manager charges against each student's deposits.
   - Final balances carry forward cleanly to the student's overall account for the next month.
3. **Print / Email Statements**:
   - Generate full cycle summary PDFs or email digital bill receipts directly to students with one click.
4. **Reopen Support**:
   - If an expense or adjustment was missed, click **Reopen Cycle** to safely unfinalize balances, make adjustments, and re-close.

---

## 🧪 Testing

The repository includes a comprehensive test suite covering 64 unit and integration test cases across billing calculations, edge cases, negative balances, multi-cycle rollovers, and bKash workflows:

```bash
python verify_system.py
```

Expected output:
```text
................................................................
----------------------------------------------------------------------
Ran 64 tests in 15.105s

OK
```

---

## 📖 API Documentation

Interactive API documentation is automatically provided by FastAPI:
- **Swagger UI**: [http://localhost:8090/docs](http://localhost:8090/docs) (or `:8000/docs` in manual mode)
- **ReDoc**: [http://localhost:8090/redoc](http://localhost:8090/redoc)

---

## 📂 Project Structure

```text
eDining/
├── Dockerfile                  # Application container definition
├── docker-compose.yml          # Multi-container orchestration (App + PostgreSQL)
├── docker-entrypoint-initdb.d/ # PostgreSQL initialization scripts
├── requirements.txt            # Python dependencies
├── .env.example                # Configuration template
├── setup.bat                   # 1-Click launcher for Windows
├── setup.sh                    # 1-Command launcher for Linux/macOS
├── main.py                     # FastAPI application entry point & lifecycle
├── database.py                 # SQLAlchemy engine, session & connection pooling
├── models.py                   # Database schema definitions
├── schemas.py                  # Pydantic request/response validation
├── auth.py                     # JWT token generator & bcrypt password hashing
├── billing_helper.py           # Core dining billing & cost allocation algorithms
├── pdf_helper.py               # PDF receipt & invoice builder
├── import_helper.py            # Excel & bulk data import utilities
├── verify_system.py            # Complete test suite (64 automated tests)
├── routers/                    # API route controllers
│   ├── auth_router.py          # Authentication & token endpoints
│   ├── admin_router.py         # Superadmin management endpoints
│   ├── manager_router.py       # Hall manager endpoints & financial actions
│   ├── student_router.py       # Student dashboard & meal status endpoints
│   └── public_router.py        # Public inquiries & hall data
└── static/                     # Frontend web client
    ├── index.html              # Main application single-page interface
    ├── approve.html            # Manager approval portal
    ├── search.html             # Student search & meal inquiry
    └── js/
        └── app.js              # Client-side UI logic & API integration
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
