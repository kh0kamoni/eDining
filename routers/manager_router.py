import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
import auth
from datetime import datetime, date, timedelta
import billing_helper

router = APIRouter(prefix="/manager", tags=["Manager Panel"])

@router.post("/cycle/start", response_model=schemas.MealCycleResponse)
def start_cycle(payload: schemas.MealCycleCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    if not current_user.hall_id:
        raise HTTPException(status_code=400, detail="Manager is not associated with any Hall.")
        
    import re
    if not re.match(r"^\d{2}:\d{2}$", payload.cutoff_time):
        raise HTTPException(status_code=400, detail="Cutoff time must be in HH:MM 24h format (e.g., 20:00).")
        
    import calendar
    # Resolve start and end dates
    start_date_val = payload.start_date
    if not start_date_val:
        start_date_val = f"{payload.month}-01"
        
    end_date_val = payload.end_date
    if not end_date_val:
        year, month_num = map(int, payload.month.split("-"))
        last_day = calendar.monthrange(year, month_num)[1]
        end_date_val = f"{payload.month}-{last_day:02d}"
        
    # Check date overlap with existing cycles for this hall (any status, incl. closed)
    # so no two consecutive cycles ever overlap. A closed previous cycle does not block
    # creating a NEW cycle that starts after its end date.
    prev_cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.end_date >= start_date_val
    ).order_by(models.MealCycle.end_date.desc()).first()
    if prev_cycle:
        raise HTTPException(status_code=400, detail=f"A cycle already exists from {prev_cycle.start_date} to {prev_cycle.end_date}. New cycle's start date ({start_date_val}) must be after the previous cycle ends.")
        
    new_cycle = models.MealCycle(
        hall_id=current_user.hall_id,
        month=payload.month,
        status="poll",
        cutoff_time=payload.cutoff_time,
        lunch_percentage=payload.lunch_percentage,
        dinner_percentage=payload.dinner_percentage,
        start_date=start_date_val,
        end_date=end_date_val
    )
    db.add(new_cycle)
    db.commit()
    db.refresh(new_cycle)
    
    # Auto-populate daily meal status records for all students in this hall
    students = db.query(models.User).filter(
        models.User.hall_id == current_user.hall_id,
        models.User.role == "student"
    ).all()
    
    import billing_helper
    dates = billing_helper.get_cycle_dates(new_cycle, restrict_to_today=False)
    
    for student in students:
        status_str = student.status or "both"
        t_lunch = status_str in ["both", "lunch_only"]
        t_dinner = status_str in ["both", "dinner_only"]
        
        for d_str in dates:
            db.add(models.StudentMealStatus(
                user_id=student.id,
                meal_cycle_id=new_cycle.id,
                date=d_str,
                status=status_str,
                ticked_lunch=t_lunch,
                ticked_dinner=t_dinner,
                kept_lunch_for_dinner=False,
                is_guest=False,
                is_deducted=False,
                amount_deducted=0.0
            ))
            
    db.commit()
    return new_cycle

@router.post("/cycle/activate")
def activate_cycle(month: str, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.month == month,
        models.MealCycle.status == "poll"
    ).first()
    
    if not cycle:
        raise HTTPException(status_code=404, detail="Meal cycle not found.")
        
    cycle.status = "active"
    db.commit()
    return {"message": "Meal cycle activated successfully", "status": cycle.status}

def _get_effective_cycle_status(cycle: models.MealCycle, db: Session) -> str:
    """Get effective cycle status, auto-closing if past end date."""
    from datetime import datetime
    if cycle.end_date:
        end_dt = datetime.strptime(cycle.end_date, "%Y-%m-%d").date()
        today = datetime.now().date()
        if today > end_dt and cycle.status != "closed":
            cycle.status = "closed"
            billing_helper.prune_cycle_after_end_date(cycle, db, cycle.end_date)
            db.commit()
    return cycle.status

@router.get("/cycle/active")
def get_active_cycle(current_user: models.User = Depends(auth.require_roles(["student", "manager", "assistant_manager"])), db: Session = Depends(get_db)):
    # Find latest cycle (any status, incl. closed) so managers/students can
    # still view a closed cycle and managers can reopen/create the next one.
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if cycle:
        _get_effective_cycle_status(cycle, db)
        hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first() if current_user.hall_id else None
    result = cycle
    if cycle:
        result = {
            "id": cycle.id,
            "hall_id": cycle.hall_id,
            "month": cycle.month,
            "status": cycle.status,
            "cutoff_time": cycle.cutoff_time,
            "lunch_percentage": cycle.lunch_percentage,
            "dinner_percentage": cycle.dinner_percentage,
            "lunch_only_rate_percentage": cycle.lunch_only_rate_percentage,
            "dinner_only_rate_percentage": cycle.dinner_only_rate_percentage,
            "start_date": cycle.start_date,
            "end_date": cycle.end_date,
            "guest_meal_rate": hall.guest_meal_rate if hall else 120.0,
            "manager_charge_per_day": hall.manager_charge_per_day if hall else 5.0,
            "guest_charge_per_day": hall.guest_charge_per_day if hall else 5.0
        }
    return result

