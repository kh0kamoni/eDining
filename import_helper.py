import os
import csv
from sqlalchemy.orm import Session
import models
import auth

def import_halls_from_csv(db: Session, filepath: str = None) -> int:
    """
    Imports dining halls from a CSV file into the database.
    Skips halls that already exist.
    """
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
