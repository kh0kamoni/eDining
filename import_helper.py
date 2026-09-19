import os
import openpyxl
import datetime
import models
import auth
from sqlalchemy.orm import Session

def import_manual_data(db: Session):
    # Check if manual data is already imported in main tables to avoid double seeding
    if db.query(models.Deposit).filter(models.Deposit.description == "Manual Excel Deposit").count() > 0:
        print("Manual Excel data already imported in main tables. Skipping seeding.")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(base_dir, "old_data", "data.xlsx")
    if not os.path.exists(filepath):
        print(f"Notice: Excel data file not found at {filepath}. Skipping.")
        return

    print(f"Starting import of manual Excel data from {filepath}...")
    
    # Load workbook
    wb = openpyxl.load_workbook(filepath, data_only=True)
    
    # 1. Parse Users sheet for rooms, names, and status
    sheet_users = wb["Users"]
    users_status = {}
    rows_users = list(sheet_users.iter_rows(values_only=True))
    for row in rows_users[1:]:
        room = row[0]
        if room is None:
            continue
        room_str = str(int(room)) if isinstance(room, (int, float)) else str(room).strip()
        
        # Blocks of 4: name is col_idx, status is col_idx + 3
        col_idx = 1
        while col_idx < len(row):
            name = row[col_idx]
            if name is not None and str(name).strip() != "":
                status = row[col_idx + 3] if col_idx + 3 < len(row) else None
                key = (room_str, str(name).strip().lower())
                users_status[key] = {
                    "name": str(name).strip(),
                    "room": room_str,
                    "status": str(status).strip() if status else "Off"
                }
            col_idx += 4

    # 2. Parse Meals sheet for lunch and dinner counts
    sheet_meals = wb["Meals"]
    users_meals = {}
    rows_meals = list(sheet_meals.iter_rows(values_only=True))
    for row in rows_meals[1:]:
        room = row[0]
        if room is None:
            continue
        room_str = str(int(room)) if isinstance(room, (int, float)) else str(room).strip()
        
        col_idx = 1
        while col_idx < len(row):
            name = row[col_idx]
            if name is not None and str(name).strip() != "":
                lunch = row[col_idx + 1] if col_idx + 1 < len(row) else 0
                dinner = row[col_idx + 2] if col_idx + 2 < len(row) else 0
                key = (room_str, str(name).strip().lower())
                users_meals[key] = {
                    "lunch": float(lunch) if lunch is not None else 0.0,
                    "dinner": float(dinner) if dinner is not None else 0.0
                }
            col_idx += 3

    # 3. Parse Rates and Costs sheet for deposits, costs, and give_take
    sheet_rates = wb["Rates and Costs"]
    users_rates = {}
    rows_rates = list(sheet_rates.iter_rows(values_only=True))
    for row in rows_rates[1:]:
        room = row[0]
        if room is None:
            continue
        room_str = str(int(room)) if isinstance(room, (int, float)) else str(room).strip()
        
        col_idx = 1
        while col_idx < len(row):
            name = row[col_idx]
            if name is not None and str(name).strip() != "":
                deposits = row[col_idx + 1] if col_idx + 1 < len(row) else 0
                costs = row[col_idx + 2] if col_idx + 2 < len(row) else 0
                give_take = row[col_idx + 3] if col_idx + 3 < len(row) else 0
                
                # Check for empty strings in costs/deposits
                costs_val = 0.0
                if costs is not None and str(costs).strip() != "":
                    try:
                        costs_val = float(costs)
                    except ValueError:
                        pass
                
                key = (room_str, str(name).strip().lower())
                users_rates[key] = {
                    "deposits": float(deposits) if deposits is not None else 0.0,
                    "costs": costs_val,
                    "give_take": float(give_take) if give_take is not None else 0.0
                }
            col_idx += 4

    # Merge into a single master user list
    all_keys = set(users_status.keys()) | set(users_meals.keys()) | set(users_rates.keys())
    print(f"Aggregated {len(all_keys)} manual users from Excel.")

    # Get Muktijoddha Hall (hall_id = 1)
    hall = db.query(models.Hall).filter(models.Hall.id == 1).first()
    if not hall:
        hall = models.Hall(name="Muktijoddha Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        db.add(hall)
        db.commit()
        db.refresh(hall)

    # Get or create active cycle 1
    cycle = db.query(models.MealCycle).filter(models.MealCycle.id == 1).first()
    if not cycle:
        cycle = models.MealCycle(
            id=1,
            hall_id=hall.id,
            month="2026-06",
            status="active",
            start_date="2026-06-13",
            end_date="2026-06-30"
        )
        db.add(cycle)
        db.commit()
        db.refresh(cycle)
    else:
        cycle.start_date = "2026-06-13"
        cycle.end_date = "2026-06-30"
        db.commit()

    # 4. Clean any existing seeding in main tables
    excel_usernames = {f"{k[1]}{k[0]}" for k in all_keys}
    excel_users = db.query(models.User).filter(models.User.username.in_(excel_usernames)).all()
    excel_user_ids = [u.id for u in excel_users]
    
    if excel_user_ids:
        db.query(models.Deposit).filter(
            models.Deposit.user_id.in_(excel_user_ids),
            models.Deposit.description == "Manual Excel Deposit"
        ).delete(synchronize_session=False)
        
        db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id.in_(excel_user_ids),
            models.StudentMealStatus.date.in_([
                "2026-06-13", "2026-06-14", "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18",
                "2026-06-19", "2026-06-20", "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-24",
                "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30"
            ])
        ).delete(synchronize_session=False)
        
    db.query(models.Expense).filter(
        models.Expense.meal_cycle_id == cycle.id,
        models.Expense.description.like("Manual Excel Bazar:%")
    ).delete(synchronize_session=False)
    
    # Also clean helper tables to keep them in sync
    db.query(models.ManualUserRecord).delete()
    db.query(models.ManualDailyRate).delete()
    db.query(models.ManualShoppingItem).delete()
    db.commit()

    # 5. Parse and insert Shopping daily items (expenses table and manual_shopping_items)
    sheet_shopping = wb["Shopping"]
    rows_shopping = list(sheet_shopping.iter_rows(values_only=True))
    
    rates_count = 0
    for r in rows_shopping[1:]:
        dt = r[12]
        if dt is not None:
            if str(dt).strip().lower() == "total":
                continue
            
            if isinstance(dt, (datetime.datetime, datetime.date)):
                date_str = dt.strftime("%Y-%m-%d")
            else:
                date_str = str(dt).strip()
                
            lunch_cost = r[13]
            dinner_cost = r[14]
            lunch_meals = r[16]
            dinner_meals = r[17]
            lunch_rate = r[18]
            dinner_rate = r[19]
            total_rate = r[20]
            
            def safe_float(val):
                if val is None or str(val).strip() == "" or str(val).startswith("#"):
                    return 0.0
                try:
                    return float(val)
                except ValueError:
                    return 0.0
            
            daily_rate = models.ManualDailyRate(
                date=date_str,
                lunch_cost=safe_float(lunch_cost),
                dinner_cost=safe_float(dinner_cost),
                lunch_meals=safe_float(lunch_meals),
                dinner_meals=safe_float(dinner_meals),
                lunch_rate=safe_float(lunch_rate),
                dinner_rate=safe_float(dinner_rate),
                total_rate=safe_float(total_rate)
            )
            db.add(daily_rate)
            rates_count += 1
            
    shopping_count = 0
    current_date = None
    for r in rows_shopping[1:]:
        dt = r[0]
        if dt is not None:
            if isinstance(dt, (datetime.datetime, datetime.date)):
                current_date = dt.strftime("%Y-%m-%d")
            else:
                current_date = str(dt).strip()
                
        if current_date is not None:
            lunch_desc = r[1]
            lunch_cost = r[2]
            if lunch_cost is not None and float(lunch_cost) > 0:
                try: cost_val = float(lunch_cost)
                except ValueError: cost_val = 0.0
                
                desc = str(lunch_desc).strip() if lunch_desc else (str(r[3]).strip() if r[3] else "Lunch Bazar")
                
                db.add(models.Expense(
                    meal_cycle_id=cycle.id,
                    date=current_date,
                    description=f"Manual Excel Bazar: Lunch - {desc}",
                    amount=cost_val,
                    meal_type="lunch"
                ))
                
                shopping_item = models.ManualShoppingItem(
                    date=current_date,
                    meal_type="lunch",
                    description=desc,
                    cost=cost_val
                )
                db.add(shopping_item)
                shopping_count += 1
                
            dinner_desc = r[3]
            dinner_cost = r[4]
            if dinner_cost is not None and float(dinner_cost) > 0:
                try: cost_val = float(dinner_cost)
                except ValueError: cost_val = 0.0
                
                desc = str(dinner_desc).strip() if dinner_desc else (str(r[1]).strip() if r[1] else "Dinner Bazar")
                
                db.add(models.Expense(
                    meal_cycle_id=cycle.id,
                    date=current_date,
                    description=f"Manual Excel Bazar: Dinner - {desc}",
                    amount=cost_val,
                    meal_type="dinner"
                ))
                
                shopping_item = models.ManualShoppingItem(
                    date=current_date,
                    meal_type="dinner",
                    description=desc,
                    cost=cost_val
                )
                db.add(shopping_item)
                shopping_count += 1
                
    db.commit()

    # 6. Add/link users in the database, deposits, and meal statuses
    db_users_created = 0
    db_users_updated = 0
    deposit_seeded_count = 0
    status_seeded_count = 0
    
    dates_list = ["2026-06-13", "2026-06-14", "2026-06-15", "2026-06-16", "2026-06-17"]
    future_dates = ["2026-06-18", "2026-06-19", "2026-06-20", "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30"]
    
    for key in all_keys:
        room_str, name_lower = key
        status_info = users_status.get(key, {})
        meals_info = users_meals.get(key, {})
        rates_info = users_rates.get(key, {})
        
        name = status_info.get("name") or rates_info.get("name") or name_lower.capitalize()
        status = status_info.get("status", "Off")
        lunch = meals_info.get("lunch", 0.0)
        dinner = meals_info.get("dinner", 0.0)
        deposits = rates_info.get("deposits", 0.0)
        costs = rates_info.get("costs", 0.0)
        give_take = rates_info.get("give_take", 0.0)
        
        username = f"{name_lower}{room_str}"
        
        expected_status = "off"
        ticked_lunch_val = False
        ticked_dinner_val = False
        if status == "On":
            expected_status = "both"
            ticked_lunch_val = True
            ticked_dinner_val = True
        elif status == "Lunch":
            expected_status = "lunch_only"
            ticked_lunch_val = True
            
        # Check if user already exists
        user = db.query(models.User).filter(models.User.username == username).first()
        if not user:
            hashed_pw = auth.get_password_hash(username)
            user = models.User(
                username=username,
                password_hash=hashed_pw,
                role="student",
                hall_id=hall.id,
                room_number=room_str,
                name=name,
                balance=give_take,
                free_meal=False,
                status=expected_status
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            db_users_created += 1
        else:
            user.balance = give_take
            user.status = expected_status
            db.commit()
            db_users_updated += 1
            
        # Create ManualUserRecord helper table entry
        manual_rec = models.ManualUserRecord(
            user_id=user.id,
            name=name,
            room=room_str,
            status=status,
            lunch_meals=lunch,
            dinner_meals=dinner,
            deposits=deposits,
            costs=costs,
            give_take=give_take
        )
        db.add(manual_rec)
        
        # Seed deposit if > 0 in deposits table
        if deposits > 0:
            new_dep = models.Deposit(
                user_id=user.id,
                meal_cycle_id=cycle.id,
                amount=deposits,
                date="2026-06-13",
                description="Manual Excel Deposit"
            )
            db.add(new_dep)
            deposit_seeded_count += 1
            
        # Distribute daily meal statuses (past dates)
        # Use cycle's lunch/dinner percentages for cost distribution
        lunch_w = cycle.lunch_percentage if cycle else 0.5
        dinner_w = cycle.dinner_percentage if cycle else 0.5
        total_calculated = (lunch * lunch_w) + (dinner * dinner_w)
        for i, d_str in enumerate(dates_list):
            has_lunch = (i < lunch)
            has_dinner = (i < dinner)
            
            status_str = "off"
            if has_lunch and has_dinner: status_str = "both"
            elif has_lunch: status_str = "lunch_only"
            elif has_dinner: status_str = "dinner_only"
            
            daily_calc = (lunch_w if has_lunch else 0.0) + (dinner_w if has_dinner else 0.0)
            
            amount_deducted = 0.0
            if status_str != "off" and total_calculated > 0:
                amount_deducted = (daily_calc / total_calculated) * costs
                
            status_rec = models.StudentMealStatus(
                user_id=user.id,
                meal_cycle_id=cycle.id,
                date=d_str,
                status=status_str,
                ticked_lunch=has_lunch,
                ticked_dinner=has_dinner,
                kept_lunch_for_dinner=False,
                is_guest=False,
                is_deducted=True,
                amount_deducted=round(amount_deducted, 2)
            )
            db.add(status_rec)
            status_seeded_count += 1

        # Seed future statuses according to default status

        for d_str in future_dates:
            status_rec = models.StudentMealStatus(
                user_id=user.id,
                meal_cycle_id=cycle.id,
                date=d_str,
                status=expected_status,
                ticked_lunch=ticked_lunch_val,
                ticked_dinner=ticked_dinner_val,
                kept_lunch_for_dinner=False,
                is_guest=False,
                is_deducted=False,
                amount_deducted=0.0
            )
            db.add(status_rec)
            status_seeded_count += 1

    db.commit()
    
    # Ensure all students in Muktijoddha Hall (hall_id = 1) have statuses for the entire cycle
    all_dates = dates_list + future_dates
    hall_students = db.query(models.User).filter(
        models.User.hall_id == 1,
        models.User.role == "student"
    ).all()
    
    extra_status_count = 0
    for student in hall_students:
        status_str = student.status or "both"
        t_lunch = status_str in ["both", "lunch_only"]
        t_dinner = status_str in ["both", "dinner_only"]
        
        for d_str in all_dates:
            existing_rec = db.query(models.StudentMealStatus).filter(
                models.StudentMealStatus.user_id == student.id,
                models.StudentMealStatus.meal_cycle_id == cycle.id,
                models.StudentMealStatus.date == d_str
            ).first()
            
            if not existing_rec:
                db.add(models.StudentMealStatus(
                    user_id=student.id,
                    meal_cycle_id=cycle.id,
                    date=d_str,
                    status=status_str,
                    ticked_lunch=t_lunch,
                    ticked_dinner=t_dinner,
                    kept_lunch_for_dinner=False,
                    is_guest=False,
                    is_deducted=False,
                    amount_deducted=0.0
                ))
                extra_status_count += 1
                
    db.commit()
    print(f"Seeded {extra_status_count} extra student meal statuses for hall 1.")
    print(f"Created {db_users_created} and updated {db_users_updated} student accounts.")
    print(f"Seeded {deposit_seeded_count} deposits and {status_seeded_count + extra_status_count} meal statuses.")
    print(f"Seeded {rates_count} daily rates in 'manual_daily_rates' table.")
    print(f"Seeded {shopping_count} shopping items in 'manual_shopping_items' table.")
    print("Excel import completed successfully!")


def import_halls_from_csv(db: Session, filepath: str = None) -> int:
    """
    Imports dining halls from a CSV file into the database.
    Skips halls that already exist.
    """
    import csv

    if not filepath:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(base_dir, "halls.csv")

    if not os.path.exists(filepath):
        print(f"Notice: halls.csv file not found at {filepath}. Skipping halls import.")
        return 0

    print(f"Starting import of halls from {filepath}...")
    imported_count = 0
    skipped_count = 0

    try:
        with open(filepath, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    continue

                existing = db.query(models.Hall).filter(models.Hall.name.ilike(name)).first()
                if existing:
                    skipped_count += 1
                    continue

                try:
                    guest_rate = float(row.get("guest_meal_rate", 120.0) or 120.0)
                except (ValueError, TypeError):
                    guest_rate = 120.0

                try:
                    mgr_charge = float(row.get("manager_charge_per_day", 5.0) or 5.0)
                except (ValueError, TypeError):
                    mgr_charge = 5.0

                try:
                    guest_charge = float(row.get("guest_charge_per_day", 5.0) or 5.0)
                except (ValueError, TypeError):
                    guest_charge = 5.0

                hall = models.Hall(
                    name=name,
                    guest_meal_rate=guest_rate,
                    manager_charge_per_day=mgr_charge,
                    guest_charge_per_day=guest_charge
                )
                db.add(hall)
                imported_count += 1

            db.commit()
            print(f"Halls CSV import completed: {imported_count} imported, {skipped_count} skipped.")
            return imported_count
    except Exception as e:
        db.rollback()
        print(f"Error during halls.csv import: {e}")
        return 0


def import_users_from_csv(db: Session, filepath: str = None) -> int:
    """
    Imports users from a CSV file into the database on first-time setup.
    Creates any referenced halls if they don't already exist.
    Preserves bcrypt password hashes or generates new ones if plaintext.
    Skips users that already exist in the database.
    """
    import csv

    if not filepath:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(base_dir, "users.csv")

    if not os.path.exists(filepath):
        print(f"Notice: users.csv file not found at {filepath}. Skipping CSV import.")
        return 0

    print(f"Starting import of users from {filepath}...")
    imported_count = 0
    skipped_count = 0

    try:
        with open(filepath, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            halls_cache = {h.name.lower(): h for h in db.query(models.Hall).all()}

            for row in reader:
                username = (row.get("username") or "").strip()
                if not username:
                    continue

                existing = db.query(models.User).filter(models.User.username == username).first()
                if existing:
                    skipped_count += 1
                    continue

                # Hall resolution
                hall_id = None
                hall_name = (row.get("hall_name") or "").strip()
                if hall_name:
                    hall_key = hall_name.lower()
                    if hall_key not in halls_cache:
                        new_hall = models.Hall(
                            name=hall_name,
                            guest_meal_rate=120.0,
                            manager_charge_per_day=5.0,
                            guest_charge_per_day=5.0
                        )
                        db.add(new_hall)
                        db.commit()
                        db.refresh(new_hall)
                        halls_cache[hall_key] = new_hall
                    hall_id = halls_cache[hall_key].id

                # Password hash resolution
                raw_pwd = (row.get("password_hash") or row.get("password") or username).strip()
                if raw_pwd.startswith(("$2b$", "$2a$")):
                    pwd_hash = raw_pwd
                else:
                    pwd_hash = auth.get_password_hash(raw_pwd)

                def _parse_bool(val):
                    return str(val).strip().lower() in ["1", "true", "t", "yes"]

                try:
                    balance_val = float(row.get("balance", 0.0) or 0.0)
                except (ValueError, TypeError):
                    balance_val = 0.0

                user = models.User(
                    username=username,
                    password_hash=pwd_hash,
                    role=(row.get("role") or "student").strip(),
                    hall_id=hall_id,
                    room_number=(row.get("room_number") or "").strip() or None,
                    name=(row.get("name") or username).strip(),
                    phone=(row.get("phone") or "").strip() or None,
                    email=(row.get("email") or "").strip() or None,
                    balance=balance_val,
                    free_meal=_parse_bool(row.get("free_meal", 0)),
                    status=(row.get("status") or "both").strip() or "both",
                    egg_alternative=_parse_bool(row.get("egg_alternative", 0)),
                    prefer_beef=_parse_bool(row.get("prefer_beef", 0)),
                    prefer_mutton=_parse_bool(row.get("prefer_mutton", 0)),
                    meal_preference=(row.get("meal_preference") or "normal").strip(),
                    fish_egg_pref=(row.get("fish_egg_pref") or "normal").strip(),
                    meat_pref=(row.get("meat_pref") or "normal").strip()
                )
                db.add(user)
                imported_count += 1

            db.commit()
            print(f"Users CSV import completed: {imported_count} imported, {skipped_count} skipped.")
            return imported_count
    except Exception as e:
        db.rollback()
        print(f"Error during users.csv import: {e}")
        return 0


if __name__ == "__main__":
    import sys
    from database import SessionLocal
    db_session = SessionLocal()
    target_csv = sys.argv[1] if len(sys.argv) > 1 else None
    import_users_from_csv(db_session, target_csv)
    db_session.close()

