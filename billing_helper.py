from datetime import date
from sqlalchemy.orm import Session
import models

import datetime
import contextvars

# Per-request cache so repeated rate/charge lookups in loops hit memory, not the DB.
# The middleware in main.py resets this at the start of every request.
_request_cache = contextvars.ContextVar("billing_request_cache", default=None)

def request_cache_clear():
    _request_cache.set(None)

def _get_cache():
    c = _request_cache.get()
    if c is None:
        c = {}
        _request_cache.set(c)
    return c

def _meal_multiplier(status: str) -> int:
    return {"double": 2, "triple": 3}.get(status, 1)

def _is_full_rate_day(date_str: str, cycle) -> bool:
    """Check if a date falls on a configured full-rate weekday.
    full_rate_days is comma-separated weekday numbers (0=Mon, 4=Fri, 6=Sun)."""
    full_rate_days = (getattr(cycle, 'full_rate_days', None) or '4').split(',')
    try:
        return str(datetime.datetime.strptime(date_str, "%Y-%m-%d").weekday()) in full_rate_days
    except:
        return False

def get_daily_charges(cycle, date_str: str, db: Session):
    """Return (manager_charge, guest_charge) for a date.
    Uses the hall's configured default unless a per-date override exists."""
    cache = _get_cache()
    key = ("charges", cycle.id, date_str)
    if key in cache:
        return cache[key]
    hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
    mgr = hall.manager_charge_per_day if hall else 5.0
    guest = hall.guest_charge_per_day if hall else 5.0
    override = db.query(models.DailyFeeOverride).filter(
        models.DailyFeeOverride.meal_cycle_id == cycle.id,
        models.DailyFeeOverride.date == date_str
    ).first()
    if override:
        if override.manager_charge is not None:
            mgr = override.manager_charge
        if override.guest_charge is not None:
            guest = override.guest_charge
    result = (mgr, guest)
    cache[key] = result
    return result

def _lunch_only_pct(status: str, date_str: str, cycle) -> float:
    """Return effective lunch_only multiplier (1.0 on full-rate days)."""
    return 1.0 if _is_full_rate_day(date_str, cycle) else (cycle.lunch_only_rate_percentage or 0.4)

def _dinner_only_pct(status: str, date_str: str, cycle) -> float:
    """Return effective dinner_only multiplier (1.0 on full-rate days)."""
    return 1.0 if _is_full_rate_day(date_str, cycle) else (cycle.dinner_only_rate_percentage or 0.6)

def get_daily_meal_rates(cycle: models.MealCycle, target_date: str, db: Session) -> dict:
    cache = _get_cache()
    key = ("rates", cycle.id, target_date)
    if key in cache:
        return cache[key]
    expenses = db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id,
        models.Expense.date == target_date
    ).all()
    
    total_lunch_exp = 0.0
    total_dinner_exp = 0.0
    for e in expenses:
        m_type = (e.meal_type or "").lower()
        if m_type == "lunch":
            total_lunch_exp += e.amount
        elif m_type == "dinner":
            total_dinner_exp += e.amount
        else:
            desc_lower = (e.description or "").lower()
            if "lunch" in desc_lower:
                total_lunch_exp += e.amount
            elif "dinner" in desc_lower:
                total_dinner_exp += e.amount
            else:
                total_lunch_exp += e.amount * 0.5
                total_dinner_exp += e.amount * 0.5
                
    meals = db.query(models.StudentMealStatus, models.User.free_meal).outerjoin(
        models.User, models.User.id == models.StudentMealStatus.user_id
    ).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date == target_date,
        models.StudentMealStatus.status != "off"
    ).all()
    
    total_lunch_eaters = 0
    total_dinner_eaters = 0
    
    for m, free_meal in meals:
        if free_meal is True:
            continue
        has_lunch = m.status in ["both", "lunch_only", "double", "triple"]
        has_dinner = m.status in ["both", "dinner_only", "double", "triple"]
        mult = _meal_multiplier(m.status)
        if has_lunch:
            total_lunch_eaters += mult
        if has_dinner:
            total_dinner_eaters += mult
    
    lunch_rate = 0.0
    dinner_rate = 0.0
    if total_lunch_eaters > 0:
        lunch_rate = total_lunch_exp / total_lunch_eaters
    if total_dinner_eaters > 0:
        dinner_rate = total_dinner_exp / total_dinner_eaters
        
    result = {
        "lunch_rate": lunch_rate,
        "dinner_rate": dinner_rate,
        "final_rate": lunch_rate + dinner_rate
    }
    cache[key] = result
    return result

