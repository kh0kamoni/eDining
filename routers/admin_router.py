from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
import auth
from typing import Any, Dict, List
import json
from datetime import date
import billing_helper

router = APIRouter(prefix="/admin", tags=["Superadmin Panel"])

FEATURES = [
    "deposit", "meal_status", "calendar", "profile", "edit_profile",
    "balance_view", "rate_logs", "deposit_logs", "meal_history", "hall_details", "guest_switcher",
    "signup",
    "transparency_daily_rate", "transparency_daily_expense", "transparency_meal_count", "transparency_daily_charge"
]

def get_feature_cfg(key: str, db: Session, default: str = ""):
    row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
    return row.value if row else default

def check_feature_locked(feature: str, db: Session):
    """Check if a feature is hidden or locked. Raises HTTPException if blocked."""
    hidden = get_feature_cfg(f"feature_{feature}_hidden", db, "false") == "true"
    locked = get_feature_cfg(f"feature_{feature}_locked", db, "false") == "true"
    enabled = get_feature_cfg(f"feature_{feature}_enabled", db, "true") == "true"
    if not enabled or hidden or locked:
        msg = get_feature_cfg(f"feature_{feature}_message", db, "This feature is currently disabled.")
        raise HTTPException(status_code=403, detail=msg)

def set_feature_cfg(key: str, val: str, db: Session):
    row = db.query(models.AppConfig).filter(models.AppConfig.key == key).first()
    if row:
        row.value = val
    else:
        db.add(models.AppConfig(key=key, value=val))

@router.get("/features")
def list_features(current_user: models.User = Depends(auth.require_roles(["superadmin"])), db: Session = Depends(get_db)):
    result = []
    for f in FEATURES:
        result.append({
            "name": f,
            "enabled": get_feature_cfg(f"feature_{f}_enabled", db, "true") == "true",
            "locked": get_feature_cfg(f"feature_{f}_locked", db, "false") == "true",
            "hidden": get_feature_cfg(f"feature_{f}_hidden", db, "false") == "true",
            "message": get_feature_cfg(f"feature_{f}_message", db, "")
        })
    return result

@router.post("/features/{feature_name}")
def update_feature(feature_name: str, enabled: bool = True, locked: bool = False, hidden: bool = False, message: str = "", current_user: models.User = Depends(auth.require_roles(["superadmin"])), db: Session = Depends(get_db)):
    if feature_name not in FEATURES:
        raise HTTPException(status_code=404, detail="Unknown feature")
    set_feature_cfg(f"feature_{feature_name}_enabled", "true" if enabled else "false", db)
    set_feature_cfg(f"feature_{feature_name}_locked", "true" if locked else "false", db)
    set_feature_cfg(f"feature_{feature_name}_hidden", "true" if hidden else "false", db)
    set_feature_cfg(f"feature_{feature_name}_message", message, db)
    db.commit()
    return {"message": f"Feature '{feature_name}' updated."}

@router.get("/features/student-check")
def get_student_feature_states(db: Session = Depends(get_db)):
    result = {}
    for f in FEATURES:
        result[f] = {
            "enabled": get_feature_cfg(f"feature_{f}_enabled", db, "true") == "true",
            "locked": get_feature_cfg(f"feature_{f}_locked", db, "false") == "true",
            "hidden": get_feature_cfg(f"feature_{f}_hidden", db, "false") == "true",
            "message": get_feature_cfg(f"feature_{f}_message", db, "")
        }
    return result

MODELS_MAP = {
    "halls": models.Hall,
    "users": models.User,
    "meal_cycles": models.MealCycle,
    "student_meal_statuses": models.StudentMealStatus,
    "deposits": models.Deposit,
    "expenses": models.Expense
}

def get_columns_meta(model_class):
    columns = []
    for column in model_class.__table__.columns:
        columns.append({
            "name": column.name,
            "type": str(column.type),
            "primary_key": column.primary_key,
            "nullable": column.nullable,
            "default": str(column.default) if column.default else None
        })
    return columns