@router.get("/deposits")
def list_deposits(date: str = "", current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    query = db.query(models.Deposit).join(
        models.User, models.User.id == models.Deposit.user_id
    ).filter(
        models.Deposit.meal_cycle_id.in_(
            db.query(models.MealCycle.id).filter(
                models.MealCycle.hall_id == current_user.hall_id
            ).subquery()
        )
    )
    if date:
        query = query.filter(models.Deposit.date == date)
    deposits = query.order_by(models.Deposit.date.desc()).all()
    result = []
    for d in deposits:
        u = db.query(models.User).filter(models.User.id == d.user_id).first()
        result.append({
            "id": d.id,
            "user_id": d.user_id,
            "username": u.username if u else "deleted",
            "name": u.name if u else "Deleted User",
            "date": d.date,
            "amount": d.amount,
            "description": d.description or ""
        })
    return result

@router.post("/deposit", response_model=schemas.DepositResponse)
def add_deposit(payload: schemas.DepositCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    # Find user by username
    student = db.query(models.User).filter(models.User.username == payload.username).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
        
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than zero.")
        
    # Get cycle for manager's hall (any status - closed cycles allowed)
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        raise HTTPException(status_code=400, detail="No meal cycle found for your hall.")
        
    # Create Deposit
    deposit = models.Deposit(
        user_id=student.id,
        meal_cycle_id=cycle.id,
        amount=payload.amount,
        date=payload.date,
        description=payload.description
    )
    # Update balance
    student.balance += payload.amount
    db.add(deposit)
    db.commit()
    db.refresh(deposit)
    
    # Send deposit confirmation email (async — fire and forget)
    trx_ref = payload.description or f"Manual-{deposit.id}"
    import threading
    threading.Thread(target=_send_deposit_email, args=(student, payload.amount, trx_ref, db, "manual"), daemon=True).start()
    
    return deposit


@router.put("/deposits/{deposit_id}")
def update_deposit(deposit_id: int, payload: schemas.DepositCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    dep = db.query(models.Deposit).filter(models.Deposit.id == deposit_id).first()
    if not dep:
        raise HTTPException(status_code=404, detail="Deposit not found.")
    student = db.query(models.User).filter(models.User.id == dep.user_id).first()
    if student:
        student.balance -= dep.amount  # reverse old
        student.balance += payload.amount  # apply new
    dep.amount = payload.amount
    dep.date = payload.date
    dep.description = payload.description
    db.commit()
    return {"message": "Deposit updated and balance adjusted."}


@router.delete("/deposits/{deposit_id}")
def delete_deposit(deposit_id: int, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    dep = db.query(models.Deposit).filter(models.Deposit.id == deposit_id).first()
    if not dep:
        raise HTTPException(status_code=404, detail="Deposit not found.")
    student = db.query(models.User).filter(models.User.id == dep.user_id).first()
    if student:
        student.balance -= dep.amount
    db.delete(dep)
    db.commit()
    return {"message": "Deposit deleted and balance reversed."}


@router.delete("/bkash/transactions/{trx_id}")
def delete_bkash_transaction(trx_id: str, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    trx = db.query(models.BkashReceivedSms).filter(models.BkashReceivedSms.trx_id == trx_id.upper()).first()
    if not trx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if trx.status == "approved":
        student = db.query(models.User).filter(models.User.id == trx.claimed_by_user_id).first()
        if student:
            student.balance -= (trx.approved_amount or trx.amount or 0)
        # Also delete the linked deposit
        db.query(models.Deposit).filter(
            models.Deposit.user_id == trx.claimed_by_user_id,
            models.Deposit.description.like("%" + trx.trx_id + "%")
        ).delete()
    db.delete(trx)
    db.commit()
    return {"message": "Transaction deleted and balance adjusted."}


@router.post("/expense", response_model=schemas.ExpenseResponse)
def add_expense(payload: schemas.ExpenseCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        raise HTTPException(status_code=400, detail="No meal cycle found to add expenses.")
        
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Expense amount must be greater than zero.")
        
    expense = models.Expense(
        meal_cycle_id=cycle.id,
        date=payload.date,
        description=payload.description,
        amount=payload.amount,
        quantity=payload.quantity,
        unit=payload.unit,
        meal_type=payload.meal_type or "both",
        paid=payload.paid
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    billing_helper.adjust_deductions_for_date(cycle, expense.date, db)
    return expense

@router.post("/expenses/batch")
def add_expenses_batch(payload: schemas.ExpenseBatchCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        raise HTTPException(status_code=400, detail="No meal cycle found to add expenses.")
        
    if not payload.items:
        raise HTTPException(status_code=400, detail="No expense items provided.")
        
    added = []
    for item in payload.items:
        if item.amount <= 0:
            raise HTTPException(status_code=400, detail=f"Expense amount must be greater than zero (item: {item.description}).")
        expense = models.Expense(
            meal_cycle_id=cycle.id,
            date=item.date,
            description=item.description,
            amount=item.amount,
            quantity=item.quantity,
            unit=item.unit,
            meal_type=item.meal_type or "both",
            paid=item.paid
        )
        db.add(expense)
        added.append(expense)
        
    db.commit()
    # Adjust deductions for all affected dates in this batch
    for item in payload.items:
        billing_helper.adjust_deductions_for_date(cycle, item.date, db)
    return {"message": "%d expense item(s) logged successfully." % len(added), "count": len(added)}


@router.post("/students/bulk-toggle-status")
def bulk_toggle_student_status(payload: dict, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    user_ids = payload.get("user_ids", [])
    status = payload.get("status", "off")
    date_str = payload.get("date", date.today().strftime("%Y-%m-%d"))
    if not user_ids:
        raise HTTPException(status_code=400, detail="No user IDs provided.")
    
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.start_date <= date_str,
        models.MealCycle.end_date >= date_str
    ).first()
    if not cycle:
        month_str = date_str[:7]
        cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.month == month_str
        ).first()
    if not cycle:
        raise HTTPException(status_code=400, detail="No cycle found.")
    
    t_lunch = status in ["both", "lunch_only", "double", "triple"]
    t_dinner = status in ["both", "dinner_only", "double", "triple"]
    updated = 0
    
    # Determine if we should carry forward (only for today/future dates)
    from datetime import datetime as dt, date as d
    try:
        start_dt = dt.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        start_dt = d.today()
    today = d.today()
    carry_forward = start_dt >= today  # Only carry forward from today/future
    
    for uid in user_ids:
        u = db.query(models.User).filter(models.User.id == uid).first()
        if not u:
            continue
        is_other_hall = u.hall_id != current_user.hall_id
        
        # Determine end date for carry-forward
        end_dt = billing_helper.get_cycle_end_date(cycle) if carry_forward else start_dt
        
        current_dt = start_dt
        while current_dt <= end_dt:
            d_str = current_dt.strftime("%Y-%m-%d")
            status_rec = db.query(models.StudentMealStatus).filter(
                models.StudentMealStatus.user_id == uid,
                models.StudentMealStatus.meal_cycle_id == cycle.id,
                models.StudentMealStatus.date == d_str
            ).first()
            if not status_rec:
                status_rec = models.StudentMealStatus(
                    user_id=uid, meal_cycle_id=cycle.id, date=d_str,
                    status=status, ticked_lunch=t_lunch, ticked_dinner=t_dinner,
                    is_guest=is_other_hall
                )
                db.add(status_rec)
            else:
                status_rec.status = status
                status_rec.ticked_lunch = t_lunch
                status_rec.ticked_dinner = t_dinner
            if not carry_forward:
                break
            current_dt += timedelta(days=1)
        updated += 1
    db.commit()
    return {"message": "%d students updated." % updated, "count": updated}


@router.post("/meal-tick/bulk")
def bulk_meal_tick(payload: dict, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    status_ids = payload.get("status_ids", [])
    meal_type = payload.get("meal_type", "lunch")
    ticked = payload.get("ticked", False)
    if not status_ids:
        raise HTTPException(status_code=400, detail="No status IDs provided.")
    
    updated = 0
    for sid in status_ids:
        rec = db.query(models.StudentMealStatus).filter(models.StudentMealStatus.id == sid).first()
        if not rec:
            continue
        if meal_type == "lunch":
            rec.ticked_lunch = ticked
        elif meal_type == "dinner":
            rec.ticked_dinner = ticked
        updated += 1
    db.commit()
    return {"message": "%d %s %s." % (updated, meal_type, "ticked" if ticked else "unticked"), "count": updated}


@router.get("/expenses")
def list_expenses(date: str = None, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        return []
    q = db.query(models.Expense).filter(models.Expense.meal_cycle_id == cycle.id)
    if date:
        q = q.filter(models.Expense.date == date)
    return q.order_by(models.Expense.date.desc()).all()

@router.put("/expenses/{expense_id}")
def update_expense(expense_id: int, payload: schemas.ExpenseCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    expense = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")
    old_date = expense.date
    expense.date = payload.date
    expense.description = payload.description
    expense.amount = payload.amount
    if payload.quantity is not None:
        expense.quantity = payload.quantity
    if payload.unit is not None:
        expense.unit = payload.unit
    expense.meal_type = payload.meal_type or "both"
    expense.paid = payload.paid
    db.commit()
    # Adjust deductions for both old and new date
    cycle = db.query(models.MealCycle).filter(models.MealCycle.id == expense.meal_cycle_id).first()
    if cycle:
        billing_helper.adjust_deductions_for_date(cycle, old_date, db)
        if old_date != payload.date:
            billing_helper.adjust_deductions_for_date(cycle, payload.date, db)
    return {"message": "Expense updated successfully."}

@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    expense = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")
    old_date = expense.date
    cycle_id = expense.meal_cycle_id
    db.delete(expense)
    db.commit()
    cycle = db.query(models.MealCycle).filter(models.MealCycle.id == cycle_id).first()
    if cycle:
        billing_helper.adjust_deductions_for_date(cycle, old_date, db)
    return {"message": "Expense deleted successfully."}

@router.get("/daily-ops-log")
def get_daily_ops_log(date: str, end_date: str = None, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        raise HTTPException(status_code=400, detail="No meal cycle found.")
        
    expenses_q = db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id
    )
    deposits_q = db.query(models.Deposit, models.User).join(
        models.User, models.User.id == models.Deposit.user_id
    ).filter(
        models.Deposit.meal_cycle_id == cycle.id
    )
    meals_q = db.query(models.StudentMealStatus, models.User).join(
        models.User, models.User.id == models.StudentMealStatus.user_id
    ).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.status != "off"
    )
    
    if end_date:
        expenses_q = expenses_q.filter(models.Expense.date >= date, models.Expense.date <= end_date)
        deposits_q = deposits_q.filter(models.Deposit.date >= date, models.Deposit.date <= end_date)
        meals_q = meals_q.filter(models.StudentMealStatus.date >= date, models.StudentMealStatus.date <= end_date)
    else:
        expenses_q = expenses_q.filter(models.Expense.date == date)
        deposits_q = deposits_q.filter(models.Deposit.date == date)
        meals_q = meals_q.filter(models.StudentMealStatus.date == date)
        
    expenses = expenses_q.all()
    deposits = deposits_q.all()
    active_meals = meals_q.all()
    
    deposits_data = [
        {
            "id": d.id,
            "student_name": u.name,
            "student_username": u.username,
            "amount": d.amount,
            "description": d.description,
            "date": d.date
        }
        for d, u in deposits
    ]
    
    active_meals_data = [
        {
            "student_name": u.name,
            "student_username": u.username,
            "room_number": u.room_number,
            "status": s.status,
            "ticked_lunch": s.ticked_lunch,
            "ticked_dinner": s.ticked_dinner,
            "is_guest": s.is_guest,
            "date": s.date
        }
        for s, u in active_meals
    ]
    
    return {
        "start_date": date,
        "end_date": end_date or date,
        "expenses": [
            {
                "id": e.id,
                "description": e.description,
                "amount": e.amount,
                "quantity": e.quantity,
                "unit": e.unit,
                "meal_type": e.meal_type,
                "paid": e.paid,
                "date": e.date
            }
            for e in expenses
        ],
        "deposits": deposits_data,
        "active_meals": active_meals_data
    }

@router.get("/students")
def list_students(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    students = db.query(models.User).filter(models.User.hall_id == current_user.hall_id).all()
    
    # Running cycle for the manager's hall — any status, incl. closed, so managers
    # keep full control of the cycle they are associated with even after auto-close.
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        # No cycle yet — list students with zero cycle balances
        return [{
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "room_number": u.room_number,
            "phone": u.phone,
            "role": u.role,
            "hall_id": u.hall_id,
            "free_meal": u.free_meal,
            "balance": 0.0,
            "cycle_balance": 0.0,
            "egg_alternative": u.egg_alternative if hasattr(u, 'egg_alternative') else False,
            "prefer_beef": u.prefer_beef if hasattr(u, 'prefer_beef') else False,
            "prefer_mutton": u.prefer_mutton if hasattr(u, 'prefer_mutton') else False,
            "meal_preference": u.meal_preference or "normal",
            "fish_egg_pref": u.fish_egg_pref or "normal",
            "meat_pref": u.meat_pref or "normal"
        } for u in students]
    
    # Pre-fetch all deposits grouped by user
    all_deposits = db.query(models.Deposit).filter(
        models.Deposit.meal_cycle_id == cycle.id
    ).all()
    deposits_by_user = {}
    for d in all_deposits:
        deposits_by_user[d.user_id] = deposits_by_user.get(d.user_id, 0.0) + d.amount
    
    today_str = date.today().strftime("%Y-%m-%d")
    all_statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date <= today_str,
        models.StudentMealStatus.status != "off"
    ).all()
    
    hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
    guest_rate = hall.guest_meal_rate if hall else 120.0
    mgr_charge = hall.manager_charge_per_day if hall else 5.0
    # Pre-fetch all users into a dict (avoids per-status user query)
    all_users = {u.id: u for u in students}
    
    bill_by_user = {}
    fees_by_user = {}
    for s in all_statuses:
        uid = s.user_id
        if uid not in bill_by_user:
            bill_by_user[uid] = 0.0
            fees_by_user[uid] = 0.0
        
        if s.is_guest:
            g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
            g_mult = billing_helper._meal_multiplier(s.status)
            _, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
            if s.status in ("both", "double", "triple"):
                bill_by_user[uid] += g_mult * g_dr["final_rate"] + g_mult * guest_charge
            elif s.status == "lunch_only":
                l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                bill_by_user[uid] += g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
            elif s.status == "dinner_only":
                d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                bill_by_user[uid] += g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
        else:
            u = all_users.get(uid)
            if u and u.free_meal:
                continue
            mgr_charge, _ = billing_helper.get_daily_charges(cycle, s.date, db)
            fees_by_user[uid] += billing_helper._meal_multiplier(s.status) * mgr_charge
            dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
            if s.status == "both":
                bill_by_user[uid] += dr["final_rate"]
            elif s.status == "lunch_only":
                bill_by_user[uid] += billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"]
            elif s.status == "dinner_only":
                bill_by_user[uid] += billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"]
            elif s.status == "double":
                bill_by_user[uid] += 2 * dr["final_rate"]
            elif s.status == "triple":
                bill_by_user[uid] += 3 * dr["final_rate"]
    
    result = []
    for u in students:
        cb = round(deposits_by_user.get(u.id, 0.0) - bill_by_user.get(u.id, 0.0) - fees_by_user.get(u.id, 0.0), 2)
        result.append({
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "room_number": u.room_number,
            "phone": u.phone,
            "role": u.role,
            "hall_id": u.hall_id,
            "free_meal": u.free_meal,
            "balance": cb,
            "cycle_balance": cb,
            "egg_alternative": u.egg_alternative if hasattr(u, 'egg_alternative') else False,
            "prefer_beef": u.prefer_beef if hasattr(u, 'prefer_beef') else False,
            "prefer_mutton": u.prefer_mutton if hasattr(u, 'prefer_mutton') else False,
            "meal_preference": u.meal_preference or "normal",
            "fish_egg_pref": u.fish_egg_pref or "normal",
            "meat_pref": u.meat_pref or "normal"
        })
    return result

@router.get("/students/search")
def search_students(q: str = "", limit: int = 30, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    # Fast lightweight search across ALL users (all halls, incl. guests) by name/username/room/phone.
    # Used by deposit entry autocomplete — avoids the heavy balance computation in /manager/students.
    term = (q or "").strip()
    query = db.query(models.User)
    if term:
        like = f"%{term}%"
        query = query.filter(
            (models.User.name.ilike(like)) |
            (models.User.username.ilike(like)) |
            (models.User.room_number.ilike(like)) |
            (models.User.phone.ilike(like))
        )
    results = query.order_by(models.User.room_number).limit(limit).all()
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    return [{
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "room_number": u.room_number or "N/A",
        "phone": u.phone or "",
        "role": u.role,
        "hall_id": u.hall_id,
        "is_guest": hall is not None and u.hall_id != hall.id,
        "free_meal": u.free_meal
    } for u in results]

@router.post("/students/toggle-meal")
def manager_toggle_meal(payload: schemas.MealStatusAdminOverride, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    # Bypasses cutoff check
    target_student = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not target_student:
        raise HTTPException(status_code=404, detail="Student not found.")
        
    target_month = payload.date[:7]
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.month == target_month
    ).first()
    
    if not cycle:
        # Check by date range
        cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.start_date <= payload.date,
            models.MealCycle.end_date >= payload.date
        ).first()
        
    if not cycle:
        raise HTTPException(status_code=400, detail="No cycle found for this date.")
        
    from datetime import datetime, date, timedelta
    import calendar
    
    try:
        start_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")
        
    end_date = billing_helper.get_cycle_end_date(cycle)
    
    # Only carry forward for today/future dates; past dates affect only that specific day
    no_carry = (start_date < date.today())
    
    current = start_date
    while current <= end_date:
        if no_carry and current != start_date:
            break
            
        d_str = current.strftime("%Y-%m-%d")
        status_rec = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == target_student.id,
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.date == d_str
        ).first()
        
        t_lunch = payload.status in ["both", "lunch_only", "double", "triple"]
        t_dinner = payload.status in ["both", "dinner_only", "double", "triple"]
        
        # Use explicit guest flag from payload if provided, else auto-detect
        if payload.is_guest is not None:
            is_guest_flag = payload.is_guest
            guest_hall = (payload.guest_from_hall_id or target_student.hall_id) if payload.is_guest else None
        else:
            is_guest_flag = (target_student.hall_id != current_user.hall_id)
            guest_hall = target_student.hall_id if is_guest_flag else None
        
        if not status_rec:
            status_rec = models.StudentMealStatus(
                user_id=target_student.id,
                meal_cycle_id=cycle.id,
                date=d_str,
                status=payload.status,
                ticked_lunch=t_lunch,
                ticked_dinner=t_dinner,
                is_guest=is_guest_flag,
                guest_from_hall_id=guest_hall
            )
            db.add(status_rec)
        else:
            status_rec.status = payload.status
            status_rec.ticked_lunch = t_lunch
            status_rec.ticked_dinner = t_dinner
            if payload.is_guest is not None:
                status_rec.is_guest = payload.is_guest
                if payload.is_guest:
                    status_rec.guest_from_hall_id = payload.guest_from_hall_id or target_student.hall_id
                else:
                    status_rec.guest_from_hall_id = None
            
        # Resolve conflicts (deactivate competing active registrations in other halls)
        if payload.status != "off":
            if target_student.hall_id == current_user.hall_id:
                # Home student override: turn off guest status in other halls
                db.query(models.StudentMealStatus).filter(
                    models.StudentMealStatus.user_id == target_student.id,
                    models.StudentMealStatus.is_guest == True,
                    models.StudentMealStatus.date == d_str
                ).update({models.StudentMealStatus.status: "off"}, synchronize_session=False)
            else:
                # Guest student override: turn off home hall active status
                home_cycle = db.query(models.MealCycle).filter(
                    models.MealCycle.hall_id == target_student.hall_id,
                    models.MealCycle.month == target_month
                ).first()
                if home_cycle:
                    db.query(models.StudentMealStatus).filter(
                        models.StudentMealStatus.user_id == target_student.id,
                        models.StudentMealStatus.meal_cycle_id == home_cycle.id,
                        models.StudentMealStatus.date == d_str
                    ).update({models.StudentMealStatus.status: "off"}, synchronize_session=False)
                    
        current += timedelta(days=1)
        
    db.commit()
    return {"message": "Override complete and carried forward", "user": target_student.username, "date": payload.date, "status": payload.status}

@router.put("/students/{user_id}/preferences")
def update_student_preferences(user_id: int, payload: schemas.UserProfileUpdate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    student = db.query(models.User).filter(models.User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    if student.hall_id != current_user.hall_id:
        # Allow preferences for guests from other halls who participate in this hall's cycles
        is_guest_here = db.query(models.StudentMealStatus.id).join(
            models.MealCycle,
            models.StudentMealStatus.meal_cycle_id == models.MealCycle.id
        ).filter(
            models.StudentMealStatus.user_id == user_id,
            models.MealCycle.hall_id == current_user.hall_id,
            models.StudentMealStatus.is_guest == True
        ).first()
        if not is_guest_here:
            raise HTTPException(status_code=404, detail="Student not found in your hall.")
    if payload.egg_alternative is not None:
        student.egg_alternative = payload.egg_alternative
    if payload.prefer_beef is not None:
        student.prefer_beef = payload.prefer_beef
    if payload.prefer_mutton is not None:
        student.prefer_mutton = payload.prefer_mutton
    if payload.meal_preference is not None:
        student.meal_preference = payload.meal_preference
    if payload.fish_egg_pref is not None:
        student.fish_egg_pref = payload.fish_egg_pref
    if payload.meat_pref is not None:
        student.meat_pref = payload.meat_pref
    db.commit()
    return {"message": f"Preferences updated for {student.name}"}

@router.post("/guests/deactivate-all")
def deactivate_all_guests(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        raise HTTPException(status_code=400, detail="No cycle found to deactivate guests from.")
        
    today_str = date.today().strftime("%Y-%m-%d")
    
    # Deactivate all guest meals for today and future in this cycle
    guest_statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.is_guest == True,
        models.StudentMealStatus.date >= today_str
    ).all()
    
    for gs in guest_statuses:
        gs.status = "off"
        
    db.commit()
    return {"message": f"Successfully turned off {len(guest_statuses)} guest meals from today onwards."}


@router.get("/daily-menu")
def get_daily_menu(date_str: str, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    menu = db.query(models.DailyMenu).filter(
        models.DailyMenu.date == date_str,
        models.DailyMenu.hall_id == current_user.hall_id
    ).first()
    if not menu:
        return {"date": date_str, "fish_served": False, "beef_served": False, "pangas_served": False, "other_fish_served": False, "mutton_served": False}
    return {"date": menu.date, "fish_served": menu.fish_served, "beef_served": menu.beef_served, "pangas_served": menu.pangas_served, "other_fish_served": menu.other_fish_served, "mutton_served": menu.mutton_served}


@router.post("/daily-menu")
def set_daily_menu(date_str: str, fish_served: bool = False, beef_served: bool = False, pangas_served: bool = False, other_fish_served: bool = False, mutton_served: bool = False, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    menu = db.query(models.DailyMenu).filter(
        models.DailyMenu.date == date_str,
        models.DailyMenu.hall_id == current_user.hall_id
    ).first()
    if not menu:
        menu = models.DailyMenu(date=date_str, hall_id=current_user.hall_id)
        db.add(menu)
    menu.fish_served = fish_served
    menu.beef_served = beef_served
    menu.pangas_served = pangas_served
    menu.other_fish_served = other_fish_served
    menu.mutton_served = mutton_served
    db.commit()
    return {"message": "Menu updated.", "fish_served": fish_served, "beef_served": beef_served, "pangas_served": pangas_served, "other_fish_served": other_fish_served, "mutton_served": mutton_served}


@router.get("/print-sheet")
def get_print_sheet(date_str: str = None, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    billing_helper.deduct_passed_meals(db)
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")
        
    month_str = date_str[:7]
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.month == month_str
    ).first()
    
    if not cycle:
        return []
        
    # Fetch all active meal statuses for this cycle and date
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date == date_str,
        models.StudentMealStatus.status != "off"
    ).all()
    
    results = []
    for s in statuses:
        u = db.query(models.User).filter(models.User.id == s.user_id).first()
        if u:
            results.append({
                "status_id": s.id,
                "user_id": u.id,
                "username": u.username,
                "name": u.name,
                "room_number": u.room_number or "N/A",
                "role": u.role,
                "status": s.status,
                "ticked_lunch": s.ticked_lunch,
                "ticked_dinner": s.ticked_dinner,
                "kept_lunch_for_dinner": s.kept_lunch_for_dinner,
                "is_guest": s.is_guest,
            "meal_preference": u.meal_preference or "normal",
            "fish_egg_pref": u.fish_egg_pref or "normal",
            "meat_pref": u.meat_pref or "normal"
        })
            
    # Sort room-wise: floor-wise numerical sorting if possible
    def get_room_sort_key(item):
        room = item["room_number"]
        # Extract digits
        digits = "".join([c for c in room if c.isdigit()])
        if digits:
            return (int(digits), room)
        return (99999, room)
        
    results.sort(key=get_room_sort_key)
    return results

@router.get("/student-meals")
def get_student_meals(date_str: str = None, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    billing_helper.deduct_passed_meals(db)
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")
        
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.start_date <= date_str,
        models.MealCycle.end_date >= date_str
    ).first()
    
    if not cycle:
        month_str = date_str[:7]
        cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.month == month_str
        ).first()
    
    if not cycle:
        return []
    
    # Don't auto-seed statuses for dates before the cycle start_date
    if cycle.start_date and date_str < cycle.start_date:
        return []
    
    # Get all home students in this hall
    home_users = db.query(models.User).filter(
        models.User.hall_id == current_user.hall_id
    ).all()
    
    # Get all meal status records in this cycle for this date
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date == date_str
    ).all()
    
    status_map = {s.user_id: s for s in statuses}
    
    today_str = date.today().strftime("%Y-%m-%d")
    # Auto-seed missing student statuses for this date
    # Uses last-known status from prior dates so status carries forward naturally
    created_any = False
    for u in home_users:
        if u.id not in status_map:
            if date_str < today_str:
                status_str = "off"
                t_lunch = False
                t_dinner = False
            else:
                lks = billing_helper._last_known_status(u.id, cycle.id, date_str, db)
                status_str = lks["status"]
                t_lunch = lks["ticked_lunch"]
                t_dinner = lks["ticked_dinner"]
            
            new_status = models.StudentMealStatus(
                user_id=u.id,
                meal_cycle_id=cycle.id,
                date=date_str,
                status=status_str,
                ticked_lunch=t_lunch,
                ticked_dinner=t_dinner,
                kept_lunch_for_dinner=False,
                is_guest=False,
                is_deducted=False,
                amount_deducted=0.0
            )
            db.add(new_status)
            created_any = True
    
    # Also seed ALL users from OTHER halls as guests (status="off" initially)
    other_users = db.query(models.User).filter(
        models.User.hall_id != current_user.hall_id
    ).all()
    for u in other_users:
        if u.id not in status_map:
            new_status = models.StudentMealStatus(
                user_id=u.id,
                meal_cycle_id=cycle.id,
                date=date_str,
                status="off",
                ticked_lunch=False,
                ticked_dinner=False,
                kept_lunch_for_dinner=False,
                is_guest=True,
                is_deducted=False,
                amount_deducted=0.0
            )
            db.add(new_status)
            created_any = True
            
    if created_any:
        db.commit()
        # Refetch statuses
        statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.date == date_str
        ).all()
        status_map = {s.user_id: s for s in statuses}
        
    results = []
    
    # Add home students
    for u in home_users:
        s = status_map.get(u.id)
        is_guest_flag = s.is_guest if s else False
        results.append({
            "status_id": s.id if s else None,
            "user_id": u.id,
            "username": u.username,
            "name": u.name,
            "room_number": u.room_number or "N/A",
            "role": "Guest" if is_guest_flag else u.role,
            "status": s.status if s else "off",
            "ticked_lunch": s.ticked_lunch if s else False,
            "ticked_dinner": s.ticked_dinner if s else False,
            "kept_lunch_for_dinner": s.kept_lunch_for_dinner if s else False,
            "is_guest": is_guest_flag,
            "pref_egg": u.egg_alternative if hasattr(u, 'egg_alternative') else False,
            "pref_beef": u.prefer_beef if hasattr(u, 'prefer_beef') else False,
            "pref_mutton": u.prefer_mutton if hasattr(u, 'prefer_mutton') else False,
            "meal_preference": u.meal_preference or "normal",
            "fish_egg_pref": u.fish_egg_pref or "normal",
            "meat_pref": u.meat_pref or "normal"
        })
        
    # Add non-home-student users who had status logged in this cycle on this day
    # (managers, staff from same hall, and actual guests from other halls)
    home_user_ids = {u.id for u in home_users}
    for s in statuses:
        if s.user_id not in home_user_ids:
            u = db.query(models.User).filter(models.User.id == s.user_id).first()
            if u:
                # Use DB record's is_guest flag; fall back to hall-id comparison
                is_guest_flag = s.is_guest if s.is_guest is not None else (u.hall_id != cycle.hall_id)
                results.append({
                    "status_id": s.id,
                    "user_id": u.id,
                    "username": u.username,
                    "name": u.name,
                    "room_number": u.room_number or "N/A",
                    "role": "Guest" if is_guest_flag else u.role,
                    "status": s.status,
                    "ticked_lunch": s.ticked_lunch,
                    "ticked_dinner": s.ticked_dinner,
                    "kept_lunch_for_dinner": s.kept_lunch_for_dinner,
                    "is_guest": is_guest_flag,
                    "pref_egg": getattr(u, 'egg_alternative', False),
                    "pref_beef": getattr(u, 'prefer_beef', False),
                    "pref_mutton": getattr(u, 'prefer_mutton', False),
                    "meal_preference": getattr(u, 'meal_preference', "normal"),
                    "fish_egg_pref": getattr(u, 'fish_egg_pref', "normal"),
                    "meat_pref": getattr(u, 'meat_pref', "normal")
                })
                
    # Sort room-wise
    def get_room_sort_key(item):
        room = item["room_number"]
        digits = "".join([c for c in room if c.isdigit()])
        if digits:
            return (int(digits), room)
        return (99999, room)
        
    results.sort(key=get_room_sort_key)
    return results

@router.post("/meal-tick")
def tick_meal(status_id: int, meal_type: str, ticked: bool, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    status_rec = db.query(models.StudentMealStatus).filter(models.StudentMealStatus.id == status_id).first()
    if not status_rec:
        raise HTTPException(status_code=404, detail="Meal status record not found.")
        
    if meal_type == "lunch":
        status_rec.ticked_lunch = ticked
    elif meal_type == "dinner":
        status_rec.ticked_dinner = ticked
    else:
        raise HTTPException(status_code=400, detail="Invalid meal type. Use 'lunch' or 'dinner'.")
        
    db.commit()
    return {"message": "Ticked state updated successfully."}

@router.post("/keep-lunch-for-dinner")
def keep_lunch_for_dinner(status_id: int, kept: bool, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    status_rec = db.query(models.StudentMealStatus).filter(models.StudentMealStatus.id == status_id).first()
    if not status_rec:
        raise HTTPException(status_code=404, detail="Meal status record not found.")
        
    status_rec.kept_lunch_for_dinner = kept
    db.commit()
    return {"message": "Kept lunch for dinner state updated."}

@router.post("/settings")
def update_settings(manager_charge_per_day: float, cutoff_time: str, lunch_percentage: float, dinner_percentage: float, lunch_only_rate_percentage: float = 0.4, dinner_only_rate_percentage: float = 0.6, guest_charge_per_day: float = 5.0, full_rate_days: str = "4", cycle_end_date: str = "", current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    import re
    if not re.match(r"^\d{2}:\d{2}$", cutoff_time):
        raise HTTPException(status_code=400, detail="Cutoff time must be in HH:MM format (24h).")
    if manager_charge_per_day < 0:
        raise HTTPException(status_code=400, detail="Manager daily charge cannot be negative.")
    if lunch_percentage < 0 or lunch_percentage > 1:
        raise HTTPException(status_code=400, detail="Lunch percentage must be between 0 and 1.")
    if dinner_percentage < 0 or dinner_percentage > 1:
        raise HTTPException(status_code=400, detail="Dinner percentage must be between 0 and 1.")
    if lunch_only_rate_percentage < 0 or lunch_only_rate_percentage > 1:
        raise HTTPException(status_code=400, detail="Lunch-only rate percentage must be between 0 and 1.")
    if dinner_only_rate_percentage < 0 or dinner_only_rate_percentage > 1:
        raise HTTPException(status_code=400, detail="Dinner-only rate percentage must be between 0 and 1.")

    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    if not hall:
        raise HTTPException(status_code=404, detail="Hall not found.")
        
    hall.manager_charge_per_day = manager_charge_per_day
    hall.guest_charge_per_day = guest_charge_per_day
    
    # Update most recent cycle (any status including closed) so managers can
    # still adjust settings and set/extend the cycle end date after closing.
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc(), models.MealCycle.end_date.desc()).first()
    
    if cycle:
        cycle.cutoff_time = cutoff_time
        cycle.lunch_percentage = lunch_percentage
        cycle.dinner_percentage = dinner_percentage
        cycle.lunch_only_rate_percentage = lunch_only_rate_percentage
        cycle.dinner_only_rate_percentage = dinner_only_rate_percentage
        cycle.full_rate_days = full_rate_days
        if cycle_end_date:
            cycle.end_date = cycle_end_date
            billing_helper.prune_cycle_after_end_date(cycle, db, cycle_end_date)
        
    db.commit()
    return {"message": "Settings updated successfully."}

@router.get("/smtp-config")
def get_smtp_config(current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    def get_cfg(key, default=""):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        return row.value if row else default
    return {
        "smtp_host": get_cfg("smtp_host", os.environ.get("SMTP_HOST", "")),
        "smtp_port": get_cfg("smtp_port", os.environ.get("SMTP_PORT", "587")),
        "smtp_user": get_cfg("smtp_user", os.environ.get("SMTP_USER", "")),
    }

@router.post("/smtp-config")
def update_smtp_config(smtp_host: str = "", smtp_port: str = "587", smtp_user: str = "", smtp_pass: str = "", current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    def set_cfg(key, val):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        if row:
            row.value = val
        else:
            db.add(models.AppConfig(key=key, value=val))
    set_cfg("smtp_host", smtp_host)
    set_cfg("smtp_port", smtp_port)
    set_cfg("smtp_user", smtp_user)
    if smtp_pass:
        set_cfg("smtp_pass", smtp_pass)
    db.commit()
    return {"message": "SMTP configuration saved."}

@router.get("/payment-numbers")
def get_payment_numbers(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    def get_cfg(key, default=""):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        return row.value if row else default
    return {"bkash_number": get_cfg("bkash_number", "01700-000000"), "nagad_number": get_cfg("nagad_number", "")}

@router.post("/payment-numbers")
def update_payment_numbers(bkash_number: str = "01700-000000", nagad_number: str = "", current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    def set_cfg(key, val):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        if row:
            row.value = val
        else:
            db.add(models.AppConfig(key=key, value=val))
    set_cfg("bkash_number", bkash_number)
    set_cfg("nagad_number", nagad_number)
    db.commit()
    return {"message": "Payment numbers updated."}

@router.get("/public-payment-numbers")
def get_public_payment_numbers(db: Session = Depends(get_db)):
    def get_cfg(key, default=""):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        return row.value if row else default
    return {"bkash_number": get_cfg("bkash_number", "01700-000000"), "nagad_number": get_cfg("nagad_number", "")}

@router.get("/app-config/{key}")
def get_app_config(key: str, current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
    return {"key": key, "value": row.value if row else ""}

@router.post("/app-config/{key}")
def set_app_config(key: str, value: str = "", current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.AppConfig(key=key, value=value))
    db.commit()
    return {"message": "Config saved."}

@router.get("/financial-summary")
def get_financial_summary(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    billing_helper.deduct_passed_meals(db)
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        return {
            "has_active_cycle": False,
            "total_expenses": 0.0,
            "guest_contributions": 0.0,
            "net_expenses": 0.0,
            "total_home_meal_units": 0.0,
            "meal_rate": 0.0,
            "meal_rate_excl_fri": 0.0,
            "lunch_rate": 0.0,
            "dinner_rate": 0.0,
            "total_manager_fees": 0.0
        }
        
    today_str = date.today().strftime("%Y-%m-%d")
    
    # Calculate expenses (only past/today)
    total_expenses = db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id,
        models.Expense.date <= today_str
    ).with_entities(models.Expense.amount).all()
    total_expenses = sum(e[0] for e in total_expenses) if total_expenses else 0.0
    
    # Calculate guest contributions and home student paying meal units (only past/today)
    meals = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date <= today_str,
        models.StudentMealStatus.status != "off"
    ).all()
    
    guest_contributions = 0.0
    total_home_meal_units = 0.0
    total_manager_fees = 0.0
    
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    guest_rate = hall.guest_meal_rate
    mgr_charge = hall.manager_charge_per_day 
    
    # Pre-fetch all users once (avoids per-meal User queries)
    all_users_map = {u.id: u for u in db.query(models.User).all()}
    
    for m in meals:
        weight = 1.0
        if m.status == "lunch_only":
            weight = cycle.lunch_percentage
        elif m.status == "dinner_only":
            weight = cycle.dinner_percentage
            
        elif m.status == "double":
            
            weight = 2.0
            
        elif m.status == "triple":
            weight = 3.0
        
        u = all_users_map.get(m.user_id)
        if not u:
            continue
            
        if m.is_guest:
            g_dr = billing_helper.get_daily_meal_rates(cycle, m.date, db)
            g_mult = billing_helper._meal_multiplier(m.status)
            _, guest_charge = billing_helper.get_daily_charges(cycle, m.date, db)
            if m.status in ("both", "double", "triple"):
                guest_contributions += g_mult * g_dr["final_rate"] + g_mult * guest_charge
            elif m.status == "lunch_only":
                l_g = billing_helper._lunch_only_pct(m.status, m.date, cycle)
                guest_contributions += g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
            elif m.status == "dinner_only":
                d_g = billing_helper._dinner_only_pct(m.status, m.date, cycle)
                guest_contributions += g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
        else:
            if u.free_meal:
                continue
            else:
                total_home_meal_units += weight
                mgr_charge, _ = billing_helper.get_daily_charges(cycle, m.date, db)
                total_manager_fees += billing_helper._meal_multiplier(m.status) * mgr_charge
                
    net_expenses = max(0.0, total_expenses - guest_contributions)
    
    cycle_total_deposits = db.query(models.Deposit).filter(
        models.Deposit.meal_cycle_id == cycle.id
    ).with_entities(models.Deposit.amount).all()
    cycle_total_deposits = sum(d[0] for d in cycle_total_deposits) if cycle_total_deposits else 0.0
    
    # Compute average daily final rate for dates up to today.
    # Days with zero expenses (dining was off) are excluded from the average.
    dates = billing_helper.get_cycle_dates(cycle, restrict_to_today=True)
    daily_final_rates = []
    daily_lunch_rates = []
    daily_dinner_rates = []
    daily_final_excl_fri = []
    for d in dates:
        dr = billing_helper.get_daily_meal_rates(cycle, d, db)
        if dr["final_rate"] <= 0:
            continue
        daily_final_rates.append(dr["final_rate"])
        daily_lunch_rates.append(dr["lunch_rate"])
        daily_dinner_rates.append(dr["dinner_rate"])
        # Check if day is NOT Friday (weekday() == 4 means Friday)
        from datetime import datetime
        dt = datetime.strptime(d, "%Y-%m-%d")
        if dt.weekday() != 4:
            daily_final_excl_fri.append(dr["final_rate"])
    avg_rate = sum(daily_final_rates) / len(daily_final_rates) if daily_final_rates else 0.0
    avg_lunch = sum(daily_lunch_rates) / len(daily_lunch_rates) if daily_lunch_rates else 0.0
    avg_dinner = sum(daily_dinner_rates) / len(daily_dinner_rates) if daily_dinner_rates else 0.0
    avg_rate_excl_fri = sum(daily_final_excl_fri) / len(daily_final_excl_fri) if daily_final_excl_fri else 0.0
    
    return {
        "has_active_cycle": True,
        "month": cycle.month,
        "total_expenses": total_expenses,
        "guest_contributions": guest_contributions,
        "net_expenses": net_expenses,
        "total_home_meal_units": total_home_meal_units,
        "meal_rate": avg_rate,
        "meal_rate_excl_fri": avg_rate_excl_fri,
        "lunch_rate": avg_lunch,
        "dinner_rate": avg_dinner,
        "total_manager_fees": total_manager_fees,
        "total_deposits": round(cycle_total_deposits, 2)
    }

@router.get("/profit")
def get_profit(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    billing_helper.deduct_passed_meals(db)
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        return {"has_active_cycle": False, "profit_from_home": 0.0, "profit_from_guests": 0.0, "total_profit": 0.0, "daily_breakdown": []}

    today_str = date.today().strftime("%Y-%m-%d")
    hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
    guest_rate = hall.guest_meal_rate
    mgr_charge = hall.manager_charge_per_day 
    # Pre-fetch all statuses and expenses for the cycle up to today
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date <= today_str,
        models.StudentMealStatus.status != "off"
    ).all()

    all_expenses = db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id,
        models.Expense.date <= today_str
    ).all()

    dates = billing_helper.get_cycle_dates(cycle, restrict_to_today=True)
    users_free = {u.id: u.free_meal for u in db.query(models.User).filter(models.User.hall_id == cycle.hall_id).all()}

    total_expenses_all = 0.0
    total_rate_revenue = 0.0
    total_home_profit = 0.0
    total_guest_profit = 0.0
    daily = []

    for d in dates:
        day_rates = billing_helper.get_daily_meal_rates(cycle, d, db)
        day_expenses = sum(e.amount for e in all_expenses if e.date == d)
        total_expenses_all += day_expenses

        day_home = 0.0
        day_guest = 0.0
        day_home_count = 0
        day_guest_count = 0
        day_rate_revenue = 0.0
        day_mgr_charge, day_guest_charge = billing_helper.get_daily_charges(cycle, d, db)

        for s in statuses:
            if s.date != d:
                continue

            if s.is_guest:
                day_guest += billing_helper._meal_multiplier(s.status) * day_guest_charge
                day_guest_count += billing_helper._meal_multiplier(s.status)
                day_rate_revenue += billing_helper._meal_multiplier(s.status) * day_rates["final_rate"]
            else:
                is_free = users_free.get(s.user_id, False)
                if not is_free:
                    day_home += billing_helper._meal_multiplier(s.status) * day_mgr_charge
                    day_home_count += 1
                    if s.status == "both":
                        day_rate_revenue += day_rates["final_rate"]
                    elif s.status == "lunch_only":
                        day_rate_revenue += billing_helper._lunch_only_pct(s.status, d, cycle) * day_rates["final_rate"]
                    elif s.status == "dinner_only":
                        day_rate_revenue += billing_helper._dinner_only_pct(s.status, d, cycle) * day_rates["final_rate"]
                    elif s.status == "double":
                        day_rate_revenue += 2 * day_rates["final_rate"]
                    elif s.status == "triple":
                        day_rate_revenue += 3 * day_rates["final_rate"]

        total_home_profit += day_home
        total_guest_profit += day_guest
        total_rate_revenue += day_rate_revenue

        daily.append({
            "date": d,
            "expenses": round(day_expenses, 2),
            "rate_revenue": round(day_rate_revenue, 2),
            "rate_surplus": round(day_rate_revenue - day_expenses, 2),
            "home_profit": round(day_home, 2),
            "home_active_count": day_home_count,
            "guest_profit": round(day_guest, 2),
            "guest_active_count": day_guest_count,
            "day_total": round((day_rate_revenue - day_expenses) + day_home + day_guest, 2)
        })

    return {
        "has_active_cycle": True,
        "month": cycle.month,
        "total_expenses": round(total_expenses_all, 2),
        "total_rate_revenue": round(total_rate_revenue, 2),
        "total_rate_surplus": round(total_rate_revenue - total_expenses_all, 2),
        "profit_from_home": round(total_home_profit, 2),
        "profit_from_guests": round(total_guest_profit, 2),
        "total_profit": round((total_rate_revenue - total_expenses_all) + total_home_profit + total_guest_profit, 2),
        "daily_breakdown": daily
    }

@router.get("/money-flow")
def get_money_flow(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    billing_helper.deduct_passed_meals(db)
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        return {"has_active_cycle": False}
    
    today_str = date.today().strftime("%Y-%m-%d")
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    mgr_charge = hall.manager_charge_per_day if hall else 5.0
    
    # Inventory payments total (from inventory_payments table)
    inv_payments = db.query(models.InventoryPayment).filter(
        models.InventoryPayment.meal_cycle_id == cycle.id
    ).all()
    inventory_payments = round(sum(p.amount for p in inv_payments), 2)
    
    # Total deposits (all users, current cycle) — split by cash vs non-cash
    deposits = db.query(models.Deposit).filter(
        models.Deposit.meal_cycle_id == cycle.id
    ).all()
    total_deposits = sum(d.amount for d in deposits)
    cash_deposits = sum(d.amount for d in deposits if d.description and "cash" in d.description.lower())
    non_cash_deposits = sum(d.amount for d in deposits if not d.description or "cash" not in d.description.lower())
    
    # Total expenses (past + today) — split by paid/unpaid
    expenses = db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id,
        models.Expense.date <= today_str
    ).all()
    total_expenses = sum(e.amount for e in expenses)
    paid_expenses = sum(e.amount for e in expenses if e.paid)
    unpaid_expenses = sum(e.amount for e in expenses if not e.paid)
    
    # bKash transactions (all in this hall's cycle — via manager's hall)
    bkash_txns = db.query(models.BkashReceivedSms).filter(
        models.BkashReceivedSms.status == "approved"
    ).all()
    total_bkash_approved = sum(t.amount for t in bkash_txns if t.amount)
    
    # Cashout from non-cash to cash
    cashouts = db.query(models.Cashout).filter(models.Cashout.meal_cycle_id == cycle.id).all()
    total_cashout = round(sum(c.amount for c in cashouts), 2)
    
    # Compute cycle-specific balance using same logic as cycle-summary (daily rates, not amount_deducted)
    all_statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).all()
    user_deposits_map = {}
    for d in db.query(models.Deposit).filter(models.Deposit.meal_cycle_id == cycle.id).all():
        user_deposits_map[d.user_id] = user_deposits_map.get(d.user_id, 0.0) + d.amount
    
    all_user_ids = set(user_deposits_map.keys()) | {s.user_id for s in all_statuses}
    all_users = db.query(models.User).filter(models.User.id.in_(all_user_ids)).all() if all_user_ids else []
    
    negative_users = []
    positive_users = []
    total_negative = 0.0
    total_positive = 0.0
    free_cycle_balance = 0.0
    rate_cache = {}
    
    # Group statuses by user once (avoids O(users x statuses) nested scan)
    statuses_by_user = {}
    for s in all_statuses:
        if s.status == "off" or s.date > today_str:
            continue
        statuses_by_user.setdefault(s.user_id, []).append(s)
    
    for u in all_users:
        cyc_dep = user_deposits_map.get(u.id, 0.0)
        bill = 0.0
        mgr_fees = 0.0
        user_type = "native" if u.hall_id == current_user.hall_id else "guest"
        
        for s in statuses_by_user.get(u.id, []):
            if s.date not in rate_cache:
                rate_cache[s.date] = billing_helper.get_daily_meal_rates(cycle, s.date, db)
            dr = rate_cache[s.date]
            
            mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
            if s.is_guest:
                g_mult = billing_helper._meal_multiplier(s.status)
                if s.status in ("both", "double", "triple"):
                    bill += g_mult * dr["final_rate"] + g_mult * guest_charge
                elif s.status == "lunch_only":
                    bill += g_mult * billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"] + g_mult * guest_charge
                elif s.status == "dinner_only":
                    bill += g_mult * billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"] + g_mult * guest_charge
            elif not u.free_meal:
                mgr_fees += billing_helper._meal_multiplier(s.status) * mgr_charge
                if s.status == "both":
                    bill += dr["final_rate"]
                elif s.status == "lunch_only":
                    bill += billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"]
                elif s.status == "dinner_only":
                    bill += billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"]
                elif s.status == "double":
                    bill += 2 * dr["final_rate"]
                elif s.status == "triple":
                    bill += 3 * dr["final_rate"]
        
        cyc_bal = round(cyc_dep - (bill + mgr_fees), 2)
        
        if u.free_meal:
            free_cycle_balance += cyc_bal
            continue
        
        if cyc_bal < 0:
            negative_users.append({"id": u.id, "name": u.name or u.username, "username": u.username, "balance": cyc_bal, "user_type": user_type})
            total_negative += cyc_bal
        elif cyc_bal > 0:
            positive_users.append({"id": u.id, "name": u.name or u.username, "username": u.username, "balance": cyc_bal, "user_type": user_type})
            total_positive += cyc_bal
    
    # Running meal rate
    rates = billing_helper.get_running_meal_rates(cycle, db)
    
    return {
        "has_active_cycle": True,
        "month": cycle.month,
        "total_deposits": round(total_deposits, 2),
        "cash_deposits": round(cash_deposits, 2),
        "non_cash_deposits": round(non_cash_deposits, 2),
        "total_expenses": round(total_expenses, 2),
        "paid_expenses": round(paid_expenses, 2),
        "unpaid_expenses": round(unpaid_expenses, 2),
        "total_bkash_approved": round(total_bkash_approved, 2),
        "net_operating": round(total_deposits - total_expenses, 2),
        "users_negative_count": len(negative_users),
        "users_negative_total": round(abs(total_negative), 2),
        "users_negative_list": sorted(negative_users, key=lambda x: x["balance"]),
        "users_positive_count": len(positive_users),
        "users_positive_total": round(total_positive, 2),
        "users_positive_list": sorted(positive_users, key=lambda x: -x["balance"]),
        "free_users_cycle_balance": round(free_cycle_balance, 2),
        "meal_rate": round(rates["final_rate"], 2),
        "inventory_payments": inventory_payments,
        "cashout": total_cashout
    }

@router.get("/daily-fee-overrides")
def list_daily_fee_overrides(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        return []
    return db.query(models.DailyFeeOverride).filter(
        models.DailyFeeOverride.meal_cycle_id == cycle.id
    ).order_by(models.DailyFeeOverride.date).all()

@router.post("/daily-fee-overrides")
def add_daily_fee_override(payload: schemas.DailyFeeOverrideCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        raise HTTPException(status_code=400, detail="No cycle found.")
    if payload.manager_charge is None and payload.guest_charge is None:
        raise HTTPException(status_code=400, detail="Provide at least one charge override.")
    existing = db.query(models.DailyFeeOverride).filter(
        models.DailyFeeOverride.meal_cycle_id == cycle.id,
        models.DailyFeeOverride.date == payload.date
    ).first()
    if existing:
        existing.manager_charge = payload.manager_charge
        existing.guest_charge = payload.guest_charge
        db.commit()
        return {"message": "Override updated.", "date": payload.date}
    override = models.DailyFeeOverride(
        meal_cycle_id=cycle.id, date=payload.date,
        manager_charge=payload.manager_charge, guest_charge=payload.guest_charge
    )
    db.add(override)
    db.commit()
    return {"message": "Override added.", "date": payload.date}

@router.put("/daily-fee-overrides/{override_id}")
def update_daily_fee_override(override_id: int, payload: schemas.DailyFeeOverrideCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    override = db.query(models.DailyFeeOverride).filter(models.DailyFeeOverride.id == override_id).first()
    if not override:
        raise HTTPException(status_code=404, detail="Override not found.")
    override.date = payload.date
    override.manager_charge = payload.manager_charge
    override.guest_charge = payload.guest_charge
    db.commit()
    return {"message": "Override updated."}

@router.delete("/daily-fee-overrides/{override_id}")
def delete_daily_fee_override(override_id: int, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    override = db.query(models.DailyFeeOverride).filter(models.DailyFeeOverride.id == override_id).first()
    if not override:
        raise HTTPException(status_code=404, detail="Override not found.")
    db.delete(override)
    db.commit()
    return {"message": "Override deleted."}

@router.get("/cashouts")
def list_cashouts(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        return []
    return db.query(models.Cashout).filter(models.Cashout.meal_cycle_id == cycle.id).order_by(models.Cashout.date.desc(), models.Cashout.id.desc()).all()

@router.post("/cashouts")
def add_cashout(payload: schemas.CashoutCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        raise HTTPException(status_code=400, detail="No cycle found.")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    c = models.Cashout(meal_cycle_id=cycle.id, date=payload.date, amount=payload.amount, from_method=payload.from_method, notes=payload.notes)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c

@router.put("/cashouts/{cashout_id}")
def update_cashout(cashout_id: int, payload: schemas.CashoutCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    c = db.query(models.Cashout).filter(models.Cashout.id == cashout_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Cashout not found.")
    c.date = payload.date; c.amount = payload.amount; c.from_method = payload.from_method; c.notes = payload.notes
    db.commit()
    return {"message": "Cashout updated."}

@router.delete("/cashouts/{cashout_id}")
def delete_cashout(cashout_id: int, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    c = db.query(models.Cashout).filter(models.Cashout.id == cashout_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Cashout not found.")
    db.delete(c)
    db.commit()
    return {"message": "Cashout deleted."}

@router.get("/inventory-payments")
def list_inventory_payments(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        return []
    payments = db.query(models.InventoryPayment).filter(
        models.InventoryPayment.meal_cycle_id == cycle.id
    ).order_by(models.InventoryPayment.date.desc(), models.InventoryPayment.id.desc()).all()
    return payments

@router.post("/inventory-payments", response_model=schemas.InventoryPaymentResponse)
def add_inventory_payment(payload: schemas.InventoryPaymentCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        raise HTTPException(status_code=400, detail="No cycle found.")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    payment = models.InventoryPayment(
        meal_cycle_id=cycle.id,
        date=payload.date,
        paid_to=payload.paid_to,
        method=payload.method,
        amount=payload.amount,
        notes=payload.notes
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment

@router.put("/inventory-payments/{payment_id}")
def update_inventory_payment(payment_id: int, payload: schemas.InventoryPaymentCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    payment = db.query(models.InventoryPayment).filter(models.InventoryPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    payment.date = payload.date
    payment.paid_to = payload.paid_to
    payment.method = payload.method
    payment.amount = payload.amount
    payment.notes = payload.notes
    db.commit()
    return {"message": "Payment updated."}

@router.delete("/inventory-payments/{payment_id}")
def delete_inventory_payment(payment_id: int, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    payment = db.query(models.InventoryPayment).filter(models.InventoryPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    db.delete(payment)
    db.commit()
    return {"message": "Payment deleted."}

@router.post("/money-flow/pay")
def pay_user_balance(user_id: int, amount: float = 0, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    student = db.query(models.User).filter(models.User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="User not found.")
    # Flexible: allow any positive amount (no cap to global or cycle balance).
    # The refund is recorded as a negative deposit inside the respective cycle
    # so all money-flow / cycle-summary calculations include it.
    import billing_helper
    cycle = billing_helper.get_latest_cycle(db, current_user.hall_id)
    if not cycle:
        # Fallback: any latest cycle (e.g. manager without hall)
        cycle = db.query(models.MealCycle).order_by(models.MealCycle.month.desc()).first()
    if not cycle:
        raise HTTPException(status_code=400, detail="No cycle found.")
    
    student.balance -= amount
    deposit = models.Deposit(
        user_id=student.id, meal_cycle_id=cycle.id, amount=-amount,
        date=date.today().strftime("%Y-%m-%d"),
        description=f"Return to {student.name or student.username} (by {current_user.name or current_user.username})"
    )
    db.add(deposit)
    db.commit()
    return {"message": f"BDT {amount:.2f} returned to {student.name or student.username}.", "balance": round(student.balance, 2)}

@router.post("/cycle/close")
def close_cycle(month: str, current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.month == month,
        models.MealCycle.status == "active"
    ).first()
    
    if not cycle:
        raise HTTPException(status_code=404, detail="Active meal cycle not found for this month.")
        
    # Ensure all past meals are daily-deducted first
    import billing_helper
    billing_helper.deduct_passed_meals(db)
    
    # Calculate final summary/rates
    rates = billing_helper.get_running_meal_rates(cycle, db)
    
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    guest_rate = hall.guest_meal_rate
    mgr_charge = hall.manager_charge_per_day
    
    # Process adjustments and finalize
    user_ids = db.query(models.StudentMealStatus.user_id).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).distinct().all()
    user_ids = [u[0] for u in user_ids]
    
    billed_users_count = 0
    for uid in user_ids:
        user = db.query(models.User).filter(models.User.id == uid).first()
        if not user:
            continue
            
        today_str = date.today().strftime("%Y-%m-%d")
        user_statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.user_id == uid,
            models.StudentMealStatus.status != "off",
            models.StudentMealStatus.date <= today_str
        ).all()
        
        correct_bill = 0.0
        for s in user_statuses:
            mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
            if s.is_guest:
                g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                g_mult = billing_helper._meal_multiplier(s.status)
                if s.status in ("both", "double", "triple"):
                    correct_bill += g_mult * g_dr["final_rate"] + g_mult * guest_charge
                elif s.status == "lunch_only":
                    l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                    correct_bill += g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
                elif s.status == "dinner_only":
                    d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                    correct_bill += g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
            else:
                if not user.free_meal:
                    day_rates = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                    if s.status == "both":
                        correct_bill += day_rates["final_rate"] + mgr_charge
                    elif s.status == "lunch_only":
                        correct_bill += (billing_helper._lunch_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                    elif s.status == "dinner_only":
                        correct_bill += (billing_helper._dinner_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                    elif s.status == "double":
                        correct_bill += (2 * day_rates["final_rate"]) + (2 * mgr_charge)
                    elif s.status == "triple":
                        correct_bill += (3 * day_rates["final_rate"]) + (3 * mgr_charge)
        
        # Calculate what was already deducted daily
        already_deducted = sum(s.amount_deducted for s in user_statuses if s.is_deducted)
        
        # Reconcile user's balance
        adjustment = already_deducted - correct_bill
        user.balance += adjustment
        
        # Mark all statuses as fully deducted and store final settled costs
        # Future-dated meals (date > today) are set to 0 cost — not billed
        all_cycle_statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.user_id == uid
        ).all()
        
        for s in all_cycle_statuses:
            s.is_deducted = True
            if s.date > today_str:
                s.amount_deducted = 0.0
            elif s.status != "off":
                mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
                if s.is_guest:
                    g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                    g_mult = billing_helper._meal_multiplier(s.status)
                    if s.status in ("both", "double", "triple"):
                        s.amount_deducted = g_mult * g_dr["final_rate"] + g_mult * guest_charge
                    elif s.status == "lunch_only":
                        l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                        s.amount_deducted = g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
                    elif s.status == "dinner_only":
                        d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                        s.amount_deducted = g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
                else:
                    if user.free_meal:
                        s.amount_deducted = 0.0
                    else:
                        day_rates = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                        if s.status == "both":
                            s.amount_deducted = day_rates["final_rate"] + mgr_charge
                        elif s.status == "lunch_only":
                            s.amount_deducted = (billing_helper._lunch_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                        elif s.status == "dinner_only":
                            s.amount_deducted = (billing_helper._dinner_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                        elif s.status == "double":
                            s.amount_deducted = (2 * day_rates["final_rate"]) + (2 * mgr_charge)
                        elif s.status == "triple":
                            s.amount_deducted = (3 * day_rates["final_rate"]) + (3 * mgr_charge)
                        else:
                            s.amount_deducted = 0.0
                
        billed_users_count += 1
        
    cycle.status = "closed"
    db.commit()
    
    return {
        "message": f"Meal cycle for {month} closed and balances settled/reconciled.",
        "meal_rate": rates["final_rate"],
        "users_billed": billed_users_count
    }

@router.get("/cycle-summary")
def get_cycle_summary(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    billing_helper.deduct_passed_meals(db)
    
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        return {
            "has_active_cycle": False,
            "students": [],
            "summary": {
                "month": "-",
                "running_meal_rate": 0.0,
                "total_paying_units": 0.0,
                "net_expenses": 0.0
            }
        }
        
    # Compute average daily meal rate up to today.
    # Days with zero expenses (dining was off) are excluded from the average.
    dates = billing_helper.get_cycle_dates(cycle, restrict_to_today=True)
    daily_rates_list = []
    for d in dates:
        dr = billing_helper.get_daily_meal_rates(cycle, d, db)
        if dr["final_rate"] <= 0:
            continue
        daily_rates_list.append(dr["final_rate"])
    running_meal_rate = sum(daily_rates_list) / len(daily_rates_list) if daily_rates_list else 0.0
    
    today_str = date.today().strftime("%Y-%m-%d")
    
    all_statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).all()
    
    statuses = [s for s in all_statuses if s.date <= today_str]
    
    user_ids = {s.user_id for s in all_statuses}
    students = []
    
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    guest_rate = hall.guest_meal_rate
    mgr_charge = hall.manager_charge_per_day
    
    # Pre-fetch all users and deposits
    all_users = {u.id: u for u in db.query(models.User).all()}
    all_deposits = db.query(models.Deposit).filter(models.Deposit.meal_cycle_id == cycle.id).all()
    deposits_by_user = {}
    for d in all_deposits:
        deposits_by_user.setdefault(d.user_id, []).append(d)
    
    # Cache daily rates per date
    rate_cache = {}
    
    # Group non-off statuses by user once (avoids O(users x statuses) scan)
    statuses_by_user = {}
    for s in statuses:
        if s.status != "off":
            statuses_by_user.setdefault(s.user_id, []).append(s)
    
    guest_user_ids = {s.user_id for s in statuses if s.is_guest}
    for s in all_statuses:
        if s.is_guest:
            guest_user_ids.add(s.user_id)
    
    total_paying_units = 0.0
    
    for uid in user_ids:
        u = all_users.get(uid)
        if not u:
            continue
            
        u_statuses = statuses_by_user.get(uid, [])
        
        total_weight = 0.0
        manager_fees = 0.0
        is_guest = False
        bill = 0.0
        
        is_guest = uid in guest_user_ids
        
        for s in u_statuses:
            weight = 1.0
            if s.status == "lunch_only":
                weight = cycle.lunch_percentage
            elif s.status == "dinner_only":
                weight = cycle.dinner_percentage
            elif s.status == "double":
                weight = 2.0
            elif s.status == "triple":
                weight = 3.0
            
            total_weight += weight
            
            if s.date not in rate_cache:
                rate_cache[s.date] = billing_helper.get_daily_meal_rates(cycle, s.date, db)
            dr = rate_cache[s.date]
            mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
            
            if s.is_guest:
                g_mult = billing_helper._meal_multiplier(s.status)
                if s.status in ("both", "double", "triple"):
                    bill += g_mult * dr["final_rate"] + g_mult * guest_charge
                elif s.status == "lunch_only":
                    l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                    bill += g_mult * l_g * dr["final_rate"] + g_mult * guest_charge
                elif s.status == "dinner_only":
                    d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                    bill += g_mult * d_g * dr["final_rate"] + g_mult * guest_charge
            else:
                if not u.free_meal:
                    manager_fees += billing_helper._meal_multiplier(s.status) * mgr_charge
                    if s.status == "both":
                        bill += dr["final_rate"]
                    elif s.status == "lunch_only":
                        bill += billing_helper._lunch_only_pct(s.status, s.date, cycle) * dr["final_rate"]
                    elif s.status == "dinner_only":
                        bill += billing_helper._dinner_only_pct(s.status, s.date, cycle) * dr["final_rate"]
                    elif s.status == "double":
                        bill += 2 * dr["final_rate"]
                    elif s.status == "triple":
                        bill += 3 * dr["final_rate"]
        
        if not is_guest and not u.free_meal:
            total_paying_units += total_weight
                
        total_deposits = sum(d.amount for d in deposits_by_user.get(uid, []))
        
        already_deducted = sum(s.amount_deducted for s in u_statuses if s.is_deducted)
        
        # Cycle-specific balance = deposits - (bill + manager_fees) for this cycle only
        cycle_balance = total_deposits - (bill + manager_fees)
        
        students.append({
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "room_number": u.room_number or "N/A",
            "role": "Guest" if is_guest else u.role,
            "total_meals_weight": round(total_weight, 2),
            "total_deposits": round(total_deposits, 2),
            "manager_fees": round(manager_fees, 2),
            "current_bill": round(bill + manager_fees, 2),
            "current_balance": round(u.balance, 2),
            "cycle_balance": round(cycle_balance, 2),
            "projected_balance": round(cycle_balance, 2)
        })
        
    total_expenses = db.query(models.Expense).filter(models.Expense.meal_cycle_id == cycle.id).with_entities(models.Expense.amount).all()
    total_expenses = sum(e[0] for e in total_expenses) if total_expenses else 0.0
    
    guest_contributions = 0.0
    for s in statuses:
        if s.is_guest and s.status != "off":
            g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
            g_mult = billing_helper._meal_multiplier(s.status)
            _, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
            if s.status in ("both", "double", "triple"):
                guest_contributions += g_mult * g_dr["final_rate"] + g_mult * guest_charge
            elif s.status == "lunch_only":
                l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                guest_contributions += g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
            elif s.status == "dinner_only":
                d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                guest_contributions += g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
            
    net_expenses = max(0.0, total_expenses - guest_contributions)
    
    def get_room_key(item):
        room = item["room_number"]
        digits = "".join([c for c in room if c.isdigit()])
        if digits:
            return (int(digits), room)
        return (99999, room)
    students.sort(key=get_room_key)
    
    return {
        "has_active_cycle": True,
        "students": students,
        "summary": {
            "month": cycle.month,
            "running_meal_rate": running_meal_rate,
            "total_paying_units": round(total_paying_units, 2),
            "net_expenses": round(net_expenses, 2)
        }
    }

@router.post("/cycle/reopen")
def reopen_cycle(month: str, current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.month == month,
        models.MealCycle.status == "closed"
    ).first()
    
    if not cycle:
        raise HTTPException(status_code=404, detail="Closed meal cycle not found for this month.")
        
    from billing_helper import get_running_meal_rate
    running_rate = get_running_meal_rate(cycle, db)
    
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    guest_rate = hall.guest_meal_rate
    mgr_charge = hall.manager_charge_per_day 
    today_str = date.today().strftime("%Y-%m-%d")
    
    # Revert user balances and restore status records
    user_ids = db.query(models.StudentMealStatus.user_id).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).distinct().all()
    user_ids = [u[0] for u in user_ids]
    
    for uid in user_ids:
        user = db.query(models.User).filter(models.User.id == uid).first()
        if not user:
            continue
            
        all_cycle_statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.user_id == uid
        ).all()
        
        # Calculate correct total monthly bill (settled at close)
        correct_bill = 0.0
        # Calculate what should be deducted daily for past days relative to today
        daily_deductions_past = 0.0
        
        for s in all_cycle_statuses:
            if s.status == "off":
                continue
                
            weight = 1.0
            if s.status == "lunch_only":
                weight = cycle.lunch_percentage
            elif s.status == "dinner_only":
                weight = cycle.dinner_percentage
                
            mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
            
            # Full monthly bill calculation
            if s.is_guest:
                g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                g_mult = billing_helper._meal_multiplier(s.status)
                if s.status in ("both", "double", "triple"):
                    correct_bill += g_mult * g_dr["final_rate"] + g_mult * guest_charge
                elif s.status == "lunch_only":
                    l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                    correct_bill += g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
                elif s.status == "dinner_only":
                    d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                    correct_bill += g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
            else:
                if not user.free_meal:
                    day_rates = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                    if s.status == "both":
                        correct_bill += day_rates["final_rate"] + mgr_charge
                    elif s.status == "lunch_only":
                        correct_bill += (billing_helper._lunch_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                    elif s.status == "dinner_only":
                        correct_bill += (billing_helper._dinner_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                    elif s.status == "double":
                        correct_bill += (2 * day_rates["final_rate"]) + (2 * mgr_charge)
                    elif s.status == "triple":
                        correct_bill += (3 * day_rates["final_rate"]) + (3 * mgr_charge)
            
            # Daily deduction for past days relative to today
            if s.date < today_str:
                if s.is_guest:
                    g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                    g_mult = billing_helper._meal_multiplier(s.status)
                    if s.status in ("both", "double", "triple"):
                        daily_deductions_past += g_mult * g_dr["final_rate"] + g_mult * guest_charge
                    elif s.status == "lunch_only":
                        l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                        daily_deductions_past += g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
                    elif s.status == "dinner_only":
                        d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                        daily_deductions_past += g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
                else:
                    if not user.free_meal:
                        day_rates = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                        if s.status == "both":
                            daily_deductions_past += day_rates["final_rate"] + mgr_charge
                        elif s.status == "lunch_only":
                            daily_deductions_past += (billing_helper._lunch_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                        elif s.status == "dinner_only":
                            daily_deductions_past += (billing_helper._dinner_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                        elif s.status == "double":
                            daily_deductions_past += (2 * day_rates["final_rate"]) + (2 * mgr_charge)
                        elif s.status == "triple":
                            daily_deductions_past += (3 * day_rates["final_rate"]) + (3 * mgr_charge)
        
        # Revert closing adjustment: target balance = current_balance + correct_bill - daily_deductions_past
        user.balance = user.balance + correct_bill - daily_deductions_past
        
        # Reset/recalculate status records
        for s in all_cycle_statuses:
            if s.date < today_str:
                s.is_deducted = True
                if s.status != "off":
                    weight = 1.0
                    if s.status == "lunch_only":
                        weight = cycle.lunch_percentage
                    elif s.status == "dinner_only":
                        weight = cycle.dinner_percentage
                    elif s.status == "double":
                        weight = 2.0
                    elif s.status == "triple":
                        weight = 3.0
                    mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
                    if s.is_guest:
                        g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                        g_mult = billing_helper._meal_multiplier(s.status)
                        if s.status in ("both", "double", "triple"):
                            s.amount_deducted = g_mult * g_dr["final_rate"] + g_mult * guest_charge
                        elif s.status == "lunch_only":
                            l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                            s.amount_deducted = g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
                        elif s.status == "dinner_only":
                            d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                            s.amount_deducted = g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
                    else:
                        if user.free_meal:
                            s.amount_deducted = 0.0
                        else:
                            day_rates = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                            if s.status == "both":
                                s.amount_deducted = day_rates["final_rate"] + mgr_charge
                            elif s.status == "lunch_only":
                                s.amount_deducted = (billing_helper._lunch_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                            elif s.status == "dinner_only":
                                s.amount_deducted = (billing_helper._dinner_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
                            elif s.status == "double":
                                s.amount_deducted = (2 * day_rates["final_rate"]) + (2 * mgr_charge)
                            elif s.status == "triple":
                                s.amount_deducted = (3 * day_rates["final_rate"]) + (3 * mgr_charge)
                            else:
                                s.amount_deducted = 0.0
            else:
                s.is_deducted = False
                s.amount_deducted = 0.0
                
    cycle.status = "active"
    db.commit()
    return {"message": f"Meal cycle for {month} reopened successfully.", "status": cycle.status}

@router.post("/cycle/reset")
def reset_cycle(current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.status.in_(["poll", "active"])
    ).order_by(models.MealCycle.month.desc()).first()

    if not cycle:
        raise HTTPException(status_code=404, detail="No active or poll cycle found to reset.")

    # Collect all users who had meal statuses in this cycle
    status_users = db.query(models.StudentMealStatus.user_id).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).distinct().all()
    user_ids = {u[0] for u in status_users}

    # Also collect users who had deposits in this cycle
    deposit_users = db.query(models.Deposit.user_id).filter(
        models.Deposit.meal_cycle_id == cycle.id
    ).distinct().all()
    user_ids.update(u[0] for u in deposit_users)

    # Delete the cycle (cascade removes expenses, meal statuses, deposits)
    db.delete(cycle)
    db.commit()

    # Reset all affected users to fresh defaults for new cycle
    for uid in user_ids:
        u = db.query(models.User).filter(models.User.id == uid).first()
        if u:
            u.balance = 0.0
            u.status = "both"
            u.free_meal = False
            u.egg_alternative = False
            u.prefer_beef = False
            u.prefer_mutton = False
            u.meal_preference = "normal"
            u.fish_egg_pref = "normal"
            u.meat_pref = "normal"
    db.commit()

    return {"message": f"Cycle for {cycle.month} ({cycle.start_date} to {cycle.end_date}) has been fully reset. All users reset to fresh defaults."}

@router.get("/daily-rates")
def get_daily_rates(current_user: models.User = Depends(auth.require_roles(["student", "manager", "assistant_manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        return []
        
    hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
    guest_rate = hall.guest_meal_rate
    
    all_statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).all()
    all_expenses = db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id
    ).all()
    
    users_free_meal = {u.id: u.free_meal for u in db.query(models.User).filter(models.User.hall_id == cycle.hall_id).all()}
    
    rates = []
    
    cumulative_lunch_exp = 0.0
    cumulative_dinner_exp = 0.0
    cumulative_guest_lunch = 0.0
    cumulative_guest_dinner = 0.0
    cumulative_home_lunch_units = 0.0
    cumulative_home_dinner_units = 0.0
    
    dates = billing_helper.get_cycle_dates(cycle, restrict_to_today=True)
    
    # If there are expenses or statuses before the cycle start_date, include those dates
    from sqlalchemy import func
    min_status = db.query(func.min(models.StudentMealStatus.date)).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).scalar()
    min_expense = db.query(func.min(models.Expense.date)).filter(
        models.Expense.meal_cycle_id == cycle.id
    ).scalar()
    earliest_dates = [d for d in [min_status, min_expense] if d is not None]
    earliest_data = min(earliest_dates) if earliest_dates else None
    if earliest_data and dates and earliest_data < dates[0]:
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(earliest_data, "%Y-%m-%d").date()
        end_dt = datetime.strptime(dates[0], "%Y-%m-%d").date()
        extra = []
        curr = start_dt
        while curr < end_dt:
            extra.append(curr.strftime("%Y-%m-%d"))
            curr += timedelta(days=1)
        dates = extra + dates
    
    for date_str in dates:
        
        day_exps = [e for e in all_expenses if e.date == date_str]
        day_statuses = [s for s in all_statuses if s.date == date_str and s.status != "off"]
        
        # Split day expenses into lunch/dinner
        day_lunch_exp = 0.0
        day_dinner_exp = 0.0
        for e in day_exps:
            m_type = (e.meal_type or "").lower()
            if m_type == "lunch":
                day_lunch_exp += e.amount
            elif m_type == "dinner":
                day_dinner_exp += e.amount
            else:
                desc_lower = (e.description or "").lower()
                if "lunch" in desc_lower:
                    day_lunch_exp += e.amount
                elif "dinner" in desc_lower:
                    day_dinner_exp += e.amount
                else:
                    day_lunch_exp += e.amount * 0.5
                    day_dinner_exp += e.amount * 0.5
        
        # Count total non-free eaters (home + guest, including double/triple multiplier)
        total_lunch_eaters = 0
        total_dinner_eaters = 0
        for s in day_statuses:
            is_free = users_free_meal.get(s.user_id, False)
            if is_free:
                continue
            has_lunch = s.status in ["both", "lunch_only", "double", "triple"]
            has_dinner = s.status in ["both", "dinner_only", "double", "triple"]
            mult = billing_helper._meal_multiplier(s.status)
            if has_lunch:
                total_lunch_eaters += mult
            if has_dinner:
                total_dinner_eaters += mult
        
        day_total_exp = sum(e.amount for e in day_exps)
        lunch_exp = day_lunch_exp
        dinner_exp = day_dinner_exp
        
        daily_lunch_rate = lunch_exp / total_lunch_eaters if total_lunch_eaters > 0 else 0.0
        daily_dinner_rate = dinner_exp / total_dinner_eaters if total_dinner_eaters > 0 else 0.0
        
        rates.append({
            "date": date_str,
            "daily_expenses": round(day_total_exp, 2),
            "daily_meals": total_lunch_eaters + total_dinner_eaters,
            "lunch_rate": daily_lunch_rate,
            "dinner_rate": daily_dinner_rate,
            "final_rate": daily_lunch_rate + daily_dinner_rate,
            "rate_with_charges": daily_lunch_rate + daily_dinner_rate + hall.manager_charge_per_day
        })
        
    return rates

@router.get("/students/{user_id}/ledger")
def get_student_ledger(user_id: int, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    """Returns full ledger for a student in the current active/poll cycle: deposits, daily meal log, daily rates."""
    student = db.query(models.User).filter(models.User.id == user_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")
    
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        raise HTTPException(status_code=404, detail="No meal cycle found.")
    
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    guest_rate = hall.guest_meal_rate
    mgr_charge = hall.manager_charge_per_day 
    hall_name = hall.name if hall else "eDining Hall"
    
    # Deposits
    deposits = db.query(models.Deposit).filter(
        models.Deposit.user_id == user_id,
        models.Deposit.meal_cycle_id == cycle.id
    ).order_by(models.Deposit.date).all()
    
    deposits_data = [
        {"date": d.date, "amount": d.amount, "description": d.description or ""}
        for d in deposits
    ]
    total_deposits = sum(d.amount for d in deposits)
    
    # Compute average daily rates up to today.
    # Days with zero expenses (dining was off) are excluded from the average.
    daily_l = 0.0; daily_d = 0.0; daily_f = 0.0; cnt = 0
    for d in billing_helper.get_cycle_dates(cycle, restrict_to_today=True):
        dr = billing_helper.get_daily_meal_rates(cycle, d, db)
        if dr["final_rate"] <= 0:
            continue
        daily_l += dr["lunch_rate"]; daily_d += dr["dinner_rate"]; daily_f += dr["final_rate"]; cnt += 1
    rates = {"lunch_rate": round(daily_l/cnt,2) if cnt else 0, "dinner_rate": round(daily_d/cnt,2) if cnt else 0, "final_rate": round(daily_f/cnt,2) if cnt else 0}
    
    # Daily meal statuses - only include dates up to current limit/today
    if cycle.status in ["active", "poll"]:
        today_str = date.today().strftime("%Y-%m-%d")
        statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == user_id,
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.date <= today_str
        ).order_by(models.StudentMealStatus.date).all()
    else:
        statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == user_id,
            models.StudentMealStatus.meal_cycle_id == cycle.id
        ).order_by(models.StudentMealStatus.date).all()
    
    # Build daily meal log for this student
    daily_meals = []
    total_bill = 0.0
    today_str_meta = date.today().strftime("%Y-%m-%d") if cycle.status in ["active", "poll"] else None
    daily_meta = billing_helper.get_cycle_daily_meta(cycle, db, today_str_meta or (cycle.end_date or today_str_meta))
    for s in statuses:
        day_rates = billing_helper.get_daily_meal_rates(cycle, s.date, db)
        meta = daily_meta.get(s.date, {"expense": 0.0, "meal_count": 0})
        mgr_charge, guest_charge = billing_helper.get_daily_charges(cycle, s.date, db)
        if s.status == "off" or s.status is None:
            day_cost = 0.0
        elif s.is_guest:
            g_dr = billing_helper.get_daily_meal_rates(cycle, s.date, db)
            g_mult = billing_helper._meal_multiplier(s.status)
            if s.status in ("both", "double", "triple"):
                day_cost = g_mult * g_dr["final_rate"] + g_mult * guest_charge
            elif s.status == "lunch_only":
                l_g = billing_helper._lunch_only_pct(s.status, s.date, cycle)
                day_cost = g_mult * l_g * g_dr["final_rate"] + g_mult * guest_charge
            elif s.status == "dinner_only":
                d_g = billing_helper._dinner_only_pct(s.status, s.date, cycle)
                day_cost = g_mult * d_g * g_dr["final_rate"] + g_mult * guest_charge
        elif student.free_meal:
            day_cost = 0.0
        else:
            if s.status == "both":
                day_cost = day_rates["final_rate"] + mgr_charge
            elif s.status == "lunch_only":
                day_cost = (billing_helper._lunch_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
            elif s.status == "dinner_only":
                day_cost = (billing_helper._dinner_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
            elif s.status == "double":
                day_cost = (2 * day_rates["final_rate"]) + (2 * mgr_charge)
            elif s.status == "triple":
                day_cost = (3 * day_rates["final_rate"]) + (3 * mgr_charge)
        
        if s.status != "off":
            total_bill += day_cost
        
        daily_meals.append({
            "date": s.date,
            "status": s.status or "off",
            "ticked_lunch": s.ticked_lunch,
            "ticked_dinner": s.ticked_dinner,
            "is_deducted": s.is_deducted,
            "amount_deducted": s.amount_deducted,
            "lunch_rate": day_rates["lunch_rate"],
            "dinner_rate": day_rates["dinner_rate"],
            "final_rate": day_rates["final_rate"],
            "expense": meta["expense"], "meal_count": meta["meal_count"],
            "day_cost": round(day_cost, 2)
        })
    
    return {
        "student": {
            "id": student.id,
            "username": student.username,
            "name": student.name,
            "room_number": student.room_number or "N/A",
            "hall_name": hall_name
        },
        "cycle": {
            "month": cycle.month,
            "status": cycle.status,
            "lunch_percentage": cycle.lunch_percentage,
            "dinner_percentage": cycle.dinner_percentage
        },
        "deposits": deposits_data,
        "total_deposits": round(total_deposits, 2),
        "daily_meals": daily_meals,
        "total_bill": round(total_bill, 2),
        "mgr_charge_per_day": mgr_charge,
        "current_balance": round(student.balance, 2),
        "rates": {
            "lunch_rate": rates["lunch_rate"],
            "dinner_rate": rates["dinner_rate"],
            "final_rate": rates["final_rate"]
        }
    }

@router.post("/email-bill")
def email_bill(payload: schemas.EmailBillRequest, current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id
    ).order_by(models.MealCycle.month.desc()).first()
    
    if not cycle:
        raise HTTPException(status_code=400, detail="No meal cycle found.")
        
    billing_helper.deduct_passed_meals(db)
    
    summary_data = get_cycle_summary(current_user, db)
    if not summary_data or not summary_data.get("has_active_cycle"):
        raise HTTPException(status_code=400, detail="No active dining summary found.")
        
    students_summary = {s["username"]: s for s in summary_data["students"]}
    
    if payload.send_all:
        # Include all users in the cycle summary (home + guests from other halls)
        target_users = db.query(models.User).filter(
            models.User.username.in_([s["username"] for s in summary_data["students"]])
        ).all()
    elif payload.username:
        u = db.query(models.User).filter(models.User.username == payload.username).first()
        if not u:
            raise HTTPException(status_code=404, detail=f"Student {payload.username} not found.")
        target_users = [u]
    else:
        raise HTTPException(status_code=400, detail="Either username or send_all must be specified.")
        
    sent_emails = []
    skipped_users = []
    
    hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
    hall_name = hall.name if hall else "Mymensingh EC Dining"
    
    # Pick a random manager from this hall as the sender
    import random
    managers = db.query(models.User).filter(
        models.User.hall_id == current_user.hall_id,
        models.User.role == "manager",
        models.User.email.isnot(None),
        models.User.email != ""
    ).all()
    sender_manager = random.choice(managers) if managers else current_user
    sender_name = sender_manager.name
    sender_email = sender_manager.email or "billing-noreply@mymensingh-ec-dining.edu"
    
    # SMTP configuration from DB settings or env vars
    def get_cfg(key, default=""):
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        return row.value if row else os.environ.get(key.upper(), default)
    smtp_host = get_cfg("smtp_host", "")
    smtp_port = int(get_cfg("smtp_port", "587"))
    smtp_user = get_cfg("smtp_user", "")
    smtp_pass = get_cfg("smtp_pass", "")
    use_smtp = bool(smtp_host and smtp_user and smtp_pass)
    
    import time
    
    for u in target_users:
        if not u.email:
            skipped_users.append(u.username)
            continue
        s_sum = students_summary.get(u.username)
        if not s_sum:
            continue
            
        # Determine user's meal status (active if they have any non-off statuses in cycle)
        user_active = bool(db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == u.id,
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.status != "off"
        ).first())
        user_status_label = "Active" if user_active else "Inactive"
        
        # Load bill email template from AppConfig
        bill_subj_row = db.query(models.AppConfig).filter(models.AppConfig.key == "bill_email_subject").first()
        bill_body_row = db.query(models.AppConfig).filter(models.AppConfig.key == "bill_email_body").first()
        
        default_subject = f"Mess Bill Receipt - Cycle {cycle.month} ({user_status_label})"
        default_body = f"""Dear {{name}},

Here is your dining hall billing summary for the cycle {cycle.month}:

  Hall: {hall_name}
  Room Number: {{room}}
  Total Meals Weight: {{weight}}
  Total Cycle Deposits: BDT {{deposits}}
  Manager Surcharge Fees: BDT {{fees}}
  Current Cycle Bill: BDT {{bill}}
  Current Cycle Balance: BDT {{balance}}
  Projected Balance: BDT {{projected}}

Status: {user_status_label}

Thank you,
{sender_name} (Dining Manager)"""
        
        subject = (bill_subj_row.value if bill_subj_row and bill_subj_row.value else default_subject)\
            .replace("{month}", cycle.month).replace("{status}", user_status_label).replace("{hall}", hall_name)
        body_template = bill_body_row.value if bill_body_row and bill_body_row.value else default_body
        body = body_template\
            .replace("{name}", u.name or "Student")\
            .replace("{room}", u.room_number or "N/A")\
            .replace("{weight}", f"{s_sum['total_meals_weight']:.1f}")\
            .replace("{deposits}", f"{s_sum['total_deposits']:.2f}")\
            .replace("{fees}", f"{s_sum['manager_fees']:.2f}")\
            .replace("{bill}", f"{s_sum['current_bill']:.2f}")\
            .replace("{balance}", f"{s_sum.get('cycle_balance', s_sum['current_balance']):.2f}")\
            .replace("{projected}", f"{s_sum['projected_balance']:.2f}")\
            .replace("{month}", cycle.month)\
            .replace("{status}", user_status_label)\
            .replace("{hall}", hall_name)
        
        if use_smtp:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from email.mime.application import MIMEApplication
            from email.header import Header
            if payload.mode == "one_by_one":
                time.sleep(0.3)
            try:
                msg = MIMEMultipart()
                msg["Subject"] = Header(subject, "utf-8")
                msg["From"] = "%s <%s>" % (Header(sender_name, "utf-8").encode(), smtp_user)
                msg["To"] = "%s <%s>" % (Header(u.name, "utf-8").encode(), u.email)
                msg.attach(MIMEText(body.strip(), "plain", "utf-8"))
                
                # Generate and attach PDF bill (required)
                from pdf_helper import generate_bill_pdf
                ledger = get_student_ledger(u.id, current_user, db)
                if not ledger:
                    raise Exception("Failed to load ledger data for %s" % u.username)
                pdf_bytes = generate_bill_pdf(
                    ledger["student"],
                    {
                        "total_deposits": ledger["total_deposits"],
                        "current_bill": ledger["total_bill"],
                        "manager_fees": s_sum["manager_fees"],
                        "cycle_balance": s_sum.get("cycle_balance", s_sum["current_balance"])
                    },
                    ledger["cycle"],
                    ledger["student"]["hall_name"],
                    ledger["deposits"],
                    ledger["daily_meals"],
                    ledger["rates"]
                )
                attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
                attachment.add_header("Content-Disposition", "attachment", filename="bill_%s_%s.pdf" % (u.username, cycle.month))
                msg.attach(attachment)
                
                with smtplib.SMTP(smtp_host, int(smtp_port), timeout=15) as server:
                    server.set_debuglevel(1)
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(smtp_user, smtp_pass)
                    fails = server.sendmail(smtp_user, [u.email], msg.as_string())
                    if fails:
                        raise Exception("Sendmail failures: %s" % str(fails))
                print("[EMAIL] Sent successfully to %s <%s>" % (u.name, u.email))
                sent_emails.append(u.email)
            except smtplib.SMTPAuthenticationError:
                skipped_users.append("%s (SMTP auth failed - check username/password)" % u.username)
            except smtplib.SMTPException as e:
                skipped_users.append("%s (SMTP error: %s)" % (u.username, str(e)))
            except Exception as e:
                skipped_users.append("%s (error: %s)" % (u.username, str(e)))
        else:
            # Simulation mode — print to console
            print(f"[EMAIL SIM] To: {u.email} | Subject: {subject}")
            sent_emails.append(u.email)
        
    res_message = f"{'Emails sent' if use_smtp else 'Simulated emails'} to {len(sent_emails)} address(es)."
    if skipped_users:
        res_message += f" Skipped {len(skipped_users)}: {', '.join(skipped_users)}."
        
    return {
        "message": res_message,
        "sent_count": len(sent_emails),
        "sent_emails": sent_emails,
        "skipped_users": skipped_users
    }


@router.get("/bkash/transactions")
def get_bkash_transactions(current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    transactions = db.query(models.BkashReceivedSms).order_by(models.BkashReceivedSms.id.desc()).all()
    
    results = []
    for t in transactions:
        claimed_by = None
        if t.is_claimed and t.claimed_by_user_id:
            user = db.query(models.User).filter(models.User.id == t.claimed_by_user_id).first()
            if user:
                claimed_by = f"{user.name} ({user.username})"
                
        results.append({
            "id": t.id,
            "trx_id": t.trx_id,
            "sender": t.sender,
            "amount": t.amount,
            "status": t.status or "pending",
            "approved_amount": t.approved_amount,
            "is_claimed": t.is_claimed,
            "claimed_by": claimed_by,
            "date_received": t.date_received
        })
    return results



@router.post("/bkash/transactions")
def add_bkash_transaction(payload: schemas.BkashManualTransactionCreate, current_user: models.User = Depends(auth.require_roles(["manager", "assistant_manager"])), db: Session = Depends(get_db)):
    trx_id_upper = payload.trx_id.strip().upper()
    if not trx_id_upper or len(trx_id_upper) != 10 or not trx_id_upper.isalnum():
        raise HTTPException(status_code=400, detail="Invalid Transaction ID. Must be 10 alphanumeric characters.")
        
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
        
    existing = db.query(models.BkashReceivedSms).filter(models.BkashReceivedSms.trx_id == trx_id_upper).first()
    if existing:
        raise HTTPException(status_code=400, detail="Transaction ID already exists in database.")
        
    sender = (payload.sender or "Manager").strip()
    new_trx = models.BkashReceivedSms(
        trx_id=trx_id_upper,
        sender=sender,
        amount=payload.amount,
        raw_text=f"Manually added by Manager ({current_user.username})",
        is_claimed=False,
        date_received=date.today().strftime("%Y-%m-%d")
    )
    db.add(new_trx)
    db.commit()
    return {"message": "Transaction added successfully.", "trx_id": trx_id_upper}


@router.post("/bkash/set-pin")
def set_manager_pin(pin: str, current_user: models.User = Depends(auth.require_roles(["manager"])), db: Session = Depends(get_db)):
    if not pin.isdigit() or len(pin) != 4:
        raise HTTPException(status_code=400, detail="PIN must be exactly 4 digits.")
    row = db.query(models.AppConfig).filter(models.AppConfig.key == "manager_pin").first()
    if row:
        row.value = pin
    else:
        db.add(models.AppConfig(key="manager_pin", value=pin))
    db.commit()
    return {"message": "Manager PIN set successfully."}


@router.post("/bkash/check-pin")
def check_manager_pin(pin: str, db: Session = Depends(get_db)):
    row = db.query(models.AppConfig).filter(models.AppConfig.key == "manager_pin").first()
    if not row or not row.value or pin != row.value:
        raise HTTPException(status_code=403, detail="Invalid PIN.")
    return {"valid": True}


@router.get("/bkash/pending")
def get_pending_transactions(db: Session = Depends(get_db)):
    transactions = db.query(models.BkashReceivedSms).filter(
        models.BkashReceivedSms.status == "pending"
    ).order_by(models.BkashReceivedSms.id.desc()).all()
    results = []
    for t in transactions:
        claimed_by = None
        if t.claimed_by_user_id:
            u = db.query(models.User).filter(models.User.id == t.claimed_by_user_id).first()
            if u: claimed_by = u.name + " (" + u.username + ")"
        results.append({
            "id": t.id, "trx_id": t.trx_id, "sender": t.sender,
            "amount": t.amount or 0, "claimed_by": claimed_by,
            "date_received": t.date_received
        })
    return results


@router.post("/bkash/approve")
def approve_bkash_transaction(
    trx_id: str, amount: float, pin: str = "",
    current_user: models.User = Depends(auth.get_current_user_or_none),
    db: Session = Depends(get_db)
):
    # Require PIN only if not logged in via JWT
    if current_user is None:
        stored_pin = db.query(models.AppConfig).filter(models.AppConfig.key == "manager_pin").first()
        if not stored_pin or not stored_pin.value or pin != stored_pin.value:
            raise HTTPException(status_code=403, detail="Invalid PIN.")
    elif current_user.role not in ["manager", "assistant_manager", "superadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized.")
    
    trx = db.query(models.BkashReceivedSms).filter(models.BkashReceivedSms.trx_id == trx_id.upper()).first()
    if not trx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if trx.status == "approved":
        raise HTTPException(status_code=400, detail="Already approved.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")

    trx.status = "approved"
    trx.approved_amount = amount

    # Find student and create deposit in the running cycle (any status, incl.
    # auto-closed) — the manager's hall cycle first, then the student's, then any.
    student = db.query(models.User).filter(models.User.id == trx.claimed_by_user_id).first()
    if student:
        today = date.today()
        cycle = None
        if current_user and current_user.hall_id:
            cycle = billing_helper.get_latest_cycle(db, current_user.hall_id)
        if not cycle and student.hall_id:
            cycle = billing_helper.get_latest_cycle(db, student.hall_id)
        if not cycle:
            cycle = billing_helper.get_latest_cycle(db)
        dep = models.Deposit(
            user_id=student.id,
            meal_cycle_id=cycle.id if cycle else None,
            amount=amount,
            date=today.strftime("%Y-%m-%d"),
            description="bKash approved (TrxID: " + trx.trx_id + ")"
        )
        db.add(dep)
        student.balance += amount

    db.commit()

    # Send confirmation email if SMTP configured (async)
    if student and student.email:
        import threading
        threading.Thread(target=_send_deposit_email, args=(student, amount, trx.trx_id, db), daemon=True).start()

    return {"message": "Transaction approved, deposit created.", "trx_id": trx.trx_id, "amount": amount}


def _send_deposit_email(student, amount, trx_id, db, template_type="bkash"):
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    for key in ["smtp_host", "smtp_port", "smtp_user", "smtp_pass"]:
        row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
        if row and row.value:
            if key == "smtp_host": smtp_host = row.value
            elif key == "smtp_user": smtp_user = row.value
            elif key == "smtp_pass": smtp_pass = row.value
    if not (smtp_host and smtp_user and smtp_pass):
        return
    
    # Load email templates from AppConfig
    prefix = "deposit_email_" + template_type
    default_subject = "Deposit Approved - eDining" if template_type == "bkash" else "Deposit Confirmed - eDining"
    default_body = "Dear %s,\n\nYour deposit of BDT %.2f has been approved.\nTransaction: %s\n\nThank you,\neDining Management" % (student.name, amount, trx_id)
    if template_type == "manual":
        default_body = "Dear %s,\n\nYour deposit of BDT %.2f has been recorded.\nReference: %s\n\nThank you,\neDining Management" % (student.name, amount, trx_id)
    
    subj_row = db.query(models.AppConfig).filter(models.AppConfig.key == prefix + "_subject").first()
    subject = subj_row.value if subj_row and subj_row.value else default_subject
    body_row = db.query(models.AppConfig).filter(models.AppConfig.key == prefix + "_body").first()
    body_template = body_row.value if body_row and body_row.value else default_body
    
    # Compute current cycle balance for the student
    cycle_balance = student.balance
    active_cycle = db.query(models.MealCycle).filter(models.MealCycle.status == "active", models.MealCycle.hall_id == student.hall_id).first()
    if active_cycle:
        dep_sum = db.query(models.Deposit).filter(models.Deposit.user_id == student.id, models.Deposit.meal_cycle_id == active_cycle.id).with_entities(models.Deposit.amount).all()
        total_dep = sum(d[0] for d in dep_sum) if dep_sum else 0.0
        bill_statuses = db.query(models.StudentMealStatus).filter(models.StudentMealStatus.user_id == student.id, models.StudentMealStatus.meal_cycle_id == active_cycle.id, models.StudentMealStatus.is_deducted == True).all()
        total_ded = sum(s.amount_deducted or 0 for s in bill_statuses)
        cycle_balance = round(total_dep - total_ded, 2)
    
    body = body_template.replace("{name}", student.name or "Student").replace("{amount}", f"{amount:.2f}").replace("{trx_id}", trx_id).replace("{date}", date.today().strftime("%Y-%m-%d")).replace("{balance}", f"{cycle_balance:.2f}")
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = smtp_user
        msg["To"] = student.email
        with smtplib.SMTP(smtp_host, 587, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [student.email], msg.as_string())
    except Exception:
        pass

