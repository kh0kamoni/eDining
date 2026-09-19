from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
import auth
from datetime import datetime, date, timedelta
import billing_helper
from routers.admin_router import check_feature_locked

router = APIRouter(prefix="/student", tags=["Student Panel"])

def check_cutoff(target_date_str: str, cutoff_time_str: str):
    """
    Returns True if the cutoff has passed for target_date_str.
    Cutoff time format: "HH:MM" (e.g., "20:00")
    """
    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    
    today = date.today()
    
    # Can't change past or today's meals
    if target_date <= today:
        return True
        
    # If target date is tomorrow, check the cutoff time today
    if target_date == today + timedelta(days=1):
        now = datetime.now()
        try:
            cutoff_h, cutoff_m = map(int, cutoff_time_str.split(":"))
        except ValueError:
            cutoff_h, cutoff_m = 20, 0 # default 8 PM
            
        cutoff_datetime = datetime.combine(today, datetime.min.time()).replace(hour=cutoff_h, minute=cutoff_m)
        if now >= cutoff_datetime:
            return True
            
    return False

@router.get("/dashboard-info")
def get_dashboard_info(current_user: models.User = Depends(auth.require_roles(["student", "manager", "assistant_manager"])), db: Session = Depends(get_db)):
    billing_helper.deduct_passed_meals(db)
    
    # Find home hall cycle for UI display
    current_cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.status.in_(["active", "poll"])
    ).order_by(models.MealCycle.month.desc()).first()

    # Find all active/poll cycles where this user has meal statuses (home + guest)
    all_active_cycles = db.query(models.MealCycle).filter(
        models.MealCycle.status.in_(["active", "poll"])
    ).all()
    
    cycle_deposits = 0.0
    cycle_deductions = 0.0
    
    for c in all_active_cycles:
        # Sum deposits in this cycle
        dep_sum = db.query(models.Deposit).filter(
            models.Deposit.user_id == current_user.id,
            models.Deposit.meal_cycle_id == c.id
        ).with_entities(models.Deposit.amount).all()
        cycle_deposits += sum(d[0] for d in dep_sum) if dep_sum else 0.0
        
        # Recalculate deductions for this cycle
        ded_statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == current_user.id,
            models.StudentMealStatus.meal_cycle_id == c.id,
            models.StudentMealStatus.is_deducted == True
        ).all()
        if not ded_statuses:
            continue
        hall_obj = db.query(models.Hall).filter(models.Hall.id == c.hall_id).first()
        mgr_rate = hall_obj.manager_charge_per_day if hall_obj else 5.0
        for s in ded_statuses:
            if s.status == "off":
                continue
            mgr_rate, g_charge_s = billing_helper.get_daily_charges(c, s.date, db)
            if s.is_guest:
                g_dr = billing_helper.get_daily_meal_rates(c, s.date, db)
                g_mult_s = billing_helper._meal_multiplier(s.status)
                if s.status in ("both", "double", "triple"):
                    cycle_deductions += g_mult_s * g_dr["final_rate"] + g_mult_s * g_charge_s
                elif s.status == "lunch_only":
                    cycle_deductions += g_mult_s * billing_helper._lunch_only_pct(s.status, s.date, c) * g_dr["final_rate"] + g_mult_s * g_charge_s
                elif s.status == "dinner_only":
                    cycle_deductions += g_mult_s * billing_helper._dinner_only_pct(s.status, s.date, c) * g_dr["final_rate"] + g_mult_s * g_charge_s
            elif current_user.free_meal:
                continue
            else:
                day_rates = billing_helper.get_daily_meal_rates(c, s.date, db)
                if s.status == "both":
                    cycle_deductions += day_rates["final_rate"] + mgr_rate
                elif s.status == "lunch_only":
                    cycle_deductions += (billing_helper._lunch_only_pct(s.status, s.date, c) * day_rates["final_rate"]) + mgr_rate
                elif s.status == "dinner_only":
                    cycle_deductions += (billing_helper._dinner_only_pct(s.status, s.date, c) * day_rates["final_rate"]) + mgr_rate
                elif s.status == "double":
                    cycle_deductions += (2 * day_rates["final_rate"]) + (2 * mgr_rate)
                elif s.status == "triple":
                    cycle_deductions += (3 * day_rates["final_rate"]) + (3 * mgr_rate)
        
    cycle_balance = round(cycle_deposits - cycle_deductions, 2)
    
    # Calculate remaining balance for current cycle only
    remaining_balance = cycle_balance
    if current_cycle and not current_user.free_meal:
        today_str = date.today().strftime("%Y-%m-%d")
        upcoming = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == current_user.id,
            models.StudentMealStatus.meal_cycle_id == current_cycle.id,
            models.StudentMealStatus.date >= today_str,
            models.StudentMealStatus.status != "off",
            models.StudentMealStatus.is_deducted == False
        ).all()
        if upcoming:
            rates = billing_helper.get_running_meal_rates(current_cycle, db)
            hall = db.query(models.Hall).filter(models.Hall.id == current_cycle.hall_id).first()
            mgr = hall.manager_charge_per_day if hall else 5.0
            projected = 0.0
            for m in upcoming:
                mgr, g_gr = billing_helper.get_daily_charges(current_cycle, m.date, db)
                if m.is_guest:
                    g_mult_m = billing_helper._meal_multiplier(m.status)
                    if m.status in ("both", "double", "triple"):
                        projected += g_mult_m * rates["final_rate"] + g_mult_m * g_gr
                    elif m.status == "lunch_only":
                        projected += g_mult_m * billing_helper._lunch_only_pct(m.status, m.date, current_cycle) * rates["final_rate"] + g_mult_m * g_gr
                    elif m.status == "dinner_only":
                        projected += g_mult_m * billing_helper._dinner_only_pct(m.status, m.date, current_cycle) * rates["final_rate"] + g_mult_m * g_gr
                else:
                    if m.status == "both":
                        projected += rates["final_rate"] + mgr
                    elif m.status == "lunch_only":
                        projected += (billing_helper._lunch_only_pct(m.status, m.date, current_cycle) * rates["final_rate"]) + mgr
                    elif m.status == "dinner_only":
                        projected += (billing_helper._dinner_only_pct(m.status, m.date, current_cycle) * rates["final_rate"]) + mgr
                    elif m.status == "double":
                        projected += (2 * rates["final_rate"]) + (2 * mgr)
                    elif m.status == "triple":
                        projected += (3 * rates["final_rate"]) + (3 * mgr)
            remaining_balance = round(cycle_balance - projected, 2)

    # Get user deposits for current cycle only
    cycle_for_deposits = current_cycle
    if not cycle_for_deposits:
        cycle_for_deposits = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.status.in_(["poll", "active"])
        ).order_by(models.MealCycle.month.desc()).first()
    deposits = []
    if cycle_for_deposits:
        deposits = db.query(models.Deposit).filter(
            models.Deposit.user_id == current_user.id,
            models.Deposit.meal_cycle_id == cycle_for_deposits.id
        ).order_by(models.Deposit.date.desc()).all()
    
    # Get user meal statuses for the next 7 days (including today)
    today = date.today()
    upcoming_dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(14)] # show 14 days
    
    # Check if home hall has active/polling cycle
    home_hall_active = False
    if current_user.hall_id:
        today_str = today.strftime("%Y-%m-%d")
        home_cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.start_date <= today_str,
            models.MealCycle.end_date >= today_str,
            models.MealCycle.status.in_(["poll", "active"])
        ).first()
        if not home_cycle:
            current_month = today.strftime("%Y-%m")
            home_cycle = db.query(models.MealCycle).filter(
                models.MealCycle.hall_id == current_user.hall_id,
                models.MealCycle.month == current_month,
                models.MealCycle.status.in_(["poll", "active"])
            ).first()
        if home_cycle:
            home_hall_active = True

    meal_statuses = {}
    created_any = False
    for d_str in upcoming_dates:
        statuses = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == current_user.id,
            models.StudentMealStatus.date == d_str
        ).all()
        
        status_rec = None
        # Prioritize active status (not 'off')
        for s in statuses:
            if s.status != "off":
                status_rec = s
                break
        if not status_rec and statuses:
            status_rec = statuses[0]
            
        if not status_rec:
            # Find cycle for this date to know where to add it
            cycle = db.query(models.MealCycle).filter(
                models.MealCycle.hall_id == current_user.hall_id,
                models.MealCycle.start_date <= d_str,
                models.MealCycle.end_date >= d_str
            ).first()
            if not cycle:
                # try month fallback
                cycle = db.query(models.MealCycle).filter(
                    models.MealCycle.hall_id == current_user.hall_id,
                    models.MealCycle.month == d_str[:7]
                ).first()
                
            if cycle and cycle.status != "closed":
                # Don't seed statuses for dates before cycle start
                if cycle.start_date and d_str < cycle.start_date:
                    continue
                status_str = current_user.status or "both"
                t_lunch = status_str in ["both", "lunch_only"]
                t_dinner = status_str in ["both", "dinner_only"]
                status_rec = models.StudentMealStatus(
                    user_id=current_user.id,
                    meal_cycle_id=cycle.id,
                    date=d_str,
                    status=status_str,
                    ticked_lunch=t_lunch,
                    ticked_dinner=t_dinner,
                    kept_lunch_for_dinner=False,
                    is_guest=False,
                    is_deducted=False,
                    amount_deducted=0.0
                )
                db.add(status_rec)
                created_any = True
        
        if status_rec:
            # Find target guest hall id
            target_hall_id = None
            if status_rec.is_guest:
                target_cycle = db.query(models.MealCycle).filter(models.MealCycle.id == status_rec.meal_cycle_id).first()
                if target_cycle:
                    target_hall_id = target_cycle.hall_id
            
            meal_statuses[d_str] = {
                "id": status_rec.id,
                "status": status_rec.status,
                "ticked_lunch": status_rec.ticked_lunch,
                "ticked_dinner": status_rec.ticked_dinner,
                "kept_lunch_for_dinner": status_rec.kept_lunch_for_dinner,
                "is_guest": status_rec.is_guest,
                "guest_from_hall_id": status_rec.guest_from_hall_id,
                "target_hall_id": target_hall_id
            }
        else:
            meal_statuses[d_str] = {
                "id": None,
                "status": "off",
                "ticked_lunch": False,
                "ticked_dinner": False,
                "kept_lunch_for_dinner": False,
                "is_guest": False,
                "guest_from_hall_id": None,
                "target_hall_id": None
            }
            
    if created_any:
        db.commit()
            
    # Get user's hall name
    hall_name = "None"
    guest_rate = 120.0
    cutoff_time = "20:00"
    
    if current_user.hall_id:
        hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
        if hall:
            hall_name = hall.name
            guest_rate = hall.guest_meal_rate
            
            # Find current active cycle for cutoff time
            current_month = today.strftime("%Y-%m")
            active_cycle_val = db.query(models.MealCycle).filter(
                models.MealCycle.hall_id == current_user.hall_id,
                models.MealCycle.month == current_month
            ).first()
            if active_cycle_val:
                cutoff_time = active_cycle_val.cutoff_time

    return {
        "user": {
            "name": current_user.name,
            "username": current_user.username,
            "role": current_user.role,
            "balance": cycle_balance,
            "raw_balance": current_user.balance,
            "room_number": current_user.room_number,
            "phone": current_user.phone,
            "hall_name": hall_name,
            "free_meal": current_user.free_meal,
            "egg_alternative": current_user.egg_alternative if hasattr(current_user, 'egg_alternative') else False,
            "prefer_beef": current_user.prefer_beef if hasattr(current_user, 'prefer_beef') else False,
            "prefer_mutton": current_user.prefer_mutton if hasattr(current_user, 'prefer_mutton') else False,
            "meal_preference": current_user.meal_preference or "normal",
            "fish_egg_pref": current_user.fish_egg_pref or "normal",
            "meat_pref": current_user.meat_pref or "normal"
        },
        "guest_rate": guest_rate,
        "cutoff_time": cutoff_time,
        "home_hall_active": home_hall_active,
        "total_deposits": cycle_deposits,
        "cycle_deductions": round(cycle_deductions, 2),
        "remaining_balance": remaining_balance,
        "deposits": [
            {"amount": d.amount, "date": d.date, "description": d.description} for d in deposits
        ],
        "meals": meal_statuses
    }

