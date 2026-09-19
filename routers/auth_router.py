from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
import auth
from routers.admin_router import check_feature_locked

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=schemas.UserResponse)
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    check_feature_locked("signup", db)
    # Check if user already exists
    existing_user = db.query(models.User).filter(models.User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
        
    # Email is required and must be valid
    if not user_data.email or "@" not in user_data.email or "." not in user_data.email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="A valid email address is required")
    
    # Check if email is already taken
    existing_email = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Check if hall exists if provided
    if user_data.hall_id:
        hall = db.query(models.Hall).filter(models.Hall.id == user_data.hall_id).first()
        if not hall:
            raise HTTPException(status_code=404, detail="Selected hall does not exist")

    hashed_pw = auth.get_password_hash(user_data.password)
    
    # Auto-escalate "admin" username to superadmin for setup convenience
    role = user_data.role
    if user_data.username.lower() == "admin":
        role = "superadmin"

    new_user = models.User(
        username=user_data.username,
        password_hash=hashed_pw,
        role=role,
        hall_id=user_data.hall_id,
        room_number=user_data.room_number,
        name=user_data.name,
        phone=user_data.phone,
        email=user_data.email,
        free_meal=user_data.free_meal,
        balance=0.0,
        status=user_data.status or "both"
    )
    db.add(new_user)
    db.flush()
    
    # Auto-seed meal statuses for any active/polling cycle in their hall
    if new_user.hall_id and new_user.role == "student":
        active_cycles = db.query(models.MealCycle).filter(
            models.MealCycle.hall_id == new_user.hall_id,
            models.MealCycle.status.in_(["active", "poll"])
        ).all()
        for cycle in active_cycles:
            import billing_helper
            from datetime import date
            dates = billing_helper.get_cycle_dates(cycle, restrict_to_today=False)
            
            today_str = date.today().strftime("%Y-%m-%d")
            for d_str in dates:
                db.add(models.StudentMealStatus(
                    user_id=new_user.id,
                    meal_cycle_id=cycle.id,
                    date=d_str,
                    status="off" if d_str < today_str else (new_user.status or "both"),
                    ticked_lunch=False if d_str < today_str else (new_user.status in ["both", "lunch_only", "double", "triple"]),
                    ticked_dinner=False if d_str < today_str else (new_user.status in ["both", "dinner_only", "double", "triple"]),
                    kept_lunch_for_dinner=False,
                    is_guest=False
                ))
                
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/login", response_model=schemas.TokenResponse)
def login(credentials: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == credentials.username).first()
    if not user or not auth.verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    # Attach hall_name
    hall_name = None
    if current_user.hall_id:
        hall = db.query(models.Hall).filter(models.Hall.id == current_user.hall_id).first()
        if hall:
            hall_name = hall.name
    setattr(current_user, "hall_name", hall_name)
    return current_user


@router.put("/profile", response_model=schemas.UserResponse)
def update_profile(
    payload: schemas.UserProfileUpdate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    check_feature_locked("edit_profile", db)
    if payload.name is not None:
        current_user.name = payload.name.strip()
    if payload.phone is not None:
        current_user.phone = payload.phone.strip()
    if payload.email is not None:
        current_user.email = payload.email.strip()
    if payload.room_number is not None:
        current_user.room_number = payload.room_number.strip()
    if payload.password is not None and payload.password.strip() != "":
        current_user.password_hash = auth.get_password_hash(payload.password.strip())
    if payload.egg_alternative is not None:
        current_user.egg_alternative = payload.egg_alternative
    if payload.prefer_beef is not None:
        current_user.prefer_beef = payload.prefer_beef
    if payload.prefer_mutton is not None:
        current_user.prefer_mutton = payload.prefer_mutton
    if payload.meal_preference is not None:
        current_user.meal_preference = payload.meal_preference
    if payload.fish_egg_pref is not None:
        current_user.fish_egg_pref = payload.fish_egg_pref
    if payload.meat_pref is not None:
        current_user.meat_pref = payload.meat_pref
        
    db.commit()
    db.refresh(current_user)
    return current_user
