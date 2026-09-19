from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Time, Date
from sqlalchemy.orm import relationship
from database import Base

class Hall(Base):
    __tablename__ = "halls"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    guest_meal_rate = Column(Float, default=120.0)
    manager_charge_per_day = Column(Float, default=5.0)
    guest_charge_per_day = Column(Float, default=5.0)

    users = relationship("User", back_populates="hall")
    cycles = relationship("MealCycle", back_populates="hall")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="student")  # superadmin, manager, assistant_manager, staff, student
    hall_id = Column(Integer, ForeignKey("halls.id"), nullable=True)
    room_number = Column(String, nullable=True)
    name = Column(String)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    free_meal = Column(Boolean, default=False)
    status = Column(String, default="both") # both, lunch_only, dinner_only, off
    egg_alternative = Column(Boolean, default=False)
    prefer_beef = Column(Boolean, default=False)
    prefer_mutton = Column(Boolean, default=False)
    meal_preference = Column(String, default="normal") # normal, if_pangas_then_egg, egg_instead_of_fish, beef, mutton
    fish_egg_pref = Column(String, default="normal") # normal, if_pangas_then_egg, egg_instead_of_fish
    meat_pref = Column(String, default="normal") # normal, beef, mutton

    hall = relationship("Hall", back_populates="users")
    meal_statuses = relationship("StudentMealStatus", back_populates="user", cascade="all, delete-orphan")
    deposits = relationship("Deposit", back_populates="user", cascade="all, delete-orphan")


class MealCycle(Base):
    __tablename__ = "meal_cycles"

    id = Column(Integer, primary_key=True, index=True)
    hall_id = Column(Integer, ForeignKey("halls.id"))
    month = Column(String)  # e.g. "2026-06"
    status = Column(String, default="poll")  # poll, active, closed
    cutoff_time = Column(String, default="20:00")  # HH:MM format
    lunch_percentage = Column(Float, default=0.5)
    dinner_percentage = Column(Float, default=0.5)
    lunch_only_rate_percentage = Column(Float, default=0.4)
    dinner_only_rate_percentage = Column(Float, default=0.6)
    start_date = Column(String, nullable=True)
    end_date = Column(String, nullable=True)
    full_rate_days = Column(String, default="4")  # comma-separated weekday numbers, e.g. "4"=Friday

    hall = relationship("Hall", back_populates="cycles")
    expenses = relationship("Expense", back_populates="meal_cycle", cascade="all, delete-orphan")
    meal_statuses = relationship("StudentMealStatus", back_populates="meal_cycle", cascade="all, delete-orphan")
    deposits = relationship("Deposit", back_populates="meal_cycle", cascade="all, delete-orphan")


class StudentMealStatus(Base):
    __tablename__ = "student_meal_statuses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    meal_cycle_id = Column(Integer, ForeignKey("meal_cycles.id"))
    date = Column(String)  # YYYY-MM-DD
    status = Column(String, default="off")  # off, both, lunch_only, dinner_only
    ticked_lunch = Column(Boolean, default=False)
    ticked_dinner = Column(Boolean, default=False)
    kept_lunch_for_dinner = Column(Boolean, default=False)
    is_guest = Column(Boolean, default=False)
    guest_from_hall_id = Column(Integer, ForeignKey("halls.id"), nullable=True)
    is_deducted = Column(Boolean, default=False)
    amount_deducted = Column(Float, default=0.0)

    user = relationship("User", back_populates="meal_statuses")
    meal_cycle = relationship("MealCycle", back_populates="meal_statuses")


class Deposit(Base):
    __tablename__ = "deposits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    meal_cycle_id = Column(Integer, ForeignKey("meal_cycles.id"))
    amount = Column(Float)
    date = Column(String)  # YYYY-MM-DD
    description = Column(String, nullable=True)

    user = relationship("User", back_populates="deposits")
    meal_cycle = relationship("MealCycle", back_populates="deposits")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    meal_cycle_id = Column(Integer, ForeignKey("meal_cycles.id"))
    date = Column(String)  # YYYY-MM-DD
    description = Column(String)
    amount = Column(Float)
    quantity = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    meal_type = Column(String, default="both") # lunch, dinner, both
    paid = Column(Boolean, default=True)  # True=Paid, False=Unpaid

    meal_cycle = relationship("MealCycle", back_populates="expenses")


class BkashReceivedSms(Base):
    __tablename__ = "bkash_received_sms"

    id = Column(Integer, primary_key=True, index=True)
    trx_id = Column(String, unique=True, index=True)
    sender = Column(String)
    amount = Column(Float)
    raw_text = Column(String)
    status = Column(String, default="pending")  # pending, approved, rejected
    is_claimed = Column(Boolean, default=False)
    claimed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_amount = Column(Float, nullable=True)
    date_received = Column(String)  # YYYY-MM-DD

    user = relationship("User", foreign_keys=[claimed_by_user_id])
    approver = relationship("User", foreign_keys=[approved_by_user_id])


class ManualUserRecord(Base):
    __tablename__ = "manual_user_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String)
    room = Column(String)
    status = Column(String, nullable=True)
    lunch_meals = Column(Float, default=0.0)
    dinner_meals = Column(Float, default=0.0)
    deposits = Column(Float, default=0.0)
    costs = Column(Float, default=0.0)
    give_take = Column(Float, default=0.0)

    user = relationship("User")


class ManualDailyRate(Base):
    __tablename__ = "manual_daily_rates"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, index=True)
    lunch_cost = Column(Float, default=0.0)
    dinner_cost = Column(Float, default=0.0)
    lunch_meals = Column(Float, default=0.0)
    dinner_meals = Column(Float, default=0.0)
    lunch_rate = Column(Float, default=0.0)
    dinner_rate = Column(Float, default=0.0)
    total_rate = Column(Float, default=0.0)


class ManualShoppingItem(Base):
    __tablename__ = "manual_shopping_items"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, index=True)
    meal_type = Column(String)  # lunch, dinner
    description = Column(String)
    cost = Column(Float, default=0.0)


class DailyMenu(Base):
    __tablename__ = "daily_menu"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, index=True)
    hall_id = Column(Integer, ForeignKey("halls.id"))
    fish_served = Column(Boolean, default=False)
    beef_served = Column(Boolean, default=False)
    pangas_served = Column(Boolean, default=False)
    other_fish_served = Column(Boolean, default=False)
    mutton_served = Column(Boolean, default=False)


class InventoryPayment(Base):
    __tablename__ = "inventory_payments"

    id = Column(Integer, primary_key=True, index=True)
    meal_cycle_id = Column(Integer, ForeignKey("meal_cycles.id"))
    date = Column(String)
    paid_to = Column(String)
    method = Column(String, default="Cash")
    amount = Column(Float)
    notes = Column(String, default="")


class Cashout(Base):
    __tablename__ = "cashouts"

    id = Column(Integer, primary_key=True, index=True)
    meal_cycle_id = Column(Integer, ForeignKey("meal_cycles.id"))
    date = Column(String)
    amount = Column(Float)
    from_method = Column(String, default="Mobile Banking")
    notes = Column(String, default="")


class DailyFeeOverride(Base):
    __tablename__ = "daily_fee_overrides"

    id = Column(Integer, primary_key=True, index=True)
    meal_cycle_id = Column(Integer, ForeignKey("meal_cycles.id"))
    date = Column(String)
    manager_charge = Column(Float, nullable=True)  # None = use default
    guest_charge = Column(Float, nullable=True)    # None = use default


class AppConfig(Base):
    __tablename__ = "app_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String, default="")

