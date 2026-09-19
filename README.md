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

## 🔑 Default Credentials

When initialized with sample seed data, the following demo accounts are created:

| Role | Username | Password | Notes |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `admin` | `admin123` (or `.env` value) | System Super Admin |
| **Hall Manager** | `mukti_mgr` | `manager123` | Muktijoddha Hall Manager |
| **Hall Manager** | `ekushe_mgr` | `manager123` | Amar Ekushe Hall Manager |
| **Student** | `student1` | `student123` | Room 102 |
| **Student** | `student2` | `student123` | Room 103 |

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
