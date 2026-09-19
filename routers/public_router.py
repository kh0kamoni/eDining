from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models
import billing_helper
import schemas
from datetime import date

router = APIRouter(prefix="/public", tags=["Public Portal"])

def _feature_allowed(name: str, db: Session) -> bool:
    """A transparency/feature flag is shown only when enabled and neither hidden nor locked."""
    def get(key):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        return row.value if row else ""
    enabled = get(f"feature_{name}_enabled") != "false"
    hidden = get(f"feature_{name}_hidden") == "true"
    locked = get(f"feature_{name}_locked") == "true"
    return enabled and not hidden and not locked

def _get_student_cycle(student: models.User, db: Session):
    """Latest cycle for the student's hall (any status, incl. closed), falling back to
    the latest cycle that actually holds the student's meal statuses (guests)."""
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == student.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if cycle:
        return cycle
    status_cycle_id = db.query(models.StudentMealStatus.meal_cycle_id).filter(
        models.StudentMealStatus.user_id == student.id
    ).order_by(models.StudentMealStatus.meal_cycle_id.desc()).first()
    if status_cycle_id:
        return db.query(models.MealCycle).filter(
            models.MealCycle.id == status_cycle_id[0]
        ).first()
    return None

def _cycle_limit(today_str: str, cycle) -> str:
    """Effective display cutoff: today, but never past the cycle's end date."""
    if cycle.end_date and cycle.end_date < today_str:
        return cycle.end_date
    return today_str

@router.get("/students")
def public_search_students(query: str = "", filter_type: str = "all", db: Session = Depends(get_db)):
    users = db.query(models.User).filter(
        models.User.role.in_(["student", "manager", "assistant_manager"])
    ).all()
    if query:
        q = query.lower().strip()
        users = [u for u in users if q in (u.name or "").lower() or q in (u.username or "").lower() or q in (u.room_number or "").lower()]
    # If filter by native/guest, check hall_id vs active cycle
    if filter_type in ("native", "guest"):
        cycle = db.query(models.MealCycle).order_by(models.MealCycle.month.desc()).first()
        if cycle:
            if filter_type == "native":
                users = [u for u in users if u.hall_id == cycle.hall_id]
            else:
                users = [u for u in users if u.hall_id != cycle.hall_id]
    return [{"id": u.id, "username": u.username, "name": u.name, "room_number": u.room_number, "hall_id": u.hall_id} for u in users[:50]]