def get_running_meal_rates(cycle: models.MealCycle, db: Session) -> dict:
    # A cycle's rate only covers its own date range — never include days after
    # the cycle end date (e.g. 15 Aug) or before its start.
    expenses_q = db.query(models.Expense).filter(models.Expense.meal_cycle_id == cycle.id)
    if cycle.start_date:
        expenses_q = expenses_q.filter(models.Expense.date >= cycle.start_date)
    if cycle.end_date:
        expenses_q = expenses_q.filter(models.Expense.date <= cycle.end_date)
    expenses = expenses_q.all()
    
    total_lunch_exp = 0.0
    total_dinner_exp = 0.0
    for e in expenses:
        m_type = (e.meal_type or "").lower()
        if m_type == "lunch":
            total_lunch_exp += e.amount
        elif m_type == "dinner":
            total_dinner_exp += e.amount
        else:
            desc_lower = (e.description or "").lower()
            if "lunch" in desc_lower:
                total_lunch_exp += e.amount
            elif "dinner" in desc_lower:
                total_dinner_exp += e.amount
            else:
                total_lunch_exp += e.amount * 0.5
                total_dinner_exp += e.amount * 0.5
                
    meals_q = db.query(models.StudentMealStatus, models.User.free_meal).outerjoin(
        models.User, models.User.id == models.StudentMealStatus.user_id
    ).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.status != "off"
    )
    if cycle.start_date:
        meals_q = meals_q.filter(models.StudentMealStatus.date >= cycle.start_date)
    if cycle.end_date:
        meals_q = meals_q.filter(models.StudentMealStatus.date <= cycle.end_date)
    meals = meals_q.all()
    
    total_lunch_eaters = 0
    total_dinner_eaters = 0
    
    for m, free_meal in meals:
        if free_meal is True:
            continue
        has_lunch = m.status in ["both", "lunch_only", "double", "triple"]
        has_dinner = m.status in ["both", "dinner_only", "double", "triple"]
        mult = _meal_multiplier(m.status)
        if has_lunch:
            total_lunch_eaters += mult
        if has_dinner:
            total_dinner_eaters += mult
    
    lunch_rate = 0.0
    dinner_rate = 0.0
    if total_lunch_eaters > 0:
        lunch_rate = total_lunch_exp / total_lunch_eaters
    if total_dinner_eaters > 0:
        dinner_rate = total_dinner_exp / total_dinner_eaters
        
    return {
        "lunch_rate": lunch_rate,
        "dinner_rate": dinner_rate,
        "final_rate": lunch_rate + dinner_rate
    }

def get_running_meal_rate(cycle: models.MealCycle, db: Session) -> float:
    rates = get_running_meal_rates(cycle, db)
    return rates["final_rate"]

def prune_cycle_after_end_date(cycle: models.MealCycle, db: Session, end_date_str: str = None) -> int:
    """Delete meal statuses dated after the cycle's end date (stale rows left behind
    when the end date was moved earlier). Returns the number of rows removed."""
    end_str = end_date_str or cycle.end_date
    if not end_str:
        return 0
    try:
        datetime.datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError:
        return 0
    deleted = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date > end_str
    ).delete(synchronize_session=False)
    if deleted:
        db.commit()
    return deleted