@router.post("/meal-status/toggle")
def toggle_meal_status(payload: schemas.MealStatusToggle, current_user: models.User = Depends(auth.require_roles(["student", "manager", "assistant_manager"])), db: Session = Depends(get_db)):
    check_feature_locked("meal_status", db)
    if not current_user.hall_id:
        raise HTTPException(status_code=400, detail="User is not associated with any Hall.")
        
    # Find cycle by date match or month fallback
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == current_user.hall_id,
        models.MealCycle.start_date <= payload.date,
        models.MealCycle.end_date >= payload.date
    ).first()
    
    if not cycle:
        target_month = payload.date[:7] # "YYYY-MM"
        cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.month == target_month
        ).first()
    
    if not cycle:
        raise HTTPException(status_code=400, detail=f"No dining cycle found for date {payload.date} in your hall.")
    
    if cycle.status == "closed":
        raise HTTPException(status_code=400, detail="The dining cycle for this month is closed.")
        
    # Check cutoff time
    if check_cutoff(payload.date, cycle.cutoff_time):
        raise HTTPException(status_code=400, detail=f"Meal status changes for this date are locked. Cutoff was {cycle.cutoff_time} previous evening.")
        
    # Find end date of cycle or last day of month and update all future dates in that cycle
    try:
        start_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")
        
    end_date = billing_helper.get_cycle_end_date(cycle)
    # Only carry forward for today/future dates; past dates affect only that specific day
    no_carry = (start_date < date.today())
    
    current = start_date
    updated_count = 0
    while current <= end_date:
        if no_carry and current != start_date:
            break
        d_str = current.strftime("%Y-%m-%d")
        status_rec = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == current_user.id,
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.date == d_str
        ).first()
        
        t_lunch = payload.status in ["both", "lunch_only", "double", "triple"]
        t_dinner = payload.status in ["both", "dinner_only", "double", "triple"]
        
        if not status_rec:
            status_rec = models.StudentMealStatus(
                user_id=current_user.id,
                meal_cycle_id=cycle.id,
                date=d_str,
                status=payload.status,
                ticked_lunch=t_lunch,
                ticked_dinner=t_dinner,
                is_guest=False,
                is_deducted=False,
                amount_deducted=0.0
            )
            db.add(status_rec)
        else:
            status_rec.status = payload.status
            status_rec.ticked_lunch = t_lunch
            status_rec.ticked_dinner = t_dinner
            
        current += timedelta(days=1)
        updated_count += 1
        
    # Deactivate any guest meals in other halls if activating home meals
    if payload.status != "off":
        db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == current_user.id,
            models.StudentMealStatus.is_guest == True,
            models.StudentMealStatus.date >= payload.date
        ).update({models.StudentMealStatus.status: "off"}, synchronize_session=False)
        
    db.commit()
    return {"message": f"Meal status updated to '{payload.status}' and carried forward for the rest of the month ({updated_count} days).", "date": payload.date, "status": payload.status}