@router.get("/students/{user_id}/statement")
def public_student_statement(user_id: int, db: Session = Depends(get_db)):
    student = db.query(models.User).filter(models.User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    
    # Get active cycle — try student's hall first, then any cycle where they have meal statuses
    cycle = _get_student_cycle(student, db)
    if not cycle:
        return {"student": {"name": student.name, "username": student.username, "room": student.room_number, "email": student.email or ""},
                "cycle": None, "daily_rates": [], "daily_meals": [], "deposits": [], "summary": {}}
    
    # Get the hall that owns this cycle (for guests, use host hall's charges)
    hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
    
    today_str = date.today().strftime("%Y-%m-%d")
    limit = _cycle_limit(today_str, cycle)
    
    # Daily rates up to today (but never past the cycle's end date)
    dates = [d for d in billing_helper.get_cycle_dates(cycle, restrict_to_today=True) if d <= limit]
    daily_rates = []
    for d in dates:
        dr = billing_helper.get_daily_meal_rates(cycle, d, db)
        daily_rates.append({"date": d, "lunch_rate": dr["lunch_rate"], "dinner_rate": dr["dinner_rate"], "final_rate": dr["final_rate"]})
    
    # Student's meal statuses (past + today for the log)
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.user_id == user_id,
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date <= limit
    ).order_by(models.StudentMealStatus.date).all()
    
    # Next meal status: first non-off record from today onwards (today's active meal, else next upcoming)
    next_meal_status = "off"
    upcoming = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.user_id == user_id,
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date >= today_str,
        models.StudentMealStatus.date <= limit
    ).order_by(models.StudentMealStatus.date).all()
    for uq in upcoming:
        if uq.status != "off":
            next_meal_status = uq.status
            break
    
    daily_meals = []
    guest_charge = hall.guest_charge_per_day if hall else 5.0
    mgr_charge = hall.manager_charge_per_day if hall else 5.0
    for s in statuses:
        dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
        mult = billing_helper._meal_multiplier(s.status)
        is_guest = s.is_guest
        mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
        if s.status == "off":
            charge = 0.0
        elif student.free_meal:
            charge = 0.0
        elif is_guest:
            if s.status in ("both",):
                charge = dr["final_rate"] + guest_charge
            elif s.status == "lunch_only":
                charge = (billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + guest_charge
            elif s.status == "dinner_only":
                charge = (billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + guest_charge
            elif s.status in ("double", "triple"):
                charge = (mult * dr["final_rate"]) + (mult * guest_charge)
            else:
                charge = dr["final_rate"] + guest_charge
        else:
            if s.status in ("both",):
                charge = dr["final_rate"] + mgr_charge
            elif s.status == "lunch_only":
                charge = (billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + mgr_charge
            elif s.status == "dinner_only":
                charge = (billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + mgr_charge
            elif s.status in ("double", "triple"):
                charge = (mult * dr["final_rate"]) + (mult * mgr_charge)
            else:
                charge = dr["final_rate"] + mgr_charge
        daily_meals.append({
            "date": s.date, "status": s.status, "lunch_ticked": s.ticked_lunch,
            "dinner_ticked": s.ticked_dinner, "is_guest": is_guest,
            "final_rate": dr["final_rate"], "charge": round(charge, 2)
        })
    
    # Deposits
    deposits = db.query(models.Deposit).filter(
        models.Deposit.user_id == user_id,
        models.Deposit.meal_cycle_id == cycle.id
    ).order_by(models.Deposit.date).all()
    
    total_deposits = sum(d.amount for d in deposits)
    total_charges = sum(m["charge"] for m in daily_meals)
    
    # Admin-controlled transparency for the /search portal
    visibility = {
        "daily_rates": _feature_allowed("transparency_daily_rate", db),
        "daily_expenses": _feature_allowed("transparency_daily_expense", db),
        "meal_count": _feature_allowed("transparency_meal_count", db),
        "daily_charges": _feature_allowed("transparency_daily_charge", db),
    }
    
    # Per-day transparency: total daily expenses + total meal count (non-off statuses that day)
    # meal_count MUST match manager /daily-rates "daily_meals" exactly:
    #   lunch eaters + dinner eaters, each counted with status multiplier, excluding free-meal users.
    daily_transparency = []
    if visibility["daily_expenses"] or visibility["meal_count"]:
        exp_by_date = {}
        cycle_expenses = db.query(models.Expense).filter(
            models.Expense.meal_cycle_id == cycle.id,
            models.Expense.date <= limit
        ).all()
        for e in cycle_expenses:
            exp_by_date[e.date] = exp_by_date.get(e.date, 0.0) + e.amount

        users_free = {u.id: u.free_meal for u in db.query(models.User).all()}
        lunch_by_date = {}
        dinner_by_date = {}
        all_day_statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.status != "off",
            models.StudentMealStatus.date <= limit
        ).all()
        for s in all_day_statuses:
            if users_free.get(s.user_id, False):
                continue
            mult = billing_helper._meal_multiplier(s.status)
            if s.status in ["both", "lunch_only", "double", "triple"]:
                lunch_by_date[s.date] = lunch_by_date.get(s.date, 0) + mult
            if s.status in ["both", "dinner_only", "double", "triple"]:
                dinner_by_date[s.date] = dinner_by_date.get(s.date, 0) + mult

        for d in dates:
            daily_transparency.append({
                "date": d,
                "total_expenses": round(exp_by_date.get(d, 0.0), 2) if visibility["daily_expenses"] else None,
                "meal_count": (lunch_by_date.get(d, 0) + dinner_by_date.get(d, 0)) if visibility["meal_count"] else None
            })
    
    return {
        "student": {"name": student.name, "username": student.username, "room": student.room_number, "free_meal": student.free_meal, "fish_egg_pref": student.fish_egg_pref or "normal", "meat_pref": student.meat_pref or "normal", "email": student.email or ""},
        "cycle": {"month": cycle.month, "status": cycle.status},
        "daily_rates": daily_rates if visibility["daily_rates"] else [],
        "daily_transparency": daily_transparency,
        "visibility": visibility,
        "daily_meals": daily_meals,
        "next_meal_status": next_meal_status,
        "deposits": [{"date": d.date, "amount": d.amount, "description": d.description} for d in deposits],
        "summary": {
            "total_deposits": round(total_deposits, 2),
            "total_charges": round(total_charges, 2),
            "balance": round(total_deposits - total_charges, 2)
        }
    }

@router.post("/deposit/claim")
def public_claim_deposit(username: str, trx_id: str, db: Session = Depends(get_db)):
    student = db.query(models.User).filter(models.User.username == username).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    trx_id_upper = trx_id.strip().upper()
    if not trx_id_upper or len(trx_id_upper) < 5 or not trx_id_upper.isalnum():
        raise HTTPException(status_code=400, detail="Invalid TrxID format.")
    
    trx = db.query(models.BkashReceivedSms).filter(
        models.BkashReceivedSms.trx_id == trx_id_upper
    ).first()
    if not trx:
        # TrxID not found — create pending for manager approval
        trx = models.BkashReceivedSms(
            trx_id=trx_id_upper, sender="Public Portal",
            amount=0.0, status="pending", is_claimed=True,
            claimed_by_user_id=student.id,
            date_received=date.today().strftime("%Y-%m-%d")
        )
        db.add(trx)
        db.commit()
        return {"status": "pending", "message": f"Transaction {trx_id_upper} submitted for manager approval.", "immediate": False}
    
    if trx.is_claimed:
        raise HTTPException(status_code=400, detail="TrxID already claimed.")
    
    # TrxID found — immediately credit
    trx.is_claimed = True
    trx.claimed_by_user_id = student.id
    trx.approved_amount = trx.amount
    trx.status = "approved"
    student.balance += trx.amount
    
    cycle = billing_helper.get_latest_cycle(db, student.hall_id)
    if cycle:
        dep = models.Deposit(
            user_id=student.id, meal_cycle_id=cycle.id,
            amount=trx.amount, date=date.today().strftime("%Y-%m-%d"),
            description="bKash Send Money (TrxID: " + trx_id_upper + ")"
        )
        db.add(dep)
    
    db.commit()
    return {"status": "success", "amount": trx.amount, "message": f"BDT {trx.amount:.2f} deposited to {student.name}.", "immediate": True}


def _public_report_data(user_id: int, db: Session) -> dict:
    """Builds the full report/ledger payload for a user (no auth) — same source data as /statement."""
    student = db.query(models.User).filter(models.User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    cycle = _get_student_cycle(student, db)
    if not cycle:
        raise HTTPException(status_code=404, detail="No active cycle found for this student.")

    hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
    hall_name = hall.name if hall else "eDining Hall"
    today_str = date.today().strftime("%Y-%m-%d")
    limit = _cycle_limit(today_str, cycle)

    # Deposits
    deposits = db.query(models.Deposit).filter(
        models.Deposit.user_id == user_id,
        models.Deposit.meal_cycle_id == cycle.id
    ).order_by(models.Deposit.date).all()
    deposits_data = [{"date": d.date, "amount": d.amount, "description": d.description or ""} for d in deposits]
    total_deposits = sum(d.amount for d in deposits)

    # Average daily rates up to today (same as manager ledger).
    # Days with zero expenses (dining was off) are excluded from the average.
    daily_l = 0.0; daily_d = 0.0; daily_f = 0.0; cnt = 0
    for d in billing_helper.get_cycle_dates(cycle, restrict_to_today=True):
        if d > limit:
            continue
        dr = billing_helper.get_daily_meal_rates(cycle, d, db)
        if dr["final_rate"] <= 0:
            continue
        daily_l += dr["lunch_rate"]; daily_d += dr["dinner_rate"]; daily_f += dr["final_rate"]; cnt += 1
    rates = {"lunch_rate": round(daily_l / cnt, 2) if cnt else 0,
             "dinner_rate": round(daily_d / cnt, 2) if cnt else 0,
             "final_rate": round(daily_f / cnt, 2) if cnt else 0}

    # Daily meal log with day_cost (same charge rules as /statement)
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.user_id == user_id,
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date <= limit
    ).order_by(models.StudentMealStatus.date).all()

    daily_meals = []
    total_bill = 0.0
    daily_meta = billing_helper.get_cycle_daily_meta(cycle, db, limit)
    for s in statuses:
        dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
        meta = daily_meta.get(s.date, {"expense": 0.0, "meal_count": 0})
        mult = billing_helper._meal_multiplier(s.status)
        mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
        if s.status == "off":
            charge = 0.0
        elif student.free_meal:
            charge = 0.0
        elif s.is_guest:
            if s.status in ("both",):
                charge = dr["final_rate"] + guest_charge
            elif s.status == "lunch_only":
                charge = (billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + guest_charge
            elif s.status == "dinner_only":
                charge = (billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + guest_charge
            elif s.status in ("double", "triple"):
                charge = (mult * dr["final_rate"]) + (mult * guest_charge)
            else:
                charge = dr["final_rate"] + guest_charge
        else:
            if s.status in ("both",):
                charge = dr["final_rate"] + mgr_charge
            elif s.status == "lunch_only":
                charge = (billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + mgr_charge
            elif s.status == "dinner_only":
                charge = (billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"]) + mgr_charge
            elif s.status in ("double", "triple"):
                charge = (mult * dr["final_rate"]) + (mult * mgr_charge)
            else:
                charge = dr["final_rate"] + mgr_charge

        if s.status != "off":
            total_bill += charge
        daily_meals.append({
            "date": s.date, "status": s.status or "off",
            "ticked_lunch": s.ticked_lunch, "ticked_dinner": s.ticked_dinner,
            "final_rate": dr["final_rate"],
            "expense": meta["expense"], "meal_count": meta["meal_count"],
            "day_cost": round(charge, 2)
        })

    manager_fees = 0.0
    for s in statuses:
        if s.status == "off" or s.is_guest or student.free_meal:
            continue
        mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
        manager_fees += billing_helper._meal_multiplier(s.status) * mgr_charge

    return {
        "student": {"id": student.id, "username": student.username, "name": student.name,
                    "room_number": student.room_number or "N/A", "hall_name": hall_name},
        "cycle": {"month": cycle.month, "status": cycle.status},
        "deposits": deposits_data,
        "total_deposits": round(total_deposits, 2),
        "daily_meals": daily_meals,
        "total_bill": round(total_bill, 2),
        "manager_fees": round(manager_fees, 2),
        "cycle_balance": round(total_deposits - total_bill, 2),
        "rates": rates,
        "email": student.email or ""
    }


@router.post("/students/{user_id}/email-report")
def public_email_report(user_id: int, payload: schemas.EmailReportRequest, db: Session = Depends(get_db)):
    if not payload.email or "@" not in payload.email or "." not in payload.email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if payload.user_id != user_id:
        raise HTTPException(status_code=400, detail="User mismatch.")

    data = _public_report_data(user_id, db)
    pdf_bytes = None
    try:
        from pdf_helper import generate_bill_pdf
        summary = {
            "total_deposits": data["total_deposits"],
            "current_bill": data["total_bill"],
            "manager_fees": data["manager_fees"],
            "cycle_balance": data["cycle_balance"],
        }
        pdf_bytes = generate_bill_pdf(
            data["student"], summary, data["cycle"], data["student"]["hall_name"],
            data["deposits"], data["daily_meals"], data["rates"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate PDF report: {str(e)}")

    # SMTP config from DB settings or env vars (same source as manager email-bill)
    def get_cfg(key, default=""):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        return row.value if row else __import__("os").environ.get(key.upper(), default)
    smtp_host = get_cfg("smtp_host", "")
    smtp_port = int(get_cfg("smtp_port", "587"))
    smtp_user = get_cfg("smtp_user", "")
    smtp_pass = get_cfg("smtp_pass", "")
    use_smtp = bool(smtp_host and smtp_user and smtp_pass)

    student = data["student"]
    subject = f"eDining Report - {student['name']} ({data['cycle']['month']})"
    body = (f"Dear {student['name']},\n\nHere is your dining hall statement report "
            f"for cycle {data['cycle']['month']}.\n\n"
            f"Hall: {student['hall_name']}\nRoom: {student['room_number']}\n"
            f"Total Deposits: BDT {data['total_deposits']:.2f}\n"
            f"Total Charges: BDT {data['total_bill']:.2f}\n"
            f"Balance: BDT {data['cycle_balance']:.2f}\n\n"
            f"The detailed statement is attached as a PDF.\n\n"
            f"Regards,\nMymensingh EC Dining")

    if use_smtp:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from email.mime.application import MIMEApplication
            from email.header import Header
            msg = MIMEMultipart()
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = "%s <%s>" % (Header("Mymensingh EC Dining", "utf-8").encode(), smtp_user)
            msg["To"] = payload.email
            msg.attach(MIMEText(body.strip(), "plain", "utf-8"))
            attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
            attachment.add_header("Content-Disposition", "attachment",
                                  filename="statement_%s_%s.pdf" % (student["username"], data["cycle"]["month"]))
            msg.attach(attachment)
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                fails = server.sendmail(smtp_user, [payload.email], msg.as_string())
                if fails:
                    raise Exception("Sendmail failures: %s" % str(fails))
            return {"status": "success", "message": f"Report sent to {payload.email}."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Email sending failed: {str(e)}")
    else:
        print(f"[EMAIL SIM] To: {payload.email} | Subject: {subject}")
        return {"status": "simulated", "message": f"SMTP not configured. Report for {student['name']} was prepared (simulated).",
                "recipient": payload.email}