def auto_close_expired_cycles(db: Session) -> list:
    """Mark any cycle whose end_date is before today as 'closed' (no settlement)."""
    from datetime import datetime
    today = datetime.now().date()
    cycles = db.query(models.MealCycle).filter(models.MealCycle.status != "closed").all()
    newly_closed = []
    for c in cycles:
        if c.end_date:
            try:
                end_dt = datetime.strptime(c.end_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if today > end_dt:
                c.status = "closed"
                prune_cycle_after_end_date(c, db, c.end_date)
                newly_closed.append(c.month)
    if newly_closed:
        db.commit()
    return newly_closed

def deduct_passed_meals(db: Session):
    request_cache_clear()
    auto_close_expired_cycles(db)
    today_str = date.today().strftime("%Y-%m-%d")
    
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.date <= today_str,
        models.StudentMealStatus.status != "off",
        models.StudentMealStatus.is_deducted == False
    ).all()
    
    if not statuses:
        return
        
    cycle_rates = {}
    hall_mgr_charges = {}
    
    # Batch-fetch cycles and users once (avoids per-status queries)
    cycle_ids = {s.meal_cycle_id for s in statuses}
    user_ids = {s.user_id for s in statuses}
    cycle_map = {c.id: c for c in db.query(models.MealCycle).filter(models.MealCycle.id.in_(cycle_ids)).all()}
    user_map = {u.id: u for u in db.query(models.User).filter(models.User.id.in_(user_ids)).all()}
    
    for s in statuses:
        cycle = cycle_map.get(s.meal_cycle_id)
        u = user_map.get(s.user_id)
        if not cycle or not u:
            continue
        
        # Skip records with dates before the cycle's start_date
        if cycle.start_date and s.date < cycle.start_date:
            s.is_deducted = True
            s.amount_deducted = 0.0
            continue
        
        # Never bill statuses dated after the cycle's end date (stale rows)
        if cycle.end_date and s.date > cycle.end_date:
            s.is_deducted = True
            s.amount_deducted = 0.0
            continue
            
        cost = 0.0
        mgr_charge, guest_charge = get_daily_charges(cycle, s.date, db)
        if s.is_guest:
            rate_key = (cycle.id, s.date)
            if rate_key not in cycle_rates:
                cycle_rates[rate_key] = get_daily_meal_rates(cycle, s.date, db)
            rates = cycle_rates[rate_key]
            mult = _meal_multiplier(s.status)
            if s.status in ("both", "double", "triple"):
                cost = mult * rates["final_rate"] + mult * guest_charge
            elif s.status == "lunch_only":
                cost = mult * _lunch_only_pct(s.status, s.date, cycle) * rates["final_rate"] + mult * guest_charge
            elif s.status == "dinner_only":
                cost = mult * _dinner_only_pct(s.status, s.date, cycle) * rates["final_rate"] + mult * guest_charge
        else:
            if not u.free_meal:
                rate_key = (cycle.id, s.date)
                if rate_key not in cycle_rates:
                    cycle_rates[rate_key] = get_daily_meal_rates(cycle, s.date, db)
                rates = cycle_rates[rate_key]
                
                mult = _meal_multiplier(s.status)
                if s.status == "both":
                    cost = rates["final_rate"] + mgr_charge
                elif s.status == "lunch_only":
                    cost = (_lunch_only_pct(s.status, s.date, cycle) * rates["final_rate"]) + mgr_charge
                elif s.status == "dinner_only":
                    cost = (_dinner_only_pct(s.status, s.date, cycle) * rates["final_rate"]) + mgr_charge
                elif s.status in ("double", "triple"):
                    cost = (mult * rates["final_rate"]) + (mult * mgr_charge)
                
        u.balance -= cost
        s.amount_deducted = cost
        s.is_deducted = True
        
    db.commit()