@router.get("/tables")
def list_tables(current_user: models.User = Depends(auth.require_roles(["superadmin"]))):
    tables = []
    for tablename, model_class in MODELS_MAP.items():
        tables.append({
            "name": tablename,
            "columns": get_columns_meta(model_class)
        })
    return tables

@router.get("/tables/{table_name}")
def get_table_data(table_name: str, search: str = "", current_user: models.User = Depends(auth.require_roles(["superadmin"])), db: Session = Depends(get_db)):
    if table_name not in MODELS_MAP:
        raise HTTPException(status_code=404, detail="Table not found")
    
    model = MODELS_MAP[table_name]
    query = db.query(model)
    
    # Generic search filter based on string columns
    if search:
        filters = []
        for col in model.__table__.columns:
            if str(col.type).startswith("VARCHAR") or str(col.type).startswith("TEXT") or str(col.type).startswith("String"):
                filters.append(col.ilike(f"%{search}%"))
        if filters:
            from sqlalchemy import or_
            query = query.filter(or_(*filters))
            
    rows = query.all()
    
    # Convert rows to serializable dicts
    serialized = []
    for r in rows:
        row_dict = {}
        for col in model.__table__.columns:
            val = getattr(r, col.name)
            # handle serialization of dates/times if necessary
            if val is not None and not isinstance(val, (int, float, str, bool)):
                val = str(val)
            row_dict[col.name] = val
        serialized.append(row_dict)
        
    return {
        "columns": get_columns_meta(model),
        "rows": serialized
    }