@router.get("/halls")
def get_halls(db: Session = Depends(get_db)):
    halls = db.query(models.Hall).all()
    return halls

@router.post("/guest-meal/toggle")
def toggle_guest_meal(payload: schemas.MealStatusToggle, target_hall_id: int, current_user: models.User = Depends(auth.require_roles(["student", "manager", "assistant_manager"])), db: Session = Depends(get_db)):
    check_feature_locked("guest_switcher", db)
    if current_user.hall_id == target_hall_id:
        raise HTTPException(status_code=400, detail="Cannot join your own hall as a guest.")
        
    # Check if home hall has active/polling dining cycle
    today = date.today()
    current_month = today.strftime("%Y-%m")
    if current_user.hall_id:
        home_cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.month == current_month,
            models.MealCycle.status.in_(["poll", "active"])
        ).first()
        if home_cycle:
            raise HTTPException(status_code=400, detail="Cannot switch to guest meals when your home hall dining is active.")
        
    target_hall = db.query(models.Hall).filter(models.Hall.id == target_hall_id).first()
    if not target_hall:
        raise HTTPException(status_code=404, detail="Target hall not found.")
        
    target_month = payload.date[:7]
    cycle = db.query(models.MealCycle).filter(
        models.MealCycle.hall_id == target_hall_id,
        models.MealCycle.start_date <= payload.date,
        models.MealCycle.end_date >= payload.date
    ).first()
    
    if not cycle:
        cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == target_hall_id,
            models.MealCycle.month == target_month
        ).first()
    
    if not cycle or cycle.status == "closed":
        raise HTTPException(status_code=400, detail="Target hall has no active dining cycle for this month.")
        
    # Check target cutoff time
    if check_cutoff(payload.date, cycle.cutoff_time):
        raise HTTPException(status_code=400, detail=f"Cutoff passed for target hall ({cycle.cutoff_time}). Cannot toggle.")
        
    # Find end date of cycle or last day of month and update all future guest dates in that cycle
    try:
        start_date = datetime.strptime(payload.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")
        
    end_date = billing_helper.get_cycle_end_date(cycle)
    
    today = date.today()
    # Only carry forward for today/future dates; past dates affect only that specific day
    no_carry = (start_date < today)
    
    current = start_date
    updated_count = 0
    while current <= end_date:
        if no_carry and current != start_date:
            break
        d_str = current.strftime("%Y-%m-%d")
        status_rec = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == current_user.id,
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.date == d_str,
            models.StudentMealStatus.is_guest == True
        ).first()
        
        t_lunch = payload.status in ["both", "lunch_only", "double", "triple"]
        t_dinner = payload.status in ["both", "dinner_only", "double", "triple"]
        
        if not status_rec:
            status_rec = models.StudentMealStatus(
                user_id=current_user.id,
                meal_cycle_id=cycle.id,
                date=d_str,
                status=payload.status,
                ticked_lunch=t_lunch,
                ticked_dinner=t_dinner,
                is_guest=True,
                guest_from_hall_id=current_user.hall_id,
                is_deducted=False,
                amount_deducted=0.0
            )
            db.add(status_rec)
        else:
            status_rec.status = payload.status
            status_rec.ticked_lunch = t_lunch
            status_rec.ticked_dinner = t_dinner
            
        current += timedelta(days=1)
        updated_count += 1
        
    # Deactivate home meals if activating guest meals in other hall
    if payload.status != "off":
        home_cycle = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == current_user.hall_id,
            models.MealCycle.start_date <= payload.date,
            models.MealCycle.end_date >= payload.date
        ).first()
        if not home_cycle:
            home_cycle = db.query(models.MealCycle).filter(
                models.MealCycle.hall_id == current_user.hall_id,
                models.MealCycle.month == target_month
            ).first()
        if home_cycle:
            db.query(models.StudentMealStatus).filter(
                models.StudentMealStatus.user_id == current_user.id,
                models.StudentMealStatus.meal_cycle_id == home_cycle.id,
                models.StudentMealStatus.date >= payload.date
            ).update({models.StudentMealStatus.status: "off"}, synchronize_session=False)
        # Deactivate guest meals in any other halls
        db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == current_user.id,
            models.StudentMealStatus.meal_cycle_id != cycle.id,
            models.StudentMealStatus.date >= payload.date,
            models.StudentMealStatus.is_guest == True,
            models.StudentMealStatus.status != "off"
        ).update({models.StudentMealStatus.status: "off"}, synchronize_session=False)
        
    db.commit()
    return {"message": f"Guest meal status updated to '{payload.status}' and carried forward for the rest of the month ({updated_count} days).", "date": payload.date, "status": payload.status}