def get_student_remaining_balance(user: models.User, db: Session) -> float:
    if user.free_meal:
        return user.balance
        
    today_str = date.today().strftime("%Y-%m-%d")
    upcoming_meals = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.user_id == user.id,
        models.StudentMealStatus.date >= today_str,
        models.StudentMealStatus.status != "off",
        models.StudentMealStatus.is_deducted == False
    ).all()
    
    projected_bill = 0.0
    cycle_rates = {}
    
    for m in upcoming_meals:
        cycle_m = db.query(models.MealCycle).filter(models.MealCycle.id == m.meal_cycle_id).first()
        if not cycle_m:
            continue
            
        mgr_charge, guest_charge = get_daily_charges(cycle_m, m.date, db)
        if m.is_guest:
            if cycle_m.id not in cycle_rates:
                cycle_rates[cycle_m.id] = get_running_meal_rates(cycle_m, db)
            g_rates = cycle_rates[cycle_m.id]
            g_mult = _meal_multiplier(m.status)
            if m.status in ("both", "double", "triple"):
                projected_bill += g_mult * g_rates["final_rate"] + g_mult * guest_charge
            elif m.status == "lunch_only":
                projected_bill += g_mult * _lunch_only_pct(m.status, m.date, cycle_m) * g_rates["final_rate"] + g_mult * guest_charge
            elif m.status == "dinner_only":
                projected_bill += g_mult * _dinner_only_pct(m.status, m.date, cycle_m) * g_rates["final_rate"] + g_mult * guest_charge
        else:
            if cycle_m.id not in cycle_rates:
                cycle_rates[cycle_m.id] = get_running_meal_rates(cycle_m, db)
            rates = cycle_rates[cycle_m.id]
            
            mult = _meal_multiplier(m.status)
            if m.status == "both":
                projected_bill += rates["final_rate"] + mgr_charge
            elif m.status == "lunch_only":
                projected_bill += (_lunch_only_pct(m.status, m.date, cycle_m) * rates["final_rate"]) + mgr_charge
            elif m.status == "dinner_only":
                projected_bill += (_dinner_only_pct(m.status, m.date, cycle_m) * rates["final_rate"]) + mgr_charge
            elif m.status in ("double", "triple"):
                projected_bill += (mult * rates["final_rate"]) + (mult * mgr_charge)

    return round(user.balance - projected_bill, 2)

def get_cycle_daily_meta(cycle: models.MealCycle, db: Session, today_str: str = None) -> dict:
    """Per-date {expense, meal_count} for a cycle, matching /search + /daily-rates.
    meal_count = lunch eaters + dinner eaters with status multiplier, excluding free-meal users."""
    today_str = today_str or datetime.date.today().strftime("%Y-%m-%d")
    # Never include data past the cycle's end date in per-day totals
    if cycle.end_date and cycle.end_date < today_str:
        today_str = cycle.end_date
    exp_by_date = {}
    cycle_expenses = db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id,
        models.Expense.date <= today_str
    ).all()
    for e in cycle_expenses:
        exp_by_date[e.date] = exp_by_date.get(e.date, 0.0) + e.amount

    users_free = {u.id: u.free_meal for u in db.query(models.User).all()}
    lunch_by_date = {}
    dinner_by_date = {}
    all_day_statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.status != "off",
        models.StudentMealStatus.date <= today_str
    ).all()
    for s in all_day_statuses:
        if users_free.get(s.user_id, False):
            continue
        mult = _meal_multiplier(s.status)
        if s.status in ["both", "lunch_only", "double", "triple"]:
            lunch_by_date[s.date] = lunch_by_date.get(s.date, 0) + mult
        if s.status in ["both", "dinner_only", "double", "triple"]:
            dinner_by_date[s.date] = dinner_by_date.get(s.date, 0) + mult

    return {
        d: {
            "expense": round(exp_by_date.get(d, 0.0), 2),
            "meal_count": lunch_by_date.get(d, 0) + dinner_by_date.get(d, 0)
        }
        for d in set(list(exp_by_date.keys()) + list(lunch_by_date.keys()) + list(dinner_by_date.keys()))
    }


def get_cycle_dates(cycle: models.MealCycle, restrict_to_today: bool = False) -> list[str]:
    import calendar
    
    if cycle.start_date:
        try:
            start_dt = datetime.datetime.strptime(cycle.start_date, "%Y-%m-%d").date()
        except ValueError:
            start_dt = datetime.date(int(cycle.month[:4]), int(cycle.month[5:7]), 1)
    else:
        start_dt = datetime.date(int(cycle.month[:4]), int(cycle.month[5:7]), 1)
        
    if cycle.end_date:
        try:
            end_dt = datetime.datetime.strptime(cycle.end_date, "%Y-%m-%d").date()
        except ValueError:
            year, month_num = map(int, cycle.month.split("-"))
            last_day = calendar.monthrange(year, month_num)[1]
            end_dt = datetime.date(year, month_num, last_day)
    else:
        year, month_num = map(int, cycle.month.split("-"))
        last_day = calendar.monthrange(year, month_num)[1]
        end_dt = datetime.date(year, month_num, last_day)
        
    if restrict_to_today and cycle.status in ["active", "poll"]:
        today = datetime.date.today()
        current_limit = min(max(today, start_dt), end_dt)
    else:
        current_limit = end_dt
        
    if start_dt > current_limit:
        return []
    dates = []
    curr = start_dt
    while curr <= current_limit:
        dates.append(curr.strftime("%Y-%m-%d"))
        curr += datetime.timedelta(days=1)
    return dates

