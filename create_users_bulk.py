import sys
sys.path.insert(0, '/app')
from database import SessionLocal
import models
import auth
import urllib.request, json

# Read user list
with open('/app/bulk_users.txt', 'r') as f:
    usernames = [line.strip() for line in f if line.strip()]

db = SessionLocal()

# Get hall_id=1 (Muktijoddha Hall) - default hall
hall = db.query(models.Hall).filter(models.Hall.id == 1).first()
if not hall:
    print("Hall 1 not found!")
    db.close()
    sys.exit(1)

created = 0
skipped = 0
for username in usernames:
    existing = db.query(models.User).filter(models.User.username == username).first()
    if existing:
        skipped += 1
        continue
    # Extract room from username (last underscore part)
    parts = username.rsplit('_', 1)
    name = parts[0].title() if len(parts) > 1 else username
    room = parts[1] if len(parts) > 1 else ''
    
    user = models.User(
        username=username,
        password_hash=auth.get_password_hash(username),
        role='student',
        hall_id=hall.id,
        room_number=room,
        name=name,
        balance=0.0,
        free_meal=False,
        status='both'
    )
    db.add(user)
    created += 1
    if created % 50 == 0:
        db.commit()
        print(f"  Created {created}...")

db.commit()
print(f"\nDone: {created} created, {skipped} skipped (already exist)")
print(f"Total users now: {db.query(models.User).count()}")

# Seed meal statuses for active cycle
active_cycle = db.query(models.MealCycle).filter(
    models.MealCycle.hall_id == 1,
    models.MealCycle.status == 'active'
).first()
if active_cycle:
    import billing_helper
    dates = billing_helper.get_cycle_dates(active_cycle, restrict_to_today=False)
    seeded = 0
    for username in usernames:
        u = db.query(models.User).filter(models.User.username == username).first()
        if not u:
            continue
        for d_str in dates:
            exists = db.query(models.StudentMealStatus).filter(
                models.StudentMealStatus.user_id == u.id,
                models.StudentMealStatus.meal_cycle_id == active_cycle.id,
                models.StudentMealStatus.date == d_str
            ).first()
            if not exists:
                db.add(models.StudentMealStatus(
                    user_id=u.id,
                    meal_cycle_id=active_cycle.id,
                    date=d_str,
                    status='both',
                    ticked_lunch=True,
                    ticked_dinner=True,
                    kept_lunch_for_dinner=False,
                    is_guest=False
                ))
                seeded += 1
    db.commit()
    print(f"Seeded {seeded} meal status records for active cycle ({active_cycle.month})")

db.close()