@router.post("/tables/{table_name}")
def create_row(table_name: str, payload: dict, current_user: models.User = Depends(auth.require_roles(["superadmin"])), db: Session = Depends(get_db)):
    if table_name not in MODELS_MAP:
        raise HTTPException(status_code=404, detail="Table not found")
        
    model = MODELS_MAP[table_name]
    
    # Custom password hashing for users
    if table_name == "users" and "password" in payload:
        payload["password_hash"] = auth.get_password_hash(payload["password"])
        del payload["password"]
    elif table_name == "users" and "password_hash" not in payload and "password" not in payload:
        payload["password_hash"] = auth.get_password_hash("password123") # default password
        
    # Clean payload of non-existing columns
    valid_cols = {col.name for col in model.__table__.columns}
    insert_data = {k: v for k, v in payload.items() if k in valid_cols and k != "id"}
    
    try:
        new_row = model(**insert_data)
        db.add(new_row)
        db.commit()
        db.refresh(new_row)
        return {"message": "Row created successfully", "id": getattr(new_row, "id", None)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")

@router.put("/tables/{table_name}/{row_id}")
def update_row(table_name: str, row_id: int, payload: dict, current_user: models.User = Depends(auth.require_roles(["superadmin"])), db: Session = Depends(get_db)):
    if table_name not in MODELS_MAP:
        raise HTTPException(status_code=404, detail="Table not found")
        
    model = MODELS_MAP[table_name]
    row = db.query(model).filter(model.id == row_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")
        
    # Custom password hashing
    if table_name == "users" and payload.get("password"):
        row.password_hash = auth.get_password_hash(payload["password"])
        del payload["password"]
        
    valid_cols = {col.name for col in model.__table__.columns}
    for k, v in payload.items():
        if k in valid_cols and k != "id":
            setattr(row, k, v)
            
    try:
        db.commit()
        return {"message": "Row updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")

@router.delete("/tables/{table_name}/{row_id}")
def delete_row(table_name: str, row_id: int, current_user: models.User = Depends(auth.require_roles(["superadmin"])), db: Session = Depends(get_db)):
    if table_name not in MODELS_MAP:
        raise HTTPException(status_code=404, detail="Table not found")
        
    model = MODELS_MAP[table_name]
    row = db.query(model).filter(model.id == row_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")
        
    # Special handling for meal_cycles: reset affected users to fresh defaults
    if table_name == "meal_cycles" and isinstance(row, models.MealCycle):
        _reset_cycle_users(row.id, db)

    try:
        db.delete(row)
        db.commit()
        return {"message": "Row deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")


def _reset_cycle_users(cycle_id: int, db: Session):
    status_users = db.query(models.StudentMealStatus.user_id).filter(
        models.StudentMealStatus.meal_cycle_id == cycle_id
    ).distinct().all()
    user_ids = {u[0] for u in status_users}
    deposit_users = db.query(models.Deposit.user_id).filter(
        models.Deposit.meal_cycle_id == cycle_id
    ).distinct().all()
    user_ids.update(u[0] for u in deposit_users)
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


@router.post("/tables/{table_name}/bulk-delete")
def bulk_delete_rows(table_name: str, payload: dict, current_user: models.User = Depends(auth.require_roles(["superadmin"])), db: Session = Depends(get_db)):
    if table_name not in MODELS_MAP:
        raise HTTPException(status_code=404, detail="Table not found")
    
    model = MODELS_MAP[table_name]
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No row IDs provided.")
    
    try:
        rows = db.query(model).filter(model.id.in_(ids)).all()
        deleted = len(rows)
        for row in rows:
            # Special handling for meal_cycles: reset affected users before delete
            if table_name == "meal_cycles" and isinstance(row, models.MealCycle):
                _reset_cycle_users(row.id, db)
            db.delete(row)
        db.commit()
        return {"message": f"{deleted} row(s) deleted successfully.", "deleted_count": deleted}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")


@router.post("/users/bulk")
def bulk_create_users(
    payload: schemas.BulkUserCreate,
    current_user: models.User = Depends(auth.require_roles(["superadmin"])),
    db: Session = Depends(get_db)
):
    lines = [line.strip() for line in payload.users_data.split("\n") if line.strip()]
    created_count = 0
    errors = []
    
    password_hash = auth.get_password_hash(payload.default_password)
    
    for idx, line in enumerate(lines, 1):
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
            
        username = parts[0]
        name = parts[1] if len(parts) > 1 and parts[1] else username
        room = parts[2] if len(parts) > 2 and parts[2] else None
        
        # Check if username already exists
        existing = db.query(models.User).filter(models.User.username == username).first()
        if existing:
            errors.append(f"Line {idx}: Username '{username}' already exists.")
            continue
            
        new_user = models.User(
            username=username,
            password_hash=password_hash,
            role=payload.role,
            hall_id=payload.hall_id,
            name=name,
            room_number=room,
            balance=0.0,
            free_meal=False,
            status="both"
        )
        db.add(new_user)
        db.flush()
        # Auto-seed meal statuses with past dates as "off"
        if new_user.hall_id and new_user.role == "student":
            cycles = db.query(models.MealCycle).filter(
                models.MealCycle.hall_id == new_user.hall_id,
                models.MealCycle.status.in_(["active", "poll"])
            ).all()
            for cycle in cycles:
                c_dates = billing_helper.get_cycle_dates(cycle, restrict_to_today=False)
                today_str = date.today().strftime("%Y-%m-%d")
                for d_str in c_dates:
                    db.add(models.StudentMealStatus(
                        user_id=new_user.id, meal_cycle_id=cycle.id, date=d_str,
                        status="off" if d_str < today_str else new_user.status or "both",
                        ticked_lunch=False if d_str < today_str else True,
                        ticked_dinner=False if d_str < today_str else True,
                        kept_lunch_for_dinner=False, is_guest=False,
                        is_deducted=False, amount_deducted=0.0
                    ))
        created_count += 1
        
    db.commit()
    
    return {
        "status": "success",
        "created_count": created_count,
        "errors": errors
    }