def get_cycle_end_date(cycle) -> datetime.date:
    """Return the effective end date of a cycle, correctly handling multi-month spans."""
    import calendar
    if cycle.end_date:
        try:
            return datetime.datetime.strptime(cycle.end_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    # Fallback: use cycle.month to determine the last calendar day
    year, month_num = int(cycle.month[:4]), int(cycle.month[5:7])
    last_day = calendar.monthrange(year, month_num)[1]
    return datetime.date(year, month_num, last_day)

def get_latest_cycle(db: Session, hall_id: int = None):
    """Latest (running) cycle for a hall — any status, incl. closed — so approved
    bKash payments and other credits always land in the cycle the manager operates."""
    q = db.query(models.MealCycle)
    if hall_id:
        q = q.filter(models.MealCycle.hall_id == hall_id)
    return q.order_by(models.MealCycle.month.desc()).first()

def _last_known_status(user_id: int, cycle_id: int, target_date: str, db: Session) -> dict:
    """Find the user's most recent meal status before target_date in this cycle.
    Returns {'status': str, 'ticked_lunch': bool, 'ticked_dinner': bool}.
    Falls back to user's profile status if no prior record exists."""
    from sqlalchemy import desc
    prior = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.user_id == user_id,
        models.StudentMealStatus.meal_cycle_id == cycle_id,
        models.StudentMealStatus.date < target_date
    ).order_by(desc(models.StudentMealStatus.date)).first()
    if prior:
        return {"status": prior.status, "ticked_lunch": prior.ticked_lunch, "ticked_dinner": prior.ticked_dinner}
    user = db.query(models.User).filter(models.User.id == user_id).first()
    default = (user.status or "both") if user else "both"
    t_lunch = default in ["both", "lunch_only", "double", "triple"]
    t_dinner = default in ["both", "dinner_only", "double", "triple"]
    return {"status": default, "ticked_lunch": t_lunch, "ticked_dinner": t_dinner}

def adjust_deductions_for_date(cycle: models.MealCycle, target_date: str, db: Session):
    """Recomputed deductions for all already-deducted records on a specific date.
    If the meal rate changed (expenses added/edited), adjusts each student's balance
    by the delta: new_cost - old_deducted. Does NOT touch non-deducted records."""
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date == target_date,
        models.StudentMealStatus.status != "off",
        models.StudentMealStatus.is_deducted == True
    ).all()
    if not statuses:
        return
    
    day_rates = get_daily_meal_rates(cycle, target_date, db)
    mgr_charge, g_charge = get_daily_charges(cycle, target_date, db)
    
    for s in statuses:
        old_cost = s.amount_deducted or 0.0
        if s.is_guest:
            g_dr = get_daily_meal_rates(cycle, s.date, db)
            g_mult = _meal_multiplier(s.status)
            if s.status in ("both", "double", "triple"):
                new_cost = g_mult * g_dr["final_rate"] + g_mult * g_charge
            elif s.status == "lunch_only":
                new_cost = g_mult * _lunch_only_pct(s.status, s.date, cycle) * g_dr["final_rate"] + g_mult * g_charge
            elif s.status == "dinner_only":
                new_cost = g_mult * _dinner_only_pct(s.status, s.date, cycle) * g_dr["final_rate"] + g_mult * g_charge
        else:
            u = db.query(models.User).filter(models.User.id == s.user_id).first()
            if not u or u.free_meal:
                continue
            if s.status == "both":
                new_cost = day_rates["final_rate"] + mgr_charge
            elif s.status == "lunch_only":
                new_cost = (_lunch_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
            elif s.status == "dinner_only":
                new_cost = (_dinner_only_pct(s.status, s.date, cycle) * day_rates["final_rate"]) + mgr_charge
            else:
                new_cost = 0.0
        
        delta = round(new_cost - old_cost, 2)
        if delta != 0:
            u = db.query(models.User).filter(models.User.id == s.user_id).first()
            if u:
                u.balance -= delta
                s.amount_deducted = round(new_cost, 2)
    
    db.commit()
