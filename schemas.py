from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List

class UserCreate(BaseModel):
    username: str
    password: str
    name: str
    email: str
    role: str = "student" # student, manager, assistant_manager, staff, superadmin
    hall_id: Optional[int] = None
    room_number: Optional[str] = None
    phone: Optional[str] = None
    free_meal: bool = False
    status: Optional[str] = "both"

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    hall_id: Optional[int] = None
    room_number: Optional[str] = None
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    balance: float
    free_meal: bool
    status: Optional[str] = "both"
    egg_alternative: Optional[bool] = False
    prefer_beef: Optional[bool] = False
    prefer_mutton: Optional[bool] = False
    meal_preference: Optional[str] = "normal"
    fish_egg_pref: Optional[str] = "normal"
    meat_pref: Optional[str] = "normal"

    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    room_number: Optional[str] = None
    role: Optional[str] = None
    hall_id: Optional[int] = None
    balance: Optional[float] = None
    free_meal: Optional[bool] = None
    status: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class HallCreate(BaseModel):
    name: str
    guest_meal_rate: float = 120.0
    manager_charge_per_day: float = 5.0

class HallResponse(BaseModel):
    id: int
    name: str
    guest_meal_rate: float
    manager_charge_per_day: float

    model_config = ConfigDict(from_attributes=True)

class MealCycleCreate(BaseModel):
    month: str # YYYY-MM
    cutoff_time: str = "20:00"
    lunch_percentage: float = 0.5
    dinner_percentage: float = 0.5
    lunch_only_rate_percentage: float = 0.4
    dinner_only_rate_percentage: float = 0.6
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    full_rate_days: str = "4"

class MealCycleResponse(BaseModel):
    id: int
    hall_id: int
    month: str
    status: str
    cutoff_time: str
    lunch_percentage: float
    dinner_percentage: float
    lunch_only_rate_percentage: float = 0.4
    dinner_only_rate_percentage: float = 0.6
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    full_rate_days: str = "4"

    model_config = ConfigDict(from_attributes=True)

class DepositCreate(BaseModel):
    username: str
    amount: float
    date: str
    description: Optional[str] = None

class DepositResponse(BaseModel):
    id: int
    user_id: int
    meal_cycle_id: int
    amount: float
    date: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ExpenseCreate(BaseModel):
    date: str
    description: str
    amount: float
    quantity: Optional[float] = None
    unit: Optional[str] = None
    meal_type: Optional[str] = "both" # lunch, dinner, both
    paid: bool = True

class ExpenseResponse(BaseModel):
    id: int
    meal_cycle_id: int
    date: str
    description: str
    amount: float
    quantity: Optional[float] = None
    unit: Optional[str] = None
    meal_type: Optional[str] = None
    paid: bool = True

    model_config = ConfigDict(from_attributes=True)

class MealStatusToggle(BaseModel):
    date: str
    status: str # off, both, lunch_only, dinner_only

class MealStatusAdminOverride(BaseModel):
    user_id: int
    date: str
    status: str
    ticked_lunch: Optional[bool] = None
    ticked_dinner: Optional[bool] = None
    kept_lunch_for_dinner: Optional[bool] = None
    is_guest: Optional[bool] = None
    guest_from_hall_id: Optional[int] = None

class ExpenseBatchCreate(BaseModel):
    items: List[ExpenseCreate]

class InventoryPaymentCreate(BaseModel):
    date: str
    paid_to: str
    method: str = "Cash"
    amount: float
    notes: str = ""

class InventoryPaymentResponse(BaseModel):
    id: int
    meal_cycle_id: int
    date: str
    paid_to: str
    method: str
    amount: float
    notes: str

    model_config = ConfigDict(from_attributes=True)

class CashoutCreate(BaseModel):
    date: str
    amount: float
    from_method: str = "Mobile Banking"
    notes: str = ""

class DailyFeeOverrideCreate(BaseModel):
    date: str
    manager_charge: Optional[float] = None
    guest_charge: Optional[float] = None

class EmailBillRequest(BaseModel):
    username: Optional[str] = None
    send_all: bool = False
    mode: str = "all_at_once" # all_at_once, one_by_one


class EmailReportRequest(BaseModel):
    email: str
    user_id: int


class BkashWebhookPayload(BaseModel):
    text: str
    secret: str


class BkashVerifyTrxRequest(BaseModel):
    trx_id: str


class BkashManualTransactionCreate(BaseModel):
    trx_id: str
    amount: float
    sender: Optional[str] = "Manager"


class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    room_number: Optional[str] = None
    password: Optional[str] = None
    egg_alternative: Optional[bool] = None
    prefer_beef: Optional[bool] = None
    prefer_mutton: Optional[bool] = None
    meal_preference: Optional[str] = None
    fish_egg_pref: Optional[str] = None
    meat_pref: Optional[str] = None


class BulkUserCreate(BaseModel):
    users_data: str
    role: str = "student"
    hall_id: Optional[int] = None
    default_password: str
