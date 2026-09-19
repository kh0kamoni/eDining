import sys
sys.path.insert(0, '/app')
from database import SessionLocal
import models
from datetime import date
from sqlalchemy import func

today_str = date.today().strftime("%Y-%m-%d")
db = SessionLocal()

cycle = db.query(models.MealCycle).filter(
    models.MealCycle.hall_id == 1,
    models.MealCycle.status == "active"
).first()

if not cycle:
    print("No active cycle")
else:
    print("Cycle %d: %s to %s" % (cycle.id, cycle.start_date, cycle.end_date))

    counts = db.query(
        models.StudentMealStatus.user_id,
        func.count(models.StudentMealStatus.id)
    ).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id,
        models.StudentMealStatus.date <= today_str
    ).group_by(models.StudentMealStatus.user_id).all()

    print("\nUsers with status records <= %s:" % today_str)
    for uid, cnt in counts:
        u = db.query(models.User).filter(models.User.id == uid).first()
        name = u.username if u else "?"
        print("  %s (id=%d): %d records" % (name, uid, cnt))

    all_uids = db.query(models.StudentMealStatus.user_id).filter(
        models.StudentMealStatus.meal_cycle_id == cycle.id
    ).distinct().all()
    all_uids = [u[0] for u in all_uids]
    print("\nAll users in cycle: %d" % len(all_uids))
    for uid in all_uids:
        total = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.user_id == uid
        ).count()
        past = db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.user_id == uid,
            models.StudentMealStatus.date <= today_str
        ).count()
        u = db.query(models.User).filter(models.User.id == uid).first()
        name = u.username if u else "?"
        print("  %s: total=%d, past=%d" % (name, total, past))

db.close()