@router.get("/meal-logs")
def get_meal_logs(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    check_feature_locked("meal_history", db)
    # Run passed deductions first
    import billing_helper
    from datetime import date
    billing_helper.deduct_passed_meals(db)
    
    today_str = date.today().strftime("%Y-%m-%d")
    statuses = db.query(models.StudentMealStatus).filter(
        models.StudentMealStatus.user_id == current_user.id,
        models.StudentMealStatus.date <= today_str
    ).order_by(models.StudentMealStatus.date.desc()).all()
    
    # Never show rows dated after their cycle's end date (stale post-end rows)
    cycle_ends = {}
    filtered = []
    for s in statuses:
        end = cycle_ends.get(s.meal_cycle_id)
        if end is None:
            c = db.query(models.MealCycle).filter(models.MealCycle.id == s.meal_cycle_id).first()
            end = (c.end_date or "") if c else ""
            cycle_ends[s.meal_cycle_id] = end
        if end and s.date > end:
            continue
        filtered.append(s)
    statuses = filtered
    
    results = []
    for s in statuses:
        cycle = db.query(models.MealCycle).filter(models.MealCycle.id == s.meal_cycle_id).first()
        hall_name = "Home Hall"
        if s.is_guest:
            hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first() if cycle else None
            hall_name = hall.name if hall else "Guest Hall"
            
        # Recalculate current cost using up-to-date daily rates
        cost = s.amount_deducted if s.amount_deducted else 0.0
        if s.status != "off" and cycle:
            if s.is_guest:
                hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
                guest_rate = hall.guest_meal_rate if hall else 120.0
                weight = 1.0
                if s.status == "lunch_only":
                    weight = cycle.lunch_percentage
                elif s.status == "dinner_only":
                    weight = cycle.dinner_percentage
                cost = weight * guest_rate
            else:
                u = db.query(models.User).filter(models.User.id == current_user.id).first()
                if u and not u.free_meal:
                    import billing_helper
                    day_rates = billing_helper.get_daily_meal_rates(cycle, s.date, db)
                    hall = db.query(models.Hall).filter(models.Hall.id == cycle.hall_id).first()
                    mgr = hall.manager_charge_per_day if hall else 5.0
                    l_pct = cycle.lunch_only_rate_percentage or 0.4
                    d_pct = cycle.dinner_only_rate_percentage or 0.6
                    if s.status == "both":
                        cost = day_rates["final_rate"] + mgr
                    elif s.status == "lunch_only":
                        cost = (l_pct * day_rates["final_rate"]) + mgr
                    elif s.status == "dinner_only":
                        cost = (d_pct * day_rates["final_rate"]) + mgr
        
        results.append({
            "id": s.id,
            "date": s.date,
            "status": s.status,
            "is_guest": s.is_guest,
            "hall_name": hall_name,
            "is_deducted": s.is_deducted,
            "amount_deducted": round(cost, 2)
        })
        
    return results


@router.post("/bkash/webhook")
def bkash_webhook(payload: schemas.BkashWebhookPayload, db: Session = Depends(get_db)):
    WEBHOOK_SECRET = "edining_bkash_webhook_secret_2026"
    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret key.")
        
    import re
    text = payload.text
    
    # Try matching combined regex first
    combined_match = re.search(r"You have received send money (?:Tk|TK)\s*([\d\.,]+)\s+from\s+([0-9]+).*TrxID\s+([A-Z0-9]{10})", text, re.IGNORECASE)
    if combined_match:
        try:
            amount = float(combined_match.group(1).replace(",", ""))
            sender = combined_match.group(2)
            trx_id = combined_match.group(3).upper()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error parsing message fields: {str(e)}")
    else:
        # Fallback to individual matches
        amount_match = re.search(r"(?:Tk|TK)\s*([\d\.,]+)", text)
        sender_match = re.search(r"from\s+(01[3-9]\d{8})", text)
        trx_match = re.search(r"TrxID\s+([A-Z0-9]{10})", text, re.IGNORECASE)
        
        if not (amount_match and sender_match and trx_match):
            raise HTTPException(status_code=400, detail="Could not parse standard bKash Send Money message fields (Amount, Sender, TrxID).")
            
        try:
            amount = float(amount_match.group(1).replace(",", ""))
            sender = sender_match.group(1)
            trx_id = trx_match.group(1).upper()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error parsing message fields: {str(e)}")
        
    # Check if already exists to prevent duplicate insertion
    existing = db.query(models.BkashReceivedSms).filter(models.BkashReceivedSms.trx_id == trx_id).first()
    if existing:
        return {"status": "already_received", "trx_id": trx_id, "amount": amount}
        
    new_sms = models.BkashReceivedSms(
        trx_id=trx_id,
        sender=sender,
        amount=amount,
        raw_text=text,
        is_claimed=False,
        date_received=date.today().strftime("%Y-%m-%d")
    )
    db.add(new_sms)
    db.commit()
    return {"status": "success", "trx_id": trx_id, "amount": amount}


@router.post("/bkash/verify-trx")
def verify_bkash_trx(payload: schemas.BkashVerifyTrxRequest, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    check_feature_locked("deposit", db)
    trx_id_upper = payload.trx_id.strip().upper()
    if not trx_id_upper or len(trx_id_upper) < 5 or not trx_id_upper.isalnum():
        raise HTTPException(status_code=400, detail="Invalid Transaction ID format.")
        
    sms = db.query(models.BkashReceivedSms).filter(models.BkashReceivedSms.trx_id == trx_id_upper).first()
    
    if not sms:
        # TrxID not found — create a pending record for manager approval
        sms = models.BkashReceivedSms(
            trx_id=trx_id_upper,
            sender=current_user.username,
            amount=0.0,
            raw_text="Manual claim by " + current_user.username,
            status="pending",
            is_claimed=True,
            claimed_by_user_id=current_user.id,
            date_received=date.today().strftime("%Y-%m-%d")
        )
        db.add(sms)
        db.commit()
        return {"status": "pending", "trx_id": trx_id_upper, "message": "Transaction submitted for manager approval.", "immediate": False}
    
    if sms.is_claimed:
        raise HTTPException(status_code=400, detail="Transaction ID has already been claimed.")
    
    # TrxID found — immediately credit the user
    sms.is_claimed = True
    sms.claimed_by_user_id = current_user.id
    sms.status = "approved"
    sms.approved_amount = sms.amount
    
    current_user.balance += sms.amount
    
    # Create deposit record in the running cycle (any status, incl. auto-closed)
    cycle = billing_helper.get_latest_cycle(db, current_user.hall_id)
    if cycle:
        dep = models.Deposit(
            user_id=current_user.id, meal_cycle_id=cycle.id,
            amount=sms.amount, date=date.today().strftime("%Y-%m-%d"),
            description="bKash Send Money (TrxID: " + trx_id_upper + ")"
        )
        db.add(dep)
    
    db.commit()
    return {"status": "success", "trx_id": trx_id_upper, "amount": sms.amount, "message": f"BDT {sms.amount:.2f} deposited successfully.", "immediate": True}


