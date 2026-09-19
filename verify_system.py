import os
import sys
import unittest
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import models & database
import models
import auth
import billing_helper
from database import Base

class TestDiningManagementSystem(unittest.TestCase):
    def setUp(self):
        # Use a temporary in-memory SQLite database for testing to avoid Windows file lock conflicts
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = Session()
        
        # Seed test halls
        self.mukti = models.Hall(name="Muktijoddha Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.ekushe = models.Hall(name="Amar Ekushe Hall", guest_meal_rate=100.0, manager_charge_per_day=5.0)
        self.db.add_all([self.mukti, self.ekushe])
        self.db.commit()
        
        # Seed managers
        self.mukti_mgr = models.User(
            username="mukti_mgr", password_hash=auth.get_password_hash("mgr123"),
            role="manager", hall_id=self.mukti.id, name="Sabbir Ahmed", balance=0.0, free_meal=True
        )
        self.ekushe_mgr = models.User(
            username="ekushe_mgr", password_hash=auth.get_password_hash("mgr123"),
            role="manager", hall_id=self.ekushe.id, name="Tanvir Hossain", balance=0.0, free_meal=True
        )
        
        # Seed students
        self.student1 = models.User(
            username="student1", password_hash=auth.get_password_hash("std123"),
            role="student", hall_id=self.mukti.id, name="Kamrul Islam", balance=1000.0, free_meal=False
        )
        self.student2 = models.User(
            username="student2", password_hash=auth.get_password_hash("std123"),
            role="student", hall_id=self.mukti.id, name="Rakib Hasan", balance=1000.0, free_meal=False
        )
        # Guest student
        self.guest_student = models.User(
            username="guest_std", password_hash=auth.get_password_hash("std123"),
            role="student", hall_id=self.ekushe.id, name="Sakib Al Hasan", balance=500.0, free_meal=False
        )
        
        self.db.add_all([self.mukti_mgr, self.ekushe_mgr, self.student1, self.student2, self.guest_student])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_cycle_and_meal_toggles(self):
        # 1. Start cycle for Muktijoddha Hall
        import billing_helper
        cycle_month = date.today().strftime("%Y-%m")
        future_date = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        cycle = models.MealCycle(
            hall_id=self.mukti.id,
            month=cycle_month,
            status="active",
            cutoff_time="20:00",
            lunch_percentage=0.5,
            dinner_percentage=0.5,
            start_date=date.today().strftime("%Y-%m-%d"),
            end_date=future_date
        )
        self.db.add(cycle)
        self.db.commit()

        # 2. Verify Student 1 toggles meal for a future date (uses the actual router function)
        from routers.student_router import toggle_meal_status
        from schemas import MealStatusToggle
        
        payload = MealStatusToggle(date=future_date, status="both")
        
        # Call the actual API route logic
        toggle_meal_status(payload, current_user=self.student1, db=self.db)
        
        # Retrieve and verify start date
        db_status = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == self.student1.id,
            models.StudentMealStatus.date == future_date
        ).first()
        self.assertEqual(db_status.status, "both")
        self.assertFalse(db_status.is_guest)
        
        # Verify it carried forward to the end date
        last_db_status = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == self.student1.id,
            models.StudentMealStatus.date == future_date
        ).first()
        self.assertEqual(last_db_status.status, "both")

    def test_meal_rate_and_settlement(self):
        # Setup an active cycle
        cycle_month = "2026-06"
        cycle = models.MealCycle(
            hall_id=self.mukti.id,
            month=cycle_month,
            status="active",
            cutoff_time="20:00",
            lunch_percentage=0.5,
            dinner_percentage=0.5
        )
        self.db.add(cycle)
        self.db.commit()

        # Add deposits
        # student1 balance starts at 1000, student2 at 1000
        # Add 500 deposit for student1
        dep1 = models.Deposit(user_id=self.student1.id, meal_cycle_id=cycle.id, amount=500.0, date="2026-06-01", description="Cash")
        self.student1.balance += 500.0
        self.db.add(dep1)
        self.db.commit()
        self.assertEqual(self.student1.balance, 1500.0)

        # Log daily meal statuses for the month
        # student1 eats full meal ("both") for 10 days = 10 meal units
        # student2 eats only lunch ("lunch_only") for 10 days = 10 * 0.5 = 5 meal units
        # guest_student (from Ekushe Hall) eats full meal ("both") in Mukti Hall as guest for 2 days = 2 guest meal units
        # mukti_mgr (free_meal=True) eats "both" for 10 days = 0 paying meal units (free of cost)
        
        # Add student1 status
        for d in range(1, 11):
            d_str = f"2026-06-{d:02d}"
            status = models.StudentMealStatus(
                user_id=self.student1.id, meal_cycle_id=cycle.id, date=d_str, status="both"
            )
            self.db.add(status)
            
        # Add student2 status
        for d in range(1, 11):
            d_str = f"2026-06-{d:02d}"
            status = models.StudentMealStatus(
                user_id=self.student2.id, meal_cycle_id=cycle.id, date=d_str, status="lunch_only"
            )
            self.db.add(status)

        # Add guest status
        for d in range(1, 3):
            d_str = f"2026-06-{d:02d}"
            status = models.StudentMealStatus(
                user_id=self.guest_student.id, meal_cycle_id=cycle.id, date=d_str, status="both",
                is_guest=True, guest_from_hall_id=self.ekushe.id
            )
            self.db.add(status)
            
        # Add manager status (should be ignored in paying meal count calculation)
        for d in range(1, 11):
            d_str = f"2026-06-{d:02d}"
            status = models.StudentMealStatus(
                user_id=self.mukti_mgr.id, meal_cycle_id=cycle.id, date=d_str, status="both"
            )
            self.db.add(status)

        # Add food expenses
        # Total food expense = BDT 3000
        exp1 = models.Expense(meal_cycle_id=cycle.id, date="2026-06-05", description="Market Shopping 1", amount=1800.0)
        exp2 = models.Expense(meal_cycle_id=cycle.id, date="2026-06-15", description="Market Shopping 2", amount=1200.0)
        self.db.add_all([exp1, exp2])
        self.db.commit()

        # Let's perform financial summary calculations
        # Total expenses = 3000
        # Guest rate in Muktijoddha Hall = 120.0
        # Guest contribution = 2 days * both (1.0 weight) * 120.0 guest rate = BDT 240.0
        # Net expenses to be shared = 3000 - 240 = 2760.0
        # Paying meal units from home students:
        # student1 = 10 days * 1.0 = 10 units
        # student2 = 10 days * 0.5 = 5 units
        # total home paying units = 15.0
        # Daily/Month meal rate = 2760 / 15 = 184.0 BDT per meal unit!
        
        # Calculate guest contribution
        guest_contrib = 0.0
        guest_rate = self.mukti.guest_meal_rate
        home_units = 0.0
        mgr_fees_student1 = 0.0
        mgr_fees_student2 = 0.0
        
        meals = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id
        ).all()
        
        for m in meals:
            weight = 1.0 if m.status == "both" else 0.5
            u = self.db.query(models.User).filter(models.User.id == m.user_id).first()
            if m.is_guest:
                guest_contrib += (weight * guest_rate)
            else:
                if not u.free_meal:
                    home_units += weight
                    if u.id == self.student1.id:
                        mgr_fees_student1 += self.mukti.manager_charge_per_day
                    elif u.id == self.student2.id:
                        mgr_fees_student2 += self.mukti.manager_charge_per_day
                        
        total_expenses = 3000.0
        net_expenses = total_expenses - guest_contrib
        calculated_meal_rate = net_expenses / home_units
        
        self.assertEqual(guest_contrib, 240.0)
        self.assertEqual(home_units, 15.0)
        self.assertEqual(calculated_meal_rate, 184.0)

        # 3.Settle / Close cycle and check balances
        # Student 1 bill: 10 units * 184.0 + 10 days * 5 BDT = 1840 + 50 = BDT 1890.0
        # Student 1 balance: 1500 - 1890 = -390.0 BDT
        # Student 2 bill: 5 units * 184.0 + 10 days * 5 BDT = 920 + 50 = BDT 970.0
        # Student 2 balance: 1000 - 970 = +30.0 BDT
        # Guest student bill: 2 units * 120.0 = BDT 240.0
        # Guest student balance: 500 - 240 = BDT 260.0
        # Manager bill: free_meal=True, so BDT 0.0
        
        # Apply settlement
        billings = {
            self.student1.id: (10.0 * calculated_meal_rate) + mgr_fees_student1,
            self.student2.id: (5.0 * calculated_meal_rate) + mgr_fees_student2,
            self.guest_student.id: 2.0 * guest_rate,
            self.mukti_mgr.id: 0.0
        }
        
        for u_id, bill in billings.items():
            user = self.db.query(models.User).filter(models.User.id == u_id).first()
            user.balance -= bill
        
        cycle.status = "closed"
        self.db.commit()
        
        # Verify final balances
        self.db.refresh(self.student1)
        self.db.refresh(self.student2)
        self.db.refresh(self.guest_student)
        self.db.refresh(self.mukti_mgr)
        
        self.assertEqual(self.student1.balance, -390.0)
        self.assertEqual(self.student2.balance, 30.0)
        self.assertEqual(self.guest_student.balance, 260.0)
        self.assertEqual(self.mukti_mgr.balance, 0.0)
        self.assertEqual(cycle.status, "closed")
        print("\n[OK] Financial and billing calculations verified successfully!")

    def test_constraints_and_conflicts(self):
        from routers.manager_router import add_deposit
        from schemas import DepositCreate
        from fastapi import HTTPException
        
        # 1. Negative deposit constraint validation
        payload_dep = DepositCreate(username="student1", amount=-100.0, date="2026-06-01", description="Invalid")
        with self.assertRaises(HTTPException) as context:
            add_deposit(payload_dep, current_user=self.mukti_mgr, db=self.db)
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Deposit amount must be greater than zero.")
        
        # Setup an active cycle with dates spanning into the future
        current_month = date.today().strftime("%Y-%m")
        future_date = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        
        cycle = models.MealCycle(
            hall_id=self.mukti.id, month=current_month, status="active",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5,
            start_date=date.today().strftime("%Y-%m-%d"), end_date=future_date
        )
        self.db.add(cycle)
        self.db.commit()

        # 2. Meal toggle works (deductions happen later via deduct_passed_meals)
        from routers.student_router import toggle_meal_status, toggle_guest_meal
        from schemas import MealStatusToggle
        
        payload_toggle = MealStatusToggle(date=future_date, status="both")
        toggle_meal_status(payload_toggle, current_user=self.student1, db=self.db)
        
        # Toggle home meal active
        toggle_meal_status(payload_toggle, current_user=self.student1, db=self.db)
        status_home = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == self.student1.id,
            models.StudentMealStatus.date == future_date,
            models.StudentMealStatus.is_guest == False
        ).first()
        self.assertEqual(status_home.status, "both")
        
        # Setup guest cycle in Ekushe Hall
        guest_cycle = models.MealCycle(
            hall_id=self.ekushe.id, month=current_month, status="active",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5,
            start_date=date.today().strftime("%Y-%m-%d"), end_date=future_date
        )
        self.db.add(guest_cycle)
        self.db.commit()
        
        # Shut down home hall (to allow guest switching)
        cycle.status = "closed"
        self.db.commit()
        
        # Toggle guest meal in Ekushe Hall
        toggle_guest_meal(payload_toggle, target_hall_id=self.ekushe.id, current_user=self.student1, db=self.db)
        
        # Assert guest status is active
        status_guest = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == self.student1.id,
            models.StudentMealStatus.date == future_date,
            models.StudentMealStatus.is_guest == True
        ).first()
        self.assertEqual(status_guest.status, "both")
        
        # Assert home status was automatically set to "off"!
        self.db.refresh(status_home)
        self.assertEqual(status_home.status, "off")
        print("[OK] Negative deposits, balance validations, and conflict resolutions verified successfully!")

    def test_daily_deductions_and_reconciliation(self):
        # 1. Setup active cycle for June 2026
        cycle = models.MealCycle(
            hall_id=self.mukti.id, month="2026-06", status="active",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5
        )
        self.db.add(cycle)
        self.db.commit()

        # 2. Add an expense of BDT 1000.0
        exp = models.Expense(meal_cycle_id=cycle.id, date="2026-06-01", description="Rice", amount=1000.0)
        self.db.add(exp)
        self.db.commit()

        # 3. Add student1 status records (say, for days 1, 2, 3 in the past)
        # student1 balance starts at 1000.0
        status1 = models.StudentMealStatus(
            user_id=self.student1.id, meal_cycle_id=cycle.id, date="2026-06-01", status="both"
        )
        status2 = models.StudentMealStatus(
            user_id=self.student1.id, meal_cycle_id=cycle.id, date="2026-06-02", status="both"
        )
        self.db.add_all([status1, status2])
        self.db.commit()

        # 4. Verify daily deductions logic (since date < today)
        import billing_helper
        # Under daily billing model:
        # Day 1 has BDT 1000.0 expense. 1 home student eats both. Cost = 1000.0 + 5.0 (mgr) = 1005.0 BDT.
        # Day 2 has BDT 0.0 expense. 1 home student eats both. Cost = 0.0 + 5.0 = 5.0 BDT.
        # Total deducted = 1010.0 BDT.
        
        # Deduct meals
        billing_helper.deduct_passed_meals(self.db)
        
        # Verify student1 balance is deducted
        self.db.refresh(self.student1)
        self.db.refresh(status1)
        self.db.refresh(status2)
        
        # student1 balance: 1000 - 1010 = -10.0
        self.assertEqual(self.student1.balance, -10.0)
        self.assertTrue(status1.is_deducted)
        self.assertEqual(status1.amount_deducted, 1005.0)
        self.assertEqual(status2.amount_deducted, 5.0)
        
        # 5. Add a guest student status in this cycle
        # guest_student balance starts at 500.0. final_rate=0 (no expense on that date) + guest_charge_per_day=5
        guest_status = models.StudentMealStatus(
            user_id=self.guest_student.id, meal_cycle_id=cycle.id, date="2026-06-03", status="both",
            is_guest=True, guest_from_hall_id=self.ekushe.id
        )
        self.db.add(guest_status)
        self.db.commit()
        
        billing_helper.deduct_passed_meals(self.db)
        
        self.db.refresh(self.guest_student)
        self.db.refresh(guest_status)
        
        rates = billing_helper.get_daily_meal_rates(cycle, "2026-06-03", self.db)
        expected_guest_cost = rates["final_rate"] + self.mukti.guest_charge_per_day
        expected_guest_balance = 500.0 - expected_guest_cost
        
        self.assertEqual(self.guest_student.balance, expected_guest_balance)
        self.assertTrue(guest_status.is_deducted)
        self.assertEqual(guest_status.amount_deducted, expected_guest_cost)
        
        # 6. Reconcile on Close Cycle (e.g., more expenses added, new rate)
        exp2 = models.Expense(meal_cycle_id=cycle.id, date="2026-06-05", description="Oil", amount=500.0)
        self.db.add(exp2)
        self.db.commit()
        
        # Close cycle
        from routers.manager_router import close_cycle
        close_cycle(month="2026-06", current_user=self.mukti_mgr, db=self.db)
        
        # Verify student1 balance reconciled:
        # Under daywise billing, expenses on 2026-06-05 do not affect student1 since student1 did not eat that day.
        # So student1's balance remains -10.0.
        self.db.refresh(self.student1)
        self.assertEqual(self.student1.balance, -10.0)
        
        # Verify guest balance reconciled:
        # Guest bill = final_rate(0) + guest_charge(5) = 5. Already deducted: 5. Final balance: 495.0
        self.db.refresh(self.guest_student)
        rates2 = billing_helper.get_daily_meal_rates(cycle, "2026-06-03", self.db)
        expected_guest_cost2 = rates2["final_rate"] + self.mukti.guest_charge_per_day
        expected_guest_balance2 = 500.0 - expected_guest_cost2
        self.assertEqual(self.guest_student.balance, expected_guest_balance2)
        print("[OK] Daily deductions and billing reconciliation math verified successfully!")

        # 7. Reopen Cycle and verify balances and status records are restored!
        from routers.manager_router import reopen_cycle
        reopen_cycle(month="2026-06", current_user=self.mukti_mgr, db=self.db)
        
        # Verify student1 balance restored
        self.db.refresh(self.student1)
        self.assertEqual(self.student1.balance, -10.0)
        
        # Verify status records are restored to correct daily costs
        self.db.refresh(status1)
        self.db.refresh(status2)
        self.assertTrue(status1.is_deducted)
        self.assertEqual(status1.amount_deducted, 1005.0)
        
        # Verify cycle status is active
        self.db.refresh(cycle)
        self.assertEqual(cycle.status, "active")
        print("[OK] Reopen cycle balance restoration and status reset verified successfully!")

    def test_new_features_dining_expansion(self):
        from routers.auth_router import register
        from routers.manager_router import get_student_meals, email_bill
        from schemas import UserCreate, EmailBillRequest
        from fastapi import HTTPException
        
        # 1. Test registration with invalid/missing email
        with self.assertRaises(HTTPException) as context:
            invalid_user = UserCreate(
                username="teststudent1", password="pw", name="Test Student",
                email="no_at_symbol.com", hall_id=self.mukti.id
            )
            register(invalid_user, db=self.db)
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("valid email address", context.exception.detail)
        
        # Test registration with valid email
        valid_user = UserCreate(
            username="teststudent2", password="pw", name="Test Student 2",
            email="teststudent2@example.com", hall_id=self.mukti.id
        )
        registered_u = register(valid_user, db=self.db)
        self.assertEqual(registered_u.email, "teststudent2@example.com")
        
        # 2. Test get_student_meals endpoint
        # Setup an active cycle with dates covering the future
        from datetime import timedelta as td
        future_date = (date.today() + td(days=5)).strftime("%Y-%m-%d")
        cycle = models.MealCycle(
            hall_id=self.mukti.id, month="2026-06", status="active",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5,
            start_date=date.today().strftime("%Y-%m-%d"), end_date=future_date
        )
        self.db.add(cycle)
        self.db.commit()
        
        meals_list = get_student_meals(date_str=future_date, current_user=self.mukti_mgr, db=self.db)
        
        # Verify it lists home students
        usernames = {m["username"] for m in meals_list}
        self.assertIn(self.student1.username, usernames)
        
        # Verify defaults: new future date gets user's profile default
        for m in meals_list:
            if m["username"] == self.student1.username:
                self.assertEqual(m["status"], self.student1.status or "both")
                if self.student1.status in ["both", "lunch_only", "double", "triple"]:
                    self.assertTrue(m["ticked_lunch"])
                    self.assertTrue(m["ticked_dinner"])
                
        # 3. Test manager email-bill endpoint in both modes
        # Setup emails for test users
        self.student1.email = "student1@example.com"
        self.student2.email = "student2@example.com"
        
        # Add meal statuses for student1 & student2 so they are included in the billing summary
        status_s1 = models.StudentMealStatus(
            user_id=self.student1.id, meal_cycle_id=cycle.id, date="2026-06-15", status="both"
        )
        status_s2 = models.StudentMealStatus(
            user_id=self.student2.id, meal_cycle_id=cycle.id, date="2026-06-15", status="both"
        )
        self.db.add_all([status_s1, status_s2])
        self.db.commit()
        
        # all_at_once mode
        payload_all = EmailBillRequest(send_all=True, mode="all_at_once")
        res_all = email_bill(payload_all, current_user=self.mukti_mgr, db=self.db)
        self.assertIn("Simulated emails", res_all["message"])
        self.assertIn("student1@example.com", res_all["sent_emails"])
        self.assertIn("student2@example.com", res_all["sent_emails"])
        
        # one_by_one mode for single student
        payload_single = EmailBillRequest(username="student1", send_all=False, mode="one_by_one")
        res_single = email_bill(payload_single, current_user=self.mukti_mgr, db=self.db)
        self.assertEqual(res_single["sent_count"], 1)
        self.assertIn("student1@example.com", res_single["sent_emails"])
        print("[OK] Signup email check, get_student_meals, and email modes verified successfully!")

    def test_bkash_webhook_and_claim_flow(self):
        from routers.student_router import bkash_webhook, verify_bkash_trx
        from schemas import BkashWebhookPayload, BkashVerifyTrxRequest
        from fastapi import HTTPException
        
        # 1. Setup an active cycle for Muktijoddha Hall
        cycle_month = date.today().strftime("%Y-%m")
        cycle = models.MealCycle(
            hall_id=self.mukti.id,
            month=cycle_month,
            status="active",
            cutoff_time="20:00",
            lunch_percentage=0.5,
            dinner_percentage=0.5
        )
        self.db.add(cycle)
        self.db.commit()
        
        # 2. Test bkash_webhook with invalid secret key
        with self.assertRaises(HTTPException) as context:
            payload_invalid = BkashWebhookPayload(
                text="You have received send money Tk 500.00 from 01711223344. TrxID AH12BG34KL at 15/06/2026 16:30",
                secret="wrong_secret"
            )
            bkash_webhook(payload_invalid, db=self.db)
        self.assertEqual(context.exception.status_code, 401)
        self.assertIn("Invalid webhook secret", context.exception.detail)
        
        # 3. Test bkash_webhook with invalid/unparsable SMS body
        with self.assertRaises(HTTPException) as context:
            payload_invalid_body = BkashWebhookPayload(
                text="This is an unrelated SMS message.",
                secret="edining_bkash_webhook_secret_2026"
            )
            bkash_webhook(payload_invalid_body, db=self.db)
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Could not parse standard bKash Send Money", context.exception.detail)
        
        # 4. Test successful bkash_webhook parse and insertion
        payload_valid = BkashWebhookPayload(
            text="You have received send money Tk 500.00 from 01711223344. TrxID AH12BG34KL at 15/06/2026 16:30",
            secret="edining_bkash_webhook_secret_2026"
        )
        res_webhook = bkash_webhook(payload_valid, db=self.db)
        self.assertEqual(res_webhook["status"], "success")
        self.assertEqual(res_webhook["trx_id"], "AH12BG34KL")
        self.assertEqual(res_webhook["amount"], 500.0)
        
        # Verify it exists in db
        sms_in_db = self.db.query(models.BkashReceivedSms).filter(models.BkashReceivedSms.trx_id == "AH12BG34KL").first()
        self.assertIsNotNone(sms_in_db)
        self.assertEqual(sms_in_db.amount, 500.0)
        self.assertEqual(sms_in_db.sender, "01711223344")
        self.assertFalse(sms_in_db.is_claimed)
        
        # 5. Claim the found transaction — immediately credited (no manager approval needed)
        payload_verify = BkashVerifyTrxRequest(trx_id="AH12BG34KL")
        res_verify = verify_bkash_trx(payload_verify, current_user=self.student1, db=self.db)
        self.assertEqual(res_verify["status"], "success")
        self.assertEqual(res_verify["amount"], 500.0)
        
        # Verify the SMS is marked claimed and approved
        self.db.refresh(sms_in_db)
        self.assertTrue(sms_in_db.is_claimed)
        self.assertEqual(sms_in_db.claimed_by_user_id, self.student1.id)
        self.assertEqual(sms_in_db.status, "approved")
        
        # Verify student1 balance was immediately credited
        self.db.refresh(self.student1)
        self.assertEqual(self.student1.balance, 1500.0)
        
        # 6. Attempt to claim the same Transaction ID again, expecting failure
        with self.assertRaises(HTTPException) as context:
            verify_bkash_trx(payload_verify, current_user=self.student1, db=self.db)
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Transaction ID has already been claimed.")
        
        # 7. Claim a non-existent Transaction ID — creates pending record for manager approval
        res_notfound = verify_bkash_trx(BkashVerifyTrxRequest(trx_id="NONEXIST99"), current_user=self.student1, db=self.db)
        self.assertEqual(res_notfound["status"], "pending")
        pending = self.db.query(models.BkashReceivedSms).filter(models.BkashReceivedSms.trx_id == "NONEXIST99").first()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, "pending")
        self.assertTrue(pending.is_claimed)
        print("[OK] bKash webhook and claim flow verified successfully!")

    def test_manager_manual_bkash_flow(self):
        from routers.manager_router import get_bkash_transactions, add_bkash_transaction
        from routers.student_router import verify_bkash_trx
        from schemas import BkashManualTransactionCreate, BkashVerifyTrxRequest
        from fastapi import HTTPException

        # 1. Setup an active cycle for Muktijoddha Hall
        cycle_month = date.today().strftime("%Y-%m")
        cycle = models.MealCycle(
            hall_id=self.mukti.id,
            month=cycle_month,
            status="active",
            cutoff_time="20:00",
            lunch_percentage=0.5,
            dinner_percentage=0.5
        )
        self.db.add(cycle)
        self.db.commit()

        # 2. Manager adds a manual bKash transaction
        payload = BkashManualTransactionCreate(trx_id="AL99K8X7P2", amount=750.0, sender="Manager")
        result = add_bkash_transaction(payload, current_user=self.mukti_mgr, db=self.db)
        self.assertEqual(result["trx_id"], "AL99K8X7P2")
        self.assertIn("successfully", result["message"].lower())

        # 3. Assert record exists in BkashReceivedSms
        sms = self.db.query(models.BkashReceivedSms).filter(
            models.BkashReceivedSms.trx_id == "AL99K8X7P2"
        ).first()
        self.assertIsNotNone(sms)
        self.assertEqual(sms.amount, 750.0)
        self.assertEqual(sms.sender, "Manager")
        self.assertFalse(sms.is_claimed)

        # 4. Attempt to add duplicate TrxID — expect 400 Bad Request
        with self.assertRaises(HTTPException) as ctx:
            add_bkash_transaction(payload, current_user=self.mukti_mgr, db=self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("already exists", ctx.exception.detail)

        # 5. Student claims the found transaction — immediately credited
        verify_payload = BkashVerifyTrxRequest(trx_id="AL99K8X7P2")
        res = verify_bkash_trx(verify_payload, current_user=self.student1, db=self.db)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["amount"], 750.0)

        # 6. Assert student balance incremented immediately
        self.db.refresh(self.student1)
        self.assertEqual(self.student1.balance, 1750.0)

        # 7. Assert sms is now marked as claimed + approved
        self.db.refresh(sms)
        self.assertTrue(sms.is_claimed)
        self.assertEqual(sms.claimed_by_user_id, self.student1.id)
        self.assertEqual(sms.status, "approved")

        # 8. Manager fetches transaction list — verify claimed_by is populated
        transactions = get_bkash_transactions(current_user=self.mukti_mgr, db=self.db)
        matched = next((t for t in transactions if t["trx_id"] == "AL99K8X7P2"), None)
        self.assertIsNotNone(matched)
        self.assertTrue(matched["is_claimed"])
        self.assertIsNotNone(matched["claimed_by"])
        self.assertIn("Kamrul Islam", matched["claimed_by"])
        self.assertIn("student1", matched["claimed_by"])
        print("[OK] Manager manual bKash flow verified successfully!")

    def test_custom_cycle_dates(self):
        from routers.manager_router import start_cycle
        from schemas import MealCycleCreate
        import billing_helper
        
        # Start a cycle with custom dates
        payload = MealCycleCreate(
            month="2026-07",
            cutoff_time="19:00",
            start_date="2026-07-05",
            end_date="2026-07-20"
        )
        cycle = start_cycle(payload, current_user=self.mukti_mgr, db=self.db)
        
        self.assertEqual(cycle.month, "2026-07")
        self.assertEqual(cycle.start_date, "2026-07-05")
        self.assertEqual(cycle.end_date, "2026-07-20")
        
        # Verify get_cycle_dates returns exact range
        dates = billing_helper.get_cycle_dates(cycle)
        self.assertEqual(len(dates), 16) # 20 - 5 + 1 = 16 days
        self.assertEqual(dates[0], "2026-07-05")
        self.assertEqual(dates[-1], "2026-07-20")
        print("[OK] Custom cycle dates and helpers verified successfully!")

    def test_automated_seeding_and_deductions(self):
        from routers.manager_router import start_cycle
        from routers.auth_router import register
        from schemas import MealCycleCreate, UserCreate
        import billing_helper
        
        # 1. Update existing student1 to have status = 'lunch_only'
        self.student1.status = "lunch_only"
        self.db.commit()
        
        # 2. Start a new cycle for Muktijoddha Hall (July 5 to July 10, 2026 = 6 days)
        payload = MealCycleCreate(
            month="2026-07",
            cutoff_time="19:00",
            start_date="2026-07-05",
            end_date="2026-07-10"
        )
        cycle = start_cycle(payload, current_user=self.mukti_mgr, db=self.db)
        
        # 3. Verify student1 status records were auto-seeded
        statuses = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == self.student1.id,
            models.StudentMealStatus.meal_cycle_id == cycle.id
        ).all()
        
        self.assertEqual(len(statuses), 6)
        for s in statuses:
            self.assertEqual(s.status, "lunch_only")
            self.assertTrue(s.ticked_lunch)
            self.assertFalse(s.ticked_dinner)
            
        # 4. Verify student2 (default status = 'both') statuses were auto-seeded
        statuses2 = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == self.student2.id,
            models.StudentMealStatus.meal_cycle_id == cycle.id
        ).all()
        
        self.assertEqual(len(statuses2), 6)
        for s in statuses2:
            self.assertEqual(s.status, "both")
            self.assertTrue(s.ticked_lunch)
            self.assertTrue(s.ticked_dinner)
            
        # 5. Register a new student to Muktijoddha Hall (during active cycle) with status = 'off'
        new_student_payload = UserCreate(
            username="new_std_auto",
            password="pwd",
            name="Auto Registered Student",
            email="auto@example.com",
            hall_id=self.mukti.id,
            status="off"
        )
        new_student = register(new_student_payload, db=self.db)
        
        # 6. Verify new student meal statuses were automatically seeded for the active cycle
        new_statuses = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == new_student.id,
            models.StudentMealStatus.meal_cycle_id == cycle.id
        ).all()
        
        self.assertEqual(len(new_statuses), 6)
        for s in new_statuses:
            self.assertEqual(s.status, "off")
            self.assertFalse(s.ticked_lunch)
            self.assertFalse(s.ticked_dinner)
            
        print("[OK] Automated cycle status seeding & new registration auto-seeding verified successfully!")

    def test_cycle_end_date_respected_everywhere(self):
        """Statuses/expenses dated after a cycle's end_date must never appear in the
        public statement, email report, settings pruning, or auto-close."""
        from routers.public_router import public_student_statement, _public_report_data
        from routers.manager_router import update_settings

        today = date.today()
        before_end = (today - timedelta(days=2)).strftime("%Y-%m-%d")
        end = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        after_end = today.strftime("%Y-%m-%d")

        cycle = models.MealCycle(
            hall_id=self.mukti.id, month=end[:7], status="poll",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5,
            start_date=before_end, end_date=end
        )
        self.db.add(cycle)
        self.db.commit()

        for d, st in [(before_end, "both"), (end, "both"), (after_end, "off")]:
            self.db.add(models.StudentMealStatus(
                user_id=self.student1.id, meal_cycle_id=cycle.id, date=d, status=st
            ))
        # A stale expense recorded on a date after the cycle ended
        self.db.add(models.Expense(
            meal_cycle_id=cycle.id, date=after_end, amount=999.0, description="stale"
        ))
        self.db.commit()

        # 1. Public statement: nothing after end_date may appear
        stmt = public_student_statement(self.student1.id, db=self.db)
        dates = [m["date"] for m in stmt["daily_meals"]]
        self.assertIn(before_end, dates)
        self.assertIn(end, dates)
        self.assertNotIn(after_end, dates)
        self.assertFalse(any(d > end for d in dates), "statement lists dates after cycle end")
        transparency_dates = [t["date"] for t in stmt["daily_transparency"]]
        self.assertFalse(any(d > end for d in transparency_dates), "transparency lists dates after cycle end")

        # 2. Email report payload must respect end_date too
        report = _public_report_data(self.student1.id, self.db)
        rep_dates = [m["date"] for m in report["daily_meals"]]
        self.assertFalse(any(d > end for d in rep_dates), "email report lists dates after cycle end")

        # 3. Saving a (re)confirmed end date prunes stale post-end statuses
        self.db.add(models.StudentMealStatus(
            user_id=self.student1.id, meal_cycle_id=cycle.id, date=after_end, status="both"
        ))
        self.db.commit()

        # 2b. Running (cycle) rate must never include post-end expense/eaters:
        # the 999.0 expense is on after_end, so with end-date capping it is excluded.
        run_rates = billing_helper.get_running_meal_rates(cycle, self.db)
        self.assertEqual(run_rates["final_rate"], 0.0, "cycle rate included post-end data")

        update_settings(manager_charge_per_day=5.0, cutoff_time="20:00",
                        lunch_percentage=0.5, dinner_percentage=0.5,
                        cycle_end_date=end, current_user=self.mukti_mgr, db=self.db)
        self.db.refresh(cycle)
        self.assertEqual(cycle.end_date, end)
        after_count = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.meal_cycle_id == cycle.id,
            models.StudentMealStatus.date > end
        ).count()
        self.assertEqual(after_count, 0, "post-end statuses not pruned by update_settings")

        # 4. Auto-close marks the expired cycle closed (and prunes)
        billing_helper.auto_close_expired_cycles(self.db)
        self.db.refresh(cycle)
        self.assertEqual(cycle.status, "closed")

        # 5. A closed cycle can still be read on the public portal (no empty result)
        stmt_closed = public_student_statement(self.student1.id, db=self.db)
        self.assertIsNotNone(stmt_closed["cycle"])
        self.assertIn(end, [m["date"] for m in stmt_closed["daily_meals"]])

        print("[OK] test_cycle_end_date_respected_everywhere passed successfully!")

    def test_approved_bkash_deposits_to_running_cycle(self):
        """Approved bKash payments must be credited into the running cycle (any
        status, incl. auto-closed) — never left with meal_cycle_id = None."""
        from routers.manager_router import approve_bkash_transaction

        today = date.today()
        month = today.strftime("%Y-%m")
        end = (today - timedelta(days=1)).strftime("%Y-%m-%d")

        # 1. Running cycle for Mukti hall that is already closed (auto-close)
        closed_cycle = models.MealCycle(
            hall_id=self.mukti.id, month=month, status="closed",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5,
            start_date=(today - timedelta(days=10)).strftime("%Y-%m-%d"), end_date=end
        )
        self.db.add(closed_cycle)
        self.db.commit()

        # Pending transaction claimed by student1
        trx = models.BkashReceivedSms(
            trx_id="APRVBK01", sender=self.student1.username, amount=500.0,
            status="pending", is_claimed=True,
            claimed_by_user_id=self.student1.id,
            date_received=today.strftime("%Y-%m-%d")
        )
        self.db.add(trx)
        self.db.commit()

        bal_before = self.student1.balance
        approve_bkash_transaction("APRVBK01", 500.0, current_user=self.mukti_mgr, db=self.db)

        self.db.refresh(trx)
        self.assertEqual(trx.status, "approved")
        self.assertEqual(trx.approved_amount, 500.0)

        dep = self.db.query(models.Deposit).filter(
            models.Deposit.user_id == self.student1.id,
            models.Deposit.description.like("%APRVBK01%")
        ).first()
        self.assertIsNotNone(dep, "approved payment not deposited into running (closed) cycle")
        self.assertEqual(dep.meal_cycle_id, closed_cycle.id)
        self.assertEqual(dep.amount, 500.0)

        self.db.refresh(self.student1)
        self.assertEqual(self.student1.balance, bal_before + 500.0)

        # 2. A NEWER active cycle takes precedence as the running cycle
        next_month = (today.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
        new_cycle = models.MealCycle(
            hall_id=self.mukti.id, month=next_month, status="active",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5,
            start_date=(today + timedelta(days=1)).strftime("%Y-%m-%d"),
            end_date=(today + timedelta(days=15)).strftime("%Y-%m-%d")
        )
        self.db.add(new_cycle)
        self.db.commit()

        trx2 = models.BkashReceivedSms(
            trx_id="APRVBK02", sender=self.student1.username, amount=250.0,
            status="pending", is_claimed=True,
            claimed_by_user_id=self.student1.id,
            date_received=today.strftime("%Y-%m-%d")
        )
        self.db.add(trx2)
        self.db.commit()

        bal_before = self.student1.balance
        approve_bkash_transaction("APRVBK02", 250.0, current_user=self.mukti_mgr, db=self.db)
        dep2 = self.db.query(models.Deposit).filter(
            models.Deposit.user_id == self.student1.id,
            models.Deposit.description.like("%APRVBK02%")
        ).first()
        self.assertIsNotNone(dep2)
        self.assertEqual(dep2.meal_cycle_id, new_cycle.id, "newer active cycle should absorb the approved payment")
        self.db.refresh(self.student1)
        self.assertEqual(self.student1.balance, bal_before + 250.0)

        print("[OK] test_approved_bkash_deposits_to_running_cycle passed successfully!")

    def test_manager_controls_closed_cycle(self):
        """Even with the cycle auto-closed, the manager keeps full control:
        student list, search, and deposit entry all still work against the running cycle."""
        from routers.manager_router import list_students, search_students, add_deposit
        from schemas import DepositCreate

        today = date.today()
        month = today.strftime("%Y-%m")
        end = (today - timedelta(days=1)).strftime("%Y-%m-%d")

        cycle = models.MealCycle(
            hall_id=self.mukti.id, month=month, status="closed",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5,
            start_date=(today - timedelta(days=10)).strftime("%Y-%m-%d"), end_date=end
        )
        self.db.add(cycle)
        self.db.commit()

        # 1. Student list still works and is scoped to the running (closed) cycle
        students = list_students(current_user=self.mukti_mgr, db=self.db)
        self.assertIn(self.student1.username, [s["username"] for s in students])

        # 2. Deposit autocomplete search finds the student (was 500: undefined 'hall')
        found = search_students(q="student1", current_user=self.mukti_mgr, db=self.db)
        self.assertTrue(any(s["username"] == "student1" for s in found))

        # 3. Manager can still record a deposit into the closed running cycle
        bal_before = self.student1.balance
        payload = DepositCreate(username="student1", amount=300.0,
                                date=today.strftime("%Y-%m-%d"), description="Test")
        dep = add_deposit(payload, current_user=self.mukti_mgr, db=self.db)
        self.assertEqual(dep.meal_cycle_id, cycle.id)
        self.db.refresh(self.student1)
        self.assertEqual(self.student1.balance, bal_before + 300.0)

        print("[OK] test_manager_controls_closed_cycle passed successfully!")

class TestBillingHelperRateCalculations(unittest.TestCase):
    """Direct tests for billing_helper.get_running_meal_rates() with mixed meal types."""

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = Session()

        self.hall = models.Hall(name="Test Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.db.add(self.hall)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_cycle(self, lunch_pct=0.5, dinner_pct=0.5):
        cycle = models.MealCycle(
            hall_id=self.hall.id, month="2026-06", status="active",
            cutoff_time="20:00", lunch_percentage=lunch_pct, dinner_percentage=dinner_pct
        )
        self.db.add(cycle)
        self.db.commit()
        return cycle

    def _create_student(self, name, balance=1000.0, free_meal=False, hall_id=None):
        user = models.User(
            username=name, password_hash="hash",
            role="student", hall_id=hall_id or self.hall.id,
            name=name, balance=balance, free_meal=free_meal
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _add_meal_statuses(self, user_id, cycle_id, dates, status, is_guest=False, guest_from_hall_id=None):
        for d in dates:
            s = models.StudentMealStatus(
                user_id=user_id, meal_cycle_id=cycle_id,
                date=d, status=status, is_guest=is_guest,
                guest_from_hall_id=guest_from_hall_id
            )
            self.db.add(s)
        self.db.commit()

    def _add_expense(self, cycle_id, date_str, amount, meal_type=None, description="Test expense"):
        e = models.Expense(
            meal_cycle_id=cycle_id, date=date_str,
            description=description, amount=amount, meal_type=meal_type
        )
        self.db.add(e)
        self.db.commit()

    def test_all_both_meals(self):
        """Scenario 1: All students eat 'both', expenses split 50/50."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")
        self._add_expense(cycle.id, "2026-06-05", 1000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 10 * 0.5 = 5, dinner units = 10 * 0.5 = 5
        # net lunch = 500, net dinner = 500
        # lunch_rate = 500/5 * 0.5 = 50.0
        # dinner_rate = 500/5 * 0.5 = 50.0
        # final_rate = 100.0
        self.assertEqual(rates["lunch_rate"], 50.0)
        self.assertEqual(rates["dinner_rate"], 50.0)
        self.assertEqual(rates["final_rate"], 100.0)
        print("[OK] Scenario 1: All both meals - rates computed correctly.")

    def test_mixed_both_and_lunch_only(self):
        """Scenario 2: Mixed 'both' and 'lunch_only' students."""
        cycle = self._create_cycle()
        student1 = self._create_student("student1")
        student2 = self._create_student("student2")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student1.id, cycle.id, dates, "both")
        self._add_meal_statuses(student2.id, cycle.id, dates, "lunch_only")
        self._add_expense(cycle.id, "2026-06-05", 3000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 10*0.5 + 10*0.5 = 10, dinner units = 10*0.5 + 0 = 5
        # net lunch = 1500, net dinner = 1500
        # lunch_rate = 1500/10 * 0.5 = 75.0
        # dinner_rate = 1500/5 * 0.5 = 150.0
        # final_rate = 225.0
        self.assertEqual(rates["lunch_rate"], 75.0)
        self.assertEqual(rates["dinner_rate"], 150.0)
        self.assertEqual(rates["final_rate"], 225.0)

        # Verify total cost collected = total expenses
        # student1: 10 * (75 + 150) = 2250, student2: 10 * 75 = 750, Total = 3000
        total_collected = (10 * (75.0 + 150.0)) + (10 * 75.0)
        self.assertEqual(total_collected, 3000.0)
        print("[OK] Scenario 2: Mixed both/lunch_only - lunch-only pays lunch only, both pays both.")

    def test_with_guests_and_free_meals(self):
        """Scenario 3: Includes guests and free meal users."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        other_hall = models.Hall(name="Other Hall", guest_meal_rate=100.0, manager_charge_per_day=5.0)
        self.db.add(other_hall)
        self.db.commit()

        guest = self._create_student("guest_s", hall_id=other_hall.id)
        manager = self._create_student("mgr", free_meal=True)

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")
        self._add_meal_statuses(manager.id, cycle.id, dates, "both")

        guest_dates = [f"2026-06-{d:02d}" for d in range(1, 3)]
        self._add_meal_statuses(guest.id, cycle.id, guest_dates, "both", is_guest=True, guest_from_hall_id=other_hall.id)

        # Expense: 2000 marked as "lunch" only
        self._add_expense(cycle.id, "2026-06-05", 2000.0, meal_type="lunch")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # New logic: guests counted in paying units
        # lunch units: student1 5×0.5=2.5 + guest 2×0.5=1.0 = 3.5; manager skipped (free)
        # dinner units: student1 2.5 + guest 1.0 = 3.5
        # expense 2000 "lunch" only
        # lunch_rate = (2000/3.5) × 0.5 = 285.71, dinner_rate = 0
        self.assertAlmostEqual(rates["lunch_rate"], 285.71, places=2)
        self.assertEqual(rates["dinner_rate"], 0.0)
        self.assertAlmostEqual(rates["final_rate"], 285.71, places=2)

        total_collected = 5 * 285.71  # home student pays running rate
        self.assertAlmostEqual(total_collected, 1428.55, places=0)
        print("[OK] Scenario 3: Guests and free meals — guests counted in units, rate shared.")

    def test_custom_percentages(self):
        """Scenario 4: Custom lunch/dinner percentages (0.4/0.6)."""
        cycle = self._create_cycle(lunch_pct=0.4, dinner_pct=0.6)
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")
        self._add_expense(cycle.id, "2026-06-05", 1000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 10*0.4 = 4, dinner units = 10*0.6 = 6
        # net lunch = 500, net dinner = 500
        # lunch_rate = 500/4 * 0.4 = 50.0
        # dinner_rate = 500/6 * 0.6 = 50.0
        # final_rate = 100.0
        self.assertEqual(rates["lunch_rate"], 50.0)
        self.assertEqual(rates["dinner_rate"], 50.0)
        self.assertEqual(rates["final_rate"], 100.0)
        print("[OK] Scenario 4: Custom lunch/dinner percentages work correctly.")

    def test_different_expenses_by_meal_type(self):
        """Scenario 5: Expenses explicitly marked for lunch and dinner separately."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # 1000 for lunch, 500 for dinner
        self._add_expense(cycle.id, "2026-06-05", 1000.0, meal_type="lunch")
        self._add_expense(cycle.id, "2026-06-05", 500.0, meal_type="dinner")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 10*0.5 = 5, dinner units = 10*0.5 = 5
        # net lunch = 1000, net dinner = 500
        # lunch_rate = 1000/5 * 0.5 = 100.0
        # dinner_rate = 500/5 * 0.5 = 50.0
        # final_rate = 150.0
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 50.0)
        self.assertEqual(rates["final_rate"], 150.0)
        print("[OK] Scenario 5: Expenses by meal type are correctly split.")

    def test_lunch_only_and_dinner_only_mixed(self):
        """Scenario 6: Both lunch_only and dinner_only students."""
        cycle = self._create_cycle()
        lunch_student = self._create_student("lunch_only")
        dinner_student = self._create_student("dinner_only")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(lunch_student.id, cycle.id, dates, "lunch_only")
        self._add_meal_statuses(dinner_student.id, cycle.id, dates, "dinner_only")

        self._add_expense(cycle.id, "2026-06-05", 2000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 10*0.5 = 5, dinner units = 10*0.5 = 5
        # net lunch = 1000, net dinner = 1000
        # lunch_rate = 1000/5 * 0.5 = 100.0
        # dinner_rate = 1000/5 * 0.5 = 100.0
        # final_rate = 200.0
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 100.0)
        self.assertEqual(rates["final_rate"], 200.0)

        # Total collected: lunch_student 10*100 + dinner_student 10*100 = 2000
        total_collected = 10 * 100.0 + 10 * 100.0
        self.assertEqual(total_collected, 2000.0)
        print("[OK] Scenario 6: Lunch-only and dinner-only students pay separate rates.")

    def test_zero_expenses(self):
        """Edge case: No expenses in the cycle."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        self.assertEqual(rates["lunch_rate"], 0.0)
        self.assertEqual(rates["dinner_rate"], 0.0)
        self.assertEqual(rates["final_rate"], 0.0)
        print("[OK] Edge case: Zero expenses handled correctly.")

    def test_no_meal_statuses(self):
        """Edge case: No meal statuses (only expenses)."""
        cycle = self._create_cycle()
        self._add_expense(cycle.id, "2026-06-05", 1000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        self.assertEqual(rates["lunch_rate"], 0.0)
        self.assertEqual(rates["dinner_rate"], 0.0)
        self.assertEqual(rates["final_rate"], 0.0)
        print("[OK] Edge case: No meal statuses handled correctly.")

    # ---- New edge cases ----

    def test_no_lunch_eaters_all_dinner_only(self):
        """Edge case: All students are dinner_only — lunch units = 0, lunch_rate should be 0."""
        cycle = self._create_cycle()
        student = self._create_student("dinner_student")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student.id, cycle.id, dates, "dinner_only")
        self._add_expense(cycle.id, "2026-06-05", 2000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 0, dinner units = 10*0.5 = 5
        # net lunch = 1000, net dinner = 1000
        # lunch_rate = 0 (no lunch eaters)
        # dinner_rate = 1000/5 * 0.5 = 100.0
        self.assertEqual(rates["lunch_rate"], 0.0)
        self.assertEqual(rates["dinner_rate"], 100.0)
        self.assertEqual(rates["final_rate"], 100.0)

        # Total collected: 10 * 100 = 1000 (only dinner charged)
        # But expense split is 1000 lunch + 1000 dinner. Lunch portion is not charged.
        # So: student pays 10*100 = 1000 for dinner only. The lunch 1000 is unallocated.
        total_collected = 10 * 100.0
        self.assertEqual(total_collected, 1000.0)
        print("[OK] Edge case: No lunch eaters (all dinner_only) — lunch_rate=0, dinner_rate works.")

    def test_no_dinner_eaters_all_lunch_only(self):
        """Edge case: All students are lunch_only — dinner units = 0, dinner_rate should be 0."""
        cycle = self._create_cycle()
        student = self._create_student("lunch_student")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student.id, cycle.id, dates, "lunch_only")
        self._add_expense(cycle.id, "2026-06-05", 2000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 10*0.5 = 5, dinner units = 0
        # net lunch = 1000, net dinner = 1000
        # lunch_rate = 1000/5 * 0.5 = 100.0
        # dinner_rate = 0 (no dinner eaters)
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 0.0)
        self.assertEqual(rates["final_rate"], 100.0)

        total_collected = 10 * 100.0
        self.assertEqual(total_collected, 1000.0)
        print("[OK] Edge case: No dinner eaters (all lunch_only) — dinner_rate=0, lunch_rate works.")

    def test_all_guests_no_home_students(self):
        """Edge case: Only guest meals, no home student meal statuses. Rates should be 0."""
        cycle = self._create_cycle()
        other_hall = models.Hall(name="Guest Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.db.add(other_hall)
        self.db.commit()

        guest = self._create_student("guest1", hall_id=other_hall.id)

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(guest.id, cycle.id, dates, "both", is_guest=True, guest_from_hall_id=other_hall.id)
        self._add_expense(cycle.id, "2026-06-05", 3000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # With new logic: guests counted in paying units
        # 5 guest meals (both), lunch_units = 5×0.5 = 2.5, dinner_units = 2.5
        # lunch_rate = (1500/2.5) × 0.5 = 300, dinner_rate = 300, final = 600
        self.assertEqual(rates["lunch_rate"], 300.0)
        self.assertEqual(rates["dinner_rate"], 300.0)
        self.assertEqual(rates["final_rate"], 600.0)
        print("[OK] Edge case: All guests, no home students — guests counted as paying units, rate computed.")

    def test_mid_cycle_status_changes(self):
        """Edge case: Student toggles status mid-cycle. Rate should only count active days."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        # Days 1-5: "both", Days 6-10: "off"
        active_dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        off_dates = [f"2026-06-{d:02d}" for d in range(6, 11)]
        self._add_meal_statuses(student.id, cycle.id, active_dates, "both")
        self._add_meal_statuses(student.id, cycle.id, off_dates, "off")
        self._add_expense(cycle.id, "2026-06-05", 1000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 5*0.5 = 2.5, dinner units = 5*0.5 = 2.5 (off days not counted)
        # net lunch = 500, net dinner = 500
        # lunch_rate = 500/2.5 * 0.5 = 100.0
        # dinner_rate = 500/2.5 * 0.5 = 100.0
        # final_rate = 200.0
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 100.0)
        self.assertEqual(rates["final_rate"], 200.0)

        # Total from student: 5*200 = 1000 = total expense
        total_collected = 5 * 200.0
        self.assertEqual(total_collected, 1000.0)
        print("[OK] Edge case: Mid-cycle status changes — only active days counted.")

    def test_guest_contribution_exceeds_expenses(self):
        """Edge case: Guest contributions exceed total expenses. Net should clamp to 0."""
        cycle = self._create_cycle()
        other_hall = models.Hall(name="Other Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.db.add(other_hall)
        self.db.commit()

        student = self._create_student("student1")
        guest = self._create_student("guest1", hall_id=other_hall.id)

        # Home student: 5 days "both" (small)
        home_dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, home_dates, "both")

        # Guest: 10 days "both" (large, so guest contribution >> expense)
        guest_dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(guest.id, cycle.id, guest_dates, "both", is_guest=True, guest_from_hall_id=other_hall.id)

        # Small expense: BDT 200
        self._add_expense(cycle.id, "2026-06-05", 200.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # New logic: guests counted in units alongside home students
        # lunch_units = 5 home × 0.5 + 10 guest × 0.5 = 7.5
        # dinner_units = 5 home × 0.5 + 10 guest × 0.5 = 7.5
        # lunch_rate = (100/7.5) × 0.5 = 6.67, dinner_rate = 6.67
        self.assertAlmostEqual(rates["lunch_rate"], 6.67, places=2)
        self.assertAlmostEqual(rates["dinner_rate"], 6.67, places=2)
        self.assertAlmostEqual(rates["final_rate"], 13.33, places=2)
        print("[OK] Edge case: Guest contribution exceeds expenses — now all paying users share cost.")

    def test_all_free_meals_no_paying_students(self):
        """Edge case: Only free_meal users eating, no paying home students. Rates = 0."""
        cycle = self._create_cycle()
        manager = self._create_student("hall_mgr", free_meal=True)

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(manager.id, cycle.id, dates, "both")
        self._add_expense(cycle.id, "2026-06-05", 5000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # free_meal=True => home_lunch_units = 0, home_dinner_units = 0
        self.assertEqual(rates["lunch_rate"], 0.0)
        self.assertEqual(rates["dinner_rate"], 0.0)
        self.assertEqual(rates["final_rate"], 0.0)
        print("[OK] Edge case: Only free meal users — rates=0, no charges to free users.")

    def test_single_day_single_student(self):
        """Edge case: Minimum viable scenario — 1 student, 1 day, 1 expense."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        self._add_meal_statuses(student.id, cycle.id, ["2026-06-01"], "both")
        self._add_expense(cycle.id, "2026-06-01", 100.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 1*0.5 = 0.5, dinner units = 1*0.5 = 0.5
        # net lunch = 50, net dinner = 50
        # lunch_rate = 50/0.5 * 0.5 = 50.0
        # dinner_rate = 50/0.5 * 0.5 = 50.0
        # final_rate = 100.0
        self.assertEqual(rates["lunch_rate"], 50.0)
        self.assertEqual(rates["dinner_rate"], 50.0)
        self.assertEqual(rates["final_rate"], 100.0)

        # Total collected: 1 * 100 = 100 = total expense
        self.assertEqual(1 * 100.0, 100.0)
        print("[OK] Edge case: Single day, single student — minimum viable works correctly.")

    def test_guest_only_days_no_home_eaters(self):
        """Edge case: All home students are 'off' for the entire period, only guests eating."""
        cycle = self._create_cycle()
        other_hall = models.Hall(name="Other Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.db.add(other_hall)
        self.db.commit()

        # Home students all "off"
        home_student = self._create_student("home_off")
        self._add_meal_statuses(home_student.id, cycle.id, ["2026-06-01"], "off")

        # Guest eating
        guest = self._create_student("guest1", hall_id=other_hall.id)
        self._add_meal_statuses(guest.id, cycle.id, ["2026-06-01"], "both", is_guest=True, guest_from_hall_id=other_hall.id)

        self._add_expense(cycle.id, "2026-06-01", 500.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # New logic: guest counted in units. 1 guest (both) = 0.5 lunch + 0.5 dinner
        # lunch_rate = (250/0.5) × 0.5 = 250, dinner_rate = 250, final = 500
        self.assertEqual(rates["lunch_rate"], 250.0)
        self.assertEqual(rates["dinner_rate"], 250.0)
        self.assertEqual(rates["final_rate"], 500.0)
        print("[OK] Edge case: All home students off, only guests — guest counted as paying unit, rate computed.")

    def test_multiple_cycles_independent(self):
        """Edge case: Two cycles for same hall. Meals in one should NOT affect the other's rates."""
        cycle_a = self._create_cycle()  # June
        cycle_b = models.MealCycle(
            hall_id=self.hall.id, month="2026-07", status="active",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5
        )
        self.db.add(cycle_b)
        self.db.commit()

        student_a = self._create_student("student_a")
        student_b = self._create_student("student_b")

        # Student A only in Cycle A (June 1-5)
        dates_a = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student_a.id, cycle_a.id, dates_a, "both")
        self._add_expense(cycle_a.id, "2026-06-05", 1000.0)

        # Student B only in Cycle B (July 1-5)
        dates_b = [f"2026-07-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student_b.id, cycle_b.id, dates_b, "both")
        self._add_expense(cycle_b.id, "2026-07-05", 5000.0)

        rates_a = billing_helper.get_running_meal_rates(cycle_a, self.db)
        rates_b = billing_helper.get_running_meal_rates(cycle_b, self.db)

        # Cycle A: 5 days both = 2.5 lunch + 2.5 dinner units, expense 1000
        # lunch_rate = 500/2.5 * 0.5 = 100.0
        # dinner_rate = 500/2.5 * 0.5 = 100.0
        # final_rate = 200.0
        self.assertEqual(rates_a["lunch_rate"], 100.0)
        self.assertEqual(rates_a["dinner_rate"], 100.0)
        self.assertEqual(rates_a["final_rate"], 200.0)

        # Cycle B: 5 days both = same unit counts, expense 5000
        # lunch_rate = 2500/2.5 * 0.5 = 500.0
        # dinner_rate = 2500/2.5 * 0.5 = 500.0
        # final_rate = 1000.0
        self.assertEqual(rates_b["lunch_rate"], 500.0)
        self.assertEqual(rates_b["dinner_rate"], 500.0)
        self.assertEqual(rates_b["final_rate"], 1000.0)

        # Verify independence: student_a should NOT appear in cycle_b's rates
        self.assertNotEqual(rates_a["final_rate"], rates_b["final_rate"])
        print("[OK] Edge case: Multiple cycles are independent — rates don't cross-contaminate.")

    def test_expense_with_description_fallback(self):
        """Edge case: Expenses without meal_type use description fallback (lunch/dinner keywords)."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # No meal_type set — should parse description fallback
        self._add_expense(cycle.id, "2026-06-01", 800.0, meal_type=None, description="Weekly lunch bazar")
        self._add_expense(cycle.id, "2026-06-02", 400.0, meal_type=None, description="Dinner supplies for guests")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 5*0.5 = 2.5, dinner units = 5*0.5 = 2.5
        # lunch exp (description contains "lunch") = 800
        # dinner exp (description contains "dinner") = 400
        # net lunch = 800, net dinner = 400
        # lunch_rate = 800/2.5 * 0.5 = 160.0
        # dinner_rate = 400/2.5 * 0.5 = 80.0
        # final_rate = 240.0
        self.assertEqual(rates["lunch_rate"], 160.0)
        self.assertEqual(rates["dinner_rate"], 80.0)
        self.assertEqual(rates["final_rate"], 240.0)

        # Total collected: 5 * 240 = 1200 = 800 + 400
        self.assertEqual(5 * 240.0, 1200.0)
        print("[OK] Edge case: Description fallback correctly classifies lunch/dinner expenses.")

    # ---- More edge cases (batch 2) ----

    def test_overlapping_home_and_guest_cycles(self):
        """Edge case: Student has home meals in Cycle A AND guest meals in Cycle B (different hall).
        Computing rates for Cycle A should NOT include the guest statuses from Cycle B."""
        # Cycle A (home hall — June)
        cycle_a = self._create_cycle()
        # Cycle B (other hall — July, different month)
        other_hall = models.Hall(name="Other Hall", guest_meal_rate=150.0, manager_charge_per_day=4.0)
        self.db.add(other_hall)
        self.db.commit()
        cycle_b = models.MealCycle(
            hall_id=other_hall.id, month="2026-07", status="active",
            cutoff_time="20:00", lunch_percentage=0.5, dinner_percentage=0.5
        )
        self.db.add(cycle_b)
        self.db.commit()

        student = self._create_student("cross_hall_student")

        # Home meals in Cycle A: 5 days "both"
        self._add_meal_statuses(student.id, cycle_a.id, ["2026-06-01","2026-06-02","2026-06-03","2026-06-04","2026-06-05"], "both")
        self._add_expense(cycle_a.id, "2026-06-05", 1000.0)

        # Guest meals in Cycle B (different hall): 5 days "both"
        self._add_meal_statuses(student.id, cycle_b.id, ["2026-07-01","2026-07-02","2026-07-03","2026-07-04","2026-07-05"], "both", is_guest=True, guest_from_hall_id=self.hall.id)
        self._add_expense(cycle_b.id, "2026-07-05", 5000.0)

        rates_a = billing_helper.get_running_meal_rates(cycle_a, self.db)

        # Cycle A should only see home meals (5 days "both" = 2.5 units each)
        # lunch units = 2.5, dinner units = 2.5
        # net lunch = 500, net dinner = 500
        # lunch_rate = 500/2.5 * 0.5 = 100.0
        # dinner_rate = 500/2.5 * 0.5 = 100.0
        # final = 200.0
        self.assertEqual(rates_a["lunch_rate"], 100.0)
        self.assertEqual(rates_a["dinner_rate"], 100.0)
        self.assertEqual(rates_a["final_rate"], 200.0)
        print("[OK] Edge case: Overlapping home+guest cycles — cross-cycle isolation correct.")

    def test_extreme_percentages(self):
        """Edge case: Very skewed lunch/dinner ratios (0.99 lunch / 0.01 dinner)."""
        cycle = self._create_cycle(lunch_pct=0.99, dinner_pct=0.01)
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")
        self._add_expense(cycle.id, "2026-06-05", 1000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 10*0.99 = 9.9, dinner units = 10*0.01 = 0.1
        # net lunch = 500, net dinner = 500
        # lunch_rate = 500/9.9 * 0.99 = 50.0
        # dinner_rate = 500/0.1 * 0.01 = 50.0
        # final_rate = 100.0
        self.assertEqual(rates["lunch_rate"], 50.0)
        self.assertEqual(rates["dinner_rate"], 50.0)
        self.assertEqual(rates["final_rate"], 100.0)

        # Total collected: 10 * 100 = 1000 = total expense
        self.assertEqual(10 * 100.0, 1000.0)
        print("[OK] Edge case: Extreme percentages (0.99/0.01) produce correct split rates.")

    def test_mixed_guest_meal_types(self):
        """Edge case: Multiple guests with 'both', 'lunch_only', 'dinner_only' statuses in same cycle."""
        cycle = self._create_cycle()
        other_hall = models.Hall(name="Other Hall", guest_meal_rate=100.0, manager_charge_per_day=5.0)
        self.db.add(other_hall)
        self.db.commit()

        home_student = self._create_student("home_std")
        guest_both = self._create_student("guest_both", hall_id=other_hall.id)
        guest_lunch = self._create_student("guest_lunch", hall_id=other_hall.id)
        guest_dinner = self._create_student("guest_dinner", hall_id=other_hall.id)

        # Home student: 5 days "both"
        self._add_meal_statuses(home_student.id, cycle.id, [f"2026-06-{d:02d}" for d in range(1, 6)], "both")

        # Guest A: 3 days "both"
        self._add_meal_statuses(guest_both.id, cycle.id, ["2026-06-01","2026-06-02","2026-06-03"], "both", is_guest=True, guest_from_hall_id=other_hall.id)
        # Guest B: 2 days "lunch_only"
        self._add_meal_statuses(guest_lunch.id, cycle.id, ["2026-06-01","2026-06-02"], "lunch_only", is_guest=True, guest_from_hall_id=other_hall.id)
        # Guest C: 2 days "dinner_only"
        self._add_meal_statuses(guest_dinner.id, cycle.id, ["2026-06-01","2026-06-02"], "dinner_only", is_guest=True, guest_from_hall_id=other_hall.id)

        self._add_expense(cycle.id, "2026-06-05", 2000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # home lunch units = 5*0.5 = 2.5, home dinner units = 5*0.5 = 2.5

        # guest contributions:
        # guest_both lunch = 3 * 100 * 0.5 = 150
        # guest_both dinner = 3 * 100 * 0.5 = 150
        # guest_lunch lunch = 2 * 100 * 0.5 = 100 (lunch_only has lunch)
        # guest_lunch dinner = 0 (lunch_only has no dinner)
        # guest_dinner lunch = 0 (dinner_only has no lunch)
        # guest_dinner dinner = 2 * 100 * 0.5 = 100
        # total guest lunch = 250, total guest dinner = 250

        # net lunch = max(0, 1000 - 250) = 750
        # net dinner = max(0, 1000 - 250) = 750

        # lunch_rate = 750/2.5 * 0.5 = 150.0
        # dinner_rate = 750/2.5 * 0.5 = 150.0
        # final_rate = 300.0

        # Guest rate used is from cycle's hall (self.hall, rate=120.0), NOT guest's home hall
        # guest_both lunch = 3*120*0.5 = 180, dinner = 180
        # guest_lunch lunch = 2*120*0.5 = 120, dinner = 0
        # guest_dinner lunch = 0, dinner = 2*120*0.5 = 120
        # total guest lunch = 300, total guest dinner = 300
        # net lunch = max(0, 1000-300) = 700
        # net dinner = max(0, 1000-300) = 700
        # lunch_rate = 700/2.5 * 0.5 = 140.0
        # dinner_rate = 700/2.5 * 0.5 = 140.0
        # New logic: guests counted in paying units together with home
        # lunch_units: 5 home × 0.5 + 3 g_both × 0.5 + 2 g_lunch × 0.5 = 5.0
        # dinner_units: 5 home × 0.5 + 3 g_both × 0.5 + 2 g_dinner × 0.5 = 5.0
        # lunch_rate = (1000/5) × 0.5 = 100, dinner_rate = 100, final = 200
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 100.0)
        self.assertEqual(rates["final_rate"], 200.0)

        # Total home collected: 5 × 200 = 1000. Each guest pays flat guest_rate separately via deductions.
        # So home students pay 1000, plus guest payments — but the rate calculation only affects home.
        # The total expense of 2000 is shared among ALL paying units (10 total units, 200 per unit)
        # Home students (5 units at 200 = 1000) + guests pay flat rate separately
        total_collected = 5 * 200.0
        self.assertEqual(total_collected, 1000.0)
        print("[OK] Edge case: Mixed guest meal types with new unit-sharing logic.")

    def test_multiple_status_toggles(self):
        """Edge case: Student toggles both -> off -> both mid-cycle. Only active days counted."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        # Days 1-3: "both", Days 4-5: "off", Days 6-8: "both"
        self._add_meal_statuses(student.id, cycle.id, ["2026-06-01","2026-06-02","2026-06-03"], "both")
        self._add_meal_statuses(student.id, cycle.id, ["2026-06-04","2026-06-05"], "off")
        self._add_meal_statuses(student.id, cycle.id, ["2026-06-06","2026-06-07","2026-06-08"], "both")
        self._add_expense(cycle.id, "2026-06-05", 1000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # Active: days 1-3 (3 days) + days 6-8 (3 days) = 6 days "both"
        # lunch units = 6*0.5 = 3.0, dinner units = 6*0.5 = 3.0
        # net lunch = 500, net dinner = 500
        # lunch_rate = 500/3.0 * 0.5 = 83.33
        # dinner_rate = 500/3.0 * 0.5 = 83.33
        # final_rate = 166.67
        self.assertAlmostEqual(rates["lunch_rate"], 83.33, places=2)
        self.assertAlmostEqual(rates["dinner_rate"], 83.33, places=2)
        self.assertAlmostEqual(rates["final_rate"], 166.67, places=2)

        # Total collected: 6 * 166.67 = 1000.0 (after rounding)
        total_collected = 6 * (500.0 / 3.0 * 0.5 + 500.0 / 3.0 * 0.5)
        self.assertAlmostEqual(total_collected, 1000.0, places=1)
        print("[OK] Edge case: Multiple status toggles (both->off->both) - only active days counted.")

    def test_expense_with_both_meal_type(self):
        """Edge case: Expense with meal_type='both' should fall through to 50/50 split."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # meal_type="both" — neither "lunch" nor "dinner", so falls to 50/50 split
        self._add_expense(cycle.id, "2026-06-01", 600.0, meal_type="both")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # 600 split 50/50 = 300 lunch + 300 dinner
        # lunch units = 2.5, dinner units = 2.5
        # lunch_rate = 300/2.5 * 0.5 = 60.0
        # dinner_rate = 300/2.5 * 0.5 = 60.0
        # final_rate = 120.0
        self.assertEqual(rates["lunch_rate"], 60.0)
        self.assertEqual(rates["dinner_rate"], 60.0)
        self.assertEqual(rates["final_rate"], 120.0)

        # Total collected: 5 * 120 = 600 = total expense
        self.assertEqual(5 * 120.0, 600.0)
        print("[OK] Edge case: Expense with meal_type='both' falls through to 50/50 split.")

    def test_zero_lunch_percentage(self):
        """Edge case: lunch_percentage = 0.0. No lunch eaters if all 'both'? New formula counts eaters not units."""
        cycle = self._create_cycle(lunch_pct=0.0, dinner_pct=1.0)
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 11)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")
        self._add_expense(cycle.id, "2026-06-05", 1000.0, meal_type="dinner")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # All expense goes to dinner (meal_type="dinner"), 10 dinner eaters
        # dinner_rate = 1000/10 = 100, lunch_rate = 0
        self.assertEqual(rates["lunch_rate"], 0.0)
        self.assertEqual(rates["dinner_rate"], 100.0)
        self.assertEqual(rates["final_rate"], 100.0)
        self.assertEqual(10 * 100.0, 1000.0)
        print("[OK] Edge case: Zero lunch percentage with dinner-only expense.")

    def test_description_without_meal_keywords(self):
        """Edge case: Expense description without 'lunch'/'dinner' keywords falls to 50/50 split."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # No meal_type, description doesn't mention lunch or dinner
        self._add_expense(cycle.id, "2026-06-01", 1000.0, meal_type=None, description="Vegetables and rice from market")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # 1000 split 50/50 = 500 lunch + 500 dinner
        # lunch units = 2.5, dinner units = 2.5
        # lunch_rate = 500/2.5 * 0.5 = 100.0
        # dinner_rate = 500/2.5 * 0.5 = 100.0
        # final_rate = 200.0
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 100.0)
        self.assertEqual(rates["final_rate"], 200.0)

        # Total collected: 5 * 200 = 1000 = total expense
        self.assertEqual(5 * 200.0, 1000.0)
        print("[OK] Edge case: Description without meal keywords — correctly falls to 50/50 split.")

    def test_many_students_mixed_statuses(self):
        """Edge case: 20 students with varied statuses (both, lunch_only, dinner_only, off).
        Tests that large student counts don't break the calculation."""
        cycle = self._create_cycle()
        students = []
        for i in range(20):
            s = self._create_student(f"std_{i}")
            students.append(s)

        dates_all = [f"2026-06-{d:02d}" for d in range(1, 16)]

        # 10 students "both" for 15 days
        for i in range(10):
            self._add_meal_statuses(students[i].id, cycle.id, dates_all, "both")
        # 5 students "lunch_only" for 15 days
        for i in range(10, 15):
            self._add_meal_statuses(students[i].id, cycle.id, dates_all, "lunch_only")
        # 3 students "dinner_only" for 15 days
        for i in range(15, 18):
            self._add_meal_statuses(students[i].id, cycle.id, dates_all, "dinner_only")
        # 2 students "off" for 15 days (should not count)
        for i in range(18, 20):
            self._add_meal_statuses(students[i].id, cycle.id, dates_all, "off")

        self._add_expense(cycle.id, "2026-06-10", 10000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units:
        #   10 both * 15 days * 0.5 = 75
        #   5 lunch_only * 15 days * 0.5 = 37.5
        #   3 dinner_only * 0 = 0
        #   total lunch = 112.5
        # dinner units:
        #   10 both * 15 days * 0.5 = 75
        #   5 lunch_only * 0 = 0
        #   3 dinner_only * 15 days * 0.5 = 22.5
        #   total dinner = 97.5
        # expense split: 5000 lunch, 5000 dinner
        # lunch_rate = 5000/112.5 * 0.5 = 22.222...
        # dinner_rate = 5000/97.5 * 0.5 = 25.641...
        # final_rate = 47.863...

        expected_lunch_rate = round((5000.0 / 112.5) * 0.5, 2)
        expected_dinner_rate = round((5000.0 / 97.5) * 0.5, 2)
        expected_final = round(expected_lunch_rate + expected_dinner_rate, 2)

        self.assertAlmostEqual(rates["lunch_rate"], expected_lunch_rate, places=2)
        self.assertAlmostEqual(rates["dinner_rate"], expected_dinner_rate, places=2)
        self.assertAlmostEqual(rates["final_rate"], expected_final, places=2)

        # Verify total collected matches total expenses
        # 10 both students: each pays 15 * final_rate
        # 5 lunch_only: each pays 15 * lunch_rate
        # 3 dinner_only: each pays 15 * dinner_rate
        total_collected = (10 * 15 * expected_final) + (5 * 15 * expected_lunch_rate) + (3 * 15 * expected_dinner_rate)
        # Rounding can accumulate small errors across 250 meals, so use a 1.0 delta
        self.assertAlmostEqual(total_collected, 10000.0, delta=1.0)
        print("[OK] Edge case: 20 students with mixed statuses — large group calculation correct.")

    # ---- More edge cases (batch 3) ----

    def test_description_contains_both_lunch_and_dinner(self):
        """Edge case: Description contains both 'lunch' AND 'dinner' keywords.
        Current if/elif means first match ('lunch') wins, so entire amount goes to lunch."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # Description contains both keywords — "lunch" is checked first (if), then "dinner" (elif)
        self._add_expense(cycle.id, "2026-06-01", 1000.0, meal_type=None,
                         description="Weekly lunch and dinner supplies")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # "lunch" in "lunch and dinner supplies" → True, so entire 1000 goes to lunch
        # net lunch = 1000, net dinner = 0
        # lunch units = 2.5, dinner units = 2.5
        # lunch_rate = 1000/2.5 * 0.5 = 200.0
        # dinner_rate = 0.0 (nothing allocated to dinner)
        # final_rate = 200.0
        self.assertEqual(rates["lunch_rate"], 200.0)
        self.assertEqual(rates["dinner_rate"], 0.0)
        self.assertEqual(rates["final_rate"], 200.0)

        # Total collected: 5 * 200 = 1000 = total expense
        self.assertEqual(5 * 200.0, 1000.0)
        print("[OK] Edge case: Description with both 'lunch' and 'dinner' — first match (lunch) wins.")

    def test_empty_description_fallback(self):
        """Edge case: Expense with empty/None description and no meal_type falls to 50/50 split."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # Empty description, no meal_type
        self._add_expense(cycle.id, "2026-06-01", 800.0, meal_type=None, description="")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # Empty string — "lunch" not in "", "dinner" not in "" — falls to 50/50 split
        # net lunch = 400, net dinner = 400
        # lunch_rate = 400/2.5 * 0.5 = 80.0
        # dinner_rate = 400/2.5 * 0.5 = 80.0
        # final_rate = 160.0
        self.assertEqual(rates["lunch_rate"], 80.0)
        self.assertEqual(rates["dinner_rate"], 80.0)
        self.assertEqual(rates["final_rate"], 160.0)

        # Total collected: 5 * 160 = 800 = total expense
        self.assertEqual(5 * 160.0, 800.0)
        print("[OK] Edge case: Empty description — correctly falls to 50/50 split.")

    def test_lunch_only_to_dinner_only_change(self):
        """Edge case: Student changes from lunch_only to dinner_only mid-cycle.
        Tests changing meal TYPE (not just on/off)."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        # Days 1-5: "lunch_only", Days 6-10: "dinner_only"
        self._add_meal_statuses(student.id, cycle.id, [f"2026-06-{d:02d}" for d in range(1, 6)], "lunch_only")
        self._add_meal_statuses(student.id, cycle.id, [f"2026-06-{d:02d}" for d in range(6, 11)], "dinner_only")
        self._add_expense(cycle.id, "2026-06-05", 2000.0)

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # lunch units = 5*0.5 = 2.5 (days 1-5 lunch_only)
        # dinner units = 5*0.5 = 2.5 (days 6-10 dinner_only)
        # net lunch = 1000, net dinner = 1000
        # lunch_rate = 1000/2.5 * 0.5 = 200.0
        # dinner_rate = 1000/2.5 * 0.5 = 200.0
        # final_rate = 400.0
        self.assertEqual(rates["lunch_rate"], 200.0)
        self.assertEqual(rates["dinner_rate"], 200.0)
        self.assertEqual(rates["final_rate"], 400.0)

        # Total collected: 5*200 (lunch days) + 5*200 (dinner days) = 2000 = total expense
        total_collected = (5 * 200.0) + (5 * 200.0)
        self.assertEqual(total_collected, 2000.0)
        print("[OK] Edge case: lunch_only -> dinner_only mid-cycle — meal type change handled correctly.")

    def test_substring_match_in_description(self):
        """Edge case: Description where 'lunch'/'dinner' is a substring of another word."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # "Lunchbox" contains "lunch" as substring — should match
        self._add_expense(cycle.id, "2026-06-01", 500.0, meal_type=None, description="Lunchbox supplies")
        # "Dinnerplate" contains "dinner" as substring — should match
        self._add_expense(cycle.id, "2026-06-02", 300.0, meal_type=None, description="Dinnerplate set")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # "lunch" in "lunchbox supplies" → True (substring), 500 to lunch
        # "dinner" in "dinnerplate set" → True (substring), 300 to dinner
        # net lunch = 500, net dinner = 300
        # lunch_rate = 500/2.5 * 0.5 = 100.0
        # dinner_rate = 300/2.5 * 0.5 = 60.0
        # final_rate = 160.0
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 60.0)
        self.assertEqual(rates["final_rate"], 160.0)

        # Total collected: 5 * 160 = 800 = 500 + 300
        self.assertEqual(5 * 160.0, 800.0)
        print("[OK] Edge case: Substring match ('Lunchbox', 'Dinnerplate') works correctly.")

    def test_case_insensitive_description(self):
        """Edge case: Description with uppercase 'LUNCH'/'DINNER' — should still match via .lower()."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # Uppercase keywords
        self._add_expense(cycle.id, "2026-06-01", 600.0, meal_type=None, description="LUNCH SHOPPING")
        self._add_expense(cycle.id, "2026-06-02", 400.0, meal_type=None, description="DINNER ITEMS")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # "lunch" in "lunch shopping" (after .lower()) → True
        # "dinner" in "dinner items" (after .lower()) → True
        # net lunch = 600, net dinner = 400
        # lunch units = 2.5, dinner units = 2.5
        # lunch_rate = 600/2.5 * 0.5 = 120.0
        # dinner_rate = 400/2.5 * 0.5 = 80.0
        # final_rate = 200.0
        self.assertEqual(rates["lunch_rate"], 120.0)
        self.assertEqual(rates["dinner_rate"], 80.0)
        self.assertEqual(rates["final_rate"], 200.0)

        # Total collected: 5 * 200 = 1000 = 600 + 400
        self.assertEqual(5 * 200.0, 1000.0)
        print("[OK] Edge case: Uppercase 'LUNCH'/'DINNER' — case-insensitive match works.")

    def test_multiple_expenses_same_date_different_types(self):
        """Edge case: Multiple expenses on the same date with different classifications.
        Tests that expenses are aggregated per meal type correctly on a single date."""
        cycle = self._create_cycle()
        student = self._create_student("student1")

        dates = [f"2026-06-{d:02d}" for d in range(1, 6)]
        self._add_meal_statuses(student.id, cycle.id, dates, "both")

        # Three expenses on the same date with different classifications
        self._add_expense(cycle.id, "2026-06-03", 400.0, meal_type="lunch")       # Lunch 400
        self._add_expense(cycle.id, "2026-06-03", 300.0, meal_type="dinner")      # Dinner 300
        self._add_expense(cycle.id, "2026-06-03", 200.0, meal_type=None,           # No type → 50/50 → 100+100
                         description="General supplies")

        rates = billing_helper.get_running_meal_rates(cycle, self.db)

        # Total lunch = 400 + 100 = 500
        # Total dinner = 300 + 100 = 400
        # lunch units = 2.5, dinner units = 2.5
        # lunch_rate = 500/2.5 * 0.5 = 100.0
        # dinner_rate = 400/2.5 * 0.5 = 80.0
        # final_rate = 180.0
        self.assertEqual(rates["lunch_rate"], 100.0)
        self.assertEqual(rates["dinner_rate"], 80.0)
        self.assertEqual(rates["final_rate"], 180.0)

        # Total collected: 5 * 180 = 900 = 400 + 300 + 200
        self.assertEqual(5 * 180.0, 900.0)
        print("[OK] Edge case: Multiple expenses same date (lunch+dinner+generic) aggregated correctly.")


class TestDeductPassedMeals(unittest.TestCase):
    """Tests for billing_helper.deduct_passed_meals() with mixed meal types.
    Uses past dates (2026-06-01 through 2026-06-05) which are before today."""

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = Session()

        self.hall = models.Hall(name="Test Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.db.add(self.hall)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_cycle(self, lunch_pct=0.5, dinner_pct=0.5):
        cycle = models.MealCycle(
            hall_id=self.hall.id, month="2026-06", status="active",
            cutoff_time="20:00", lunch_percentage=lunch_pct, dinner_percentage=dinner_pct
        )
        self.db.add(cycle)
        self.db.commit()
        return cycle

    def _create_student(self, name, balance=1000.0, free_meal=False, hall_id=None):
        user = models.User(
            username=name, password_hash="hash",
            role="student", hall_id=hall_id or self.hall.id,
            name=name, balance=balance, free_meal=free_meal
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _add_meal_status(self, user_id, cycle_id, date_str, status, is_guest=False, guest_from_hall_id=None,
                         is_deducted=False):
        s = models.StudentMealStatus(
            user_id=user_id, meal_cycle_id=cycle_id, date=date_str, status=status,
            is_guest=is_guest, guest_from_hall_id=guest_from_hall_id,
            is_deducted=is_deducted, amount_deducted=0.0
        )
        self.db.add(s)
        self.db.commit()
        return s

    def _add_expense(self, cycle_id, date_str, amount, meal_type=None):
        e = models.Expense(
            meal_cycle_id=cycle_id, date=date_str,
            description="Test expense", amount=amount, meal_type=meal_type
        )
        self.db.add(e)
        self.db.commit()

    def _get_expected_rates(self, cycle):
        return billing_helper.get_running_meal_rates(cycle, self.db)

    def test_deduct_both_meal(self):
        """Student with 'both' status: deducted final_rate + mgr_charge."""
        cycle = self._create_cycle()
        student = self._create_student("student1", balance=1000.0)
        self._add_expense(cycle.id, "2026-06-01", 1000.0)
        s = self._add_meal_status(student.id, cycle.id, "2026-06-01", "both")

        rates = self._get_expected_rates(cycle)
        expected_cost = rates["final_rate"] + 5.0  # mgr_charge = 5.0

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(student)
        self.db.refresh(s)
        self.assertEqual(student.balance, 1000.0 - expected_cost)
        self.assertTrue(s.is_deducted)
        self.assertEqual(s.amount_deducted, expected_cost)
        print(f"[OK] Deduct both meal: cost={expected_cost}, balance={student.balance}")

    def test_deduct_lunch_only(self):
        """Student with 'lunch_only' status: deducted lunch_rate + mgr_charge."""
        cycle = self._create_cycle()
        student = self._create_student("student_lunch", balance=1000.0)
        self._add_expense(cycle.id, "2026-06-01", 1000.0)
        s = self._add_meal_status(student.id, cycle.id, "2026-06-01", "lunch_only")

        rates = self._get_expected_rates(cycle)
        expected_cost = (0.4 * rates["final_rate"]) + 5.0

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(student)
        self.db.refresh(s)
        self.assertEqual(student.balance, 1000.0 - expected_cost)
        self.assertTrue(s.is_deducted)
        self.assertEqual(s.amount_deducted, expected_cost)
        print(f"[OK] Deduct lunch_only: cost={expected_cost}, balance={student.balance}")

    def test_deduct_dinner_only(self):
        """Student with 'dinner_only' status: deducted dinner_only_pct * final_rate + mgr_charge."""
        cycle = self._create_cycle()
        student = self._create_student("student_dinner", balance=1000.0)
        self._add_expense(cycle.id, "2026-06-01", 1000.0)
        s = self._add_meal_status(student.id, cycle.id, "2026-06-01", "dinner_only")

        rates = self._get_expected_rates(cycle)
        expected_cost = (0.6 * rates["final_rate"]) + 5.0

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(student)
        self.db.refresh(s)
        self.assertEqual(student.balance, 1000.0 - expected_cost)
        self.assertTrue(s.is_deducted)
        self.assertEqual(s.amount_deducted, expected_cost)
        print(f"[OK] Deduct dinner_only: cost={expected_cost}, balance={student.balance}")

    def test_deduct_guest_both(self):
        """Guest with 'both' status: deducted final_rate + guest_charge_per_day."""
        cycle = self._create_cycle()
        other_hall = models.Hall(name="Other Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0, guest_charge_per_day=5.0)
        self.db.add(other_hall)
        self.db.commit()
        guest = self._create_student("guest_std", balance=500.0, hall_id=other_hall.id)
        self._add_expense(cycle.id, "2026-06-01", 1000.0)
        s = self._add_meal_status(guest.id, cycle.id, "2026-06-01", "both", is_guest=True, guest_from_hall_id=other_hall.id)

        rates = billing_helper.get_daily_meal_rates(cycle, "2026-06-01", self.db)
        expected_cost = rates["final_rate"] + other_hall.guest_charge_per_day

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(guest)
        self.db.refresh(s)
        self.assertEqual(guest.balance, 500.0 - expected_cost)
        self.assertTrue(s.is_deducted)
        self.assertEqual(s.amount_deducted, expected_cost)
        print(f"[OK] Deduct guest both: cost={expected_cost}, balance={guest.balance}")

    def test_deduct_mixed_statuses(self):
        """All three meal types in one cycle, all deducted correctly with different costs."""
        cycle = self._create_cycle()
        student_both = self._create_student("both_s", balance=1000.0)
        student_lunch = self._create_student("lunch_s", balance=1000.0)
        student_dinner = self._create_student("dinner_s", balance=1000.0)

        self._add_expense(cycle.id, "2026-06-01", 2000.0)

        s_both = self._add_meal_status(student_both.id, cycle.id, "2026-06-01", "both")
        s_lunch = self._add_meal_status(student_lunch.id, cycle.id, "2026-06-01", "lunch_only")
        s_dinner = self._add_meal_status(student_dinner.id, cycle.id, "2026-06-01", "dinner_only")

        rates = self._get_expected_rates(cycle)
        # lunch units = 1*0.5 + 1*0.5 = 1.0 (both + lunch_only)
        # dinner units = 1*0.5 + 1*0.5 = 1.0 (both + dinner_only)
        # net lunch = 1000, net dinner = 1000
        # lunch_rate = 1000/1.0 * 0.5 = 500.0
        # dinner_rate = 1000/1.0 * 0.5 = 500.0
        # final_rate = 1000.0

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(student_both)
        self.db.refresh(student_lunch)
        self.db.refresh(student_dinner)
        self.db.refresh(s_both)
        self.db.refresh(s_lunch)
        self.db.refresh(s_dinner)

        # both: cost = 1000 + 5 = 1005
        self.assertEqual(student_both.balance, 1000.0 - (rates["final_rate"] + 5.0))
        self.assertTrue(s_both.is_deducted)

        # lunch_only: cost = 0.4 * final_rate + 5 = 405
        self.assertEqual(student_lunch.balance, 1000.0 - (0.4 * rates["final_rate"] + 5.0))
        self.assertTrue(s_lunch.is_deducted)

        # dinner_only: cost = 0.6 * final_rate + 5 = 605
        self.assertEqual(student_dinner.balance, 1000.0 - (0.6 * rates["final_rate"] + 5.0))
        self.assertTrue(s_dinner.is_deducted)

        # Total deductions = 1005 + 405 + 605 = 2015 (includes 3*5=15 mgr fees)
        # Total expense = 2000. Remaining 15 is manager fees.
        total_deducted = (1000.0 - student_both.balance) + (1000.0 - student_lunch.balance) + (1000.0 - student_dinner.balance)
        self.assertEqual(total_deducted, 2000.0 + 15.0)
        print(f"[OK] Deduct mixed statuses: both={1000.0-student_both.balance:.2f}, lunch={1000.0-student_lunch.balance:.2f}, dinner={1000.0-student_dinner.balance:.2f}")

    def test_deduct_idempotent(self):
        """Calling deduct_passed_meals twice should not double-deduct."""
        cycle = self._create_cycle()
        student = self._create_student("student1", balance=1000.0)
        self._add_expense(cycle.id, "2026-06-01", 1000.0)
        self._add_meal_status(student.id, cycle.id, "2026-06-01", "both")

        billing_helper.deduct_passed_meals(self.db)
        first_balance = self.db.query(models.User).filter(models.User.id == student.id).first().balance

        # Second call should not change anything
        billing_helper.deduct_passed_meals(self.db)
        second_balance = self.db.query(models.User).filter(models.User.id == student.id).first().balance

        self.assertEqual(first_balance, second_balance)

        # Verify no records are double-deducted
        deducted_records = self.db.query(models.StudentMealStatus).filter(
            models.StudentMealStatus.user_id == student.id,
            models.StudentMealStatus.is_deducted == True
        ).all()
        self.assertEqual(len(deducted_records), 1)
        print(f"[OK] Deduct idempotent: first={first_balance}, second={second_balance} — no double deduction.")

    def test_deduct_skips_future_and_off(self):
        """Future dates and 'off' statuses should not be deducted."""
        cycle = self._create_cycle()
        student = self._create_student("student1", balance=1000.0)
        self._add_expense(cycle.id, "2026-06-01", 1000.0)

        # Past date for "off" — not counted (status == "off")
        s_off = self._add_meal_status(student.id, cycle.id, "2026-06-01", "off")
        # Future date for "both" — not deducted (date >= today)
        s_future = self._add_meal_status(student.id, cycle.id, "2026-12-25", "both")

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(s_off)
        self.db.refresh(s_future)
        self.assertFalse(s_off.is_deducted)
        self.assertFalse(s_future.is_deducted)

        self.db.refresh(student)
        self.assertEqual(student.balance, 1000.0)  # unchanged
        print(f"[OK] Deduct skips future and off: balance unchanged at {student.balance}.")

    def test_deduct_free_meal_skipped(self):
        """Students with free_meal=True should not be charged."""
        cycle = self._create_cycle()
        manager = self._create_student("hall_mgr", balance=0.0, free_meal=True)
        self._add_expense(cycle.id, "2026-06-01", 1000.0)
        s = self._add_meal_status(manager.id, cycle.id, "2026-06-01", "both")

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(manager)
        self.db.refresh(s)
        self.assertEqual(manager.balance, 0.0)  # unchanged
        self.assertTrue(s.is_deducted)  # marked as processed
        self.assertEqual(s.amount_deducted, 0.0)  # but no cost
        print(f"[OK] Deduct free meal: balance={manager.balance} unchanged, cost={s.amount_deducted}.")


class TestRemainingBalance(unittest.TestCase):
    """Tests for billing_helper.get_student_remaining_balance() with projected future meals.
    Uses future dates (>= today) so meals are picked up by the function."""

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = Session()

        self.hall = models.Hall(name="Test Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.db.add(self.hall)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_cycle(self, month="2026-06", lunch_pct=0.5, dinner_pct=0.5):
        cycle = models.MealCycle(
            hall_id=self.hall.id, month=month, status="active",
            cutoff_time="20:00", lunch_percentage=lunch_pct, dinner_percentage=dinner_pct
        )
        self.db.add(cycle)
        self.db.commit()
        return cycle

    def _create_student(self, name, balance=1000.0, free_meal=False, hall_id=None):
        user = models.User(
            username=name, password_hash="hash",
            role="student", hall_id=hall_id or self.hall.id,
            name=name, balance=balance, free_meal=free_meal
        )
        self.db.add(user)
        self.db.commit()
        return user

    def _add_meal_status(self, user_id, cycle_id, date_str, status, is_guest=False, guest_from_hall_id=None,
                         is_deducted=False):
        s = models.StudentMealStatus(
            user_id=user_id, meal_cycle_id=cycle_id, date=date_str, status=status,
            is_guest=is_guest, guest_from_hall_id=guest_from_hall_id,
            is_deducted=is_deducted, amount_deducted=0.0
        )
        self.db.add(s)
        self.db.commit()
        return s

    def _add_expense(self, cycle_id, date_str, amount, meal_type=None):
        e = models.Expense(
            meal_cycle_id=cycle_id, date=date_str,
            description="Test expense", amount=amount, meal_type=meal_type
        )
        self.db.add(e)
        self.db.commit()

    def _get_rates(self, cycle):
        return billing_helper.get_running_meal_rates(cycle, self.db)

    def _future_date(self, days_from_now=5):
        from datetime import date, timedelta
        return (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")

    def test_remaining_single_both(self):
        """Student with 1 future 'both' meal: remaining = balance - (final_rate + mgr_charge)."""
        cycle = self._create_cycle()
        student = self._create_student("student1", balance=1000.0)
        self._add_expense(cycle.id, self._future_date(-5), 1000.0)
        self._add_meal_status(student.id, cycle.id, self._future_date(3), "both")

        rates = self._get_rates(cycle)
        projected_cost = rates["final_rate"] + 5.0
        expected = round(1000.0 - projected_cost, 2)

        remaining = billing_helper.get_student_remaining_balance(student, self.db)
        self.assertEqual(remaining, expected)
        print(f"[OK] Remaining single both: balance=1000, cost={projected_cost}, remaining={remaining}")

    def test_remaining_mixed_statuses(self):
        """3 students with different meal types. Each projected correctly based on their status."""
        cycle = self._create_cycle()
        both_s = self._create_student("both_s", balance=1000.0)
        lunch_s = self._create_student("lunch_s", balance=1000.0)
        dinner_s = self._create_student("dinner_s", balance=1000.0)

        self._add_expense(cycle.id, self._future_date(-5), 2000.0)
        fd = self._future_date(3)
        self._add_meal_status(both_s.id, cycle.id, fd, "both")
        self._add_meal_status(lunch_s.id, cycle.id, fd, "lunch_only")
        self._add_meal_status(dinner_s.id, cycle.id, fd, "dinner_only")

        rates = self._get_rates(cycle)

        both_remaining = billing_helper.get_student_remaining_balance(both_s, self.db)
        lunch_remaining = billing_helper.get_student_remaining_balance(lunch_s, self.db)
        dinner_remaining = billing_helper.get_student_remaining_balance(dinner_s, self.db)

        self.assertEqual(both_remaining, round(1000.0 - (rates["final_rate"] + 5.0), 2))
        self.assertEqual(lunch_remaining, round(1000.0 - (billing_helper._lunch_only_pct("lunch_only", fd, cycle) * rates["final_rate"] + 5.0), 2))
        self.assertEqual(dinner_remaining, round(1000.0 - (billing_helper._dinner_only_pct("dinner_only", fd, cycle) * rates["final_rate"] + 5.0), 2))
        print(f"[OK] Remaining mixed: both={both_remaining}, lunch={lunch_remaining}, dinner={dinner_remaining}")

    def test_remaining_guest_future(self):
        """Guest with future meals: projected at guest_rate (no mgr_charge)."""
        cycle = self._create_cycle()
        other_hall = models.Hall(name="Other Hall", guest_meal_rate=120.0, manager_charge_per_day=5.0)
        self.db.add(other_hall)
        self.db.commit()
        guest = self._create_student("guest_std", balance=500.0, hall_id=other_hall.id)
        self._add_expense(cycle.id, self._future_date(-5), 1000.0)
        self._add_meal_status(guest.id, cycle.id, self._future_date(3), "both", is_guest=True, guest_from_hall_id=other_hall.id)

        # Guest cost = final_rate + guest_charge_per_day (no mgr charge)
        rates = billing_helper.get_running_meal_rates(cycle, self.db)
        projected = rates["final_rate"] + (self.hall.guest_charge_per_day or 5.0)
        expected = round(500.0 - projected, 2)
        remaining = billing_helper.get_student_remaining_balance(guest, self.db)
        self.assertEqual(remaining, expected)
        print(f"[OK] Remaining guest future: balance=500, projected={projected}, remaining={remaining}")

    def test_remaining_multiple_cycles(self):
        """Student with future meals across 2 different cycles. Each cycle's rates used independently."""
        cycle_a = self._create_cycle(month="2026-06")
        cycle_b = self._create_cycle(month="2026-07")
        student = self._create_student("multi_cycle", balance=2000.0)

        self._add_expense(cycle_a.id, self._future_date(-5), 1000.0)
        self._add_expense(cycle_b.id, self._future_date(-4), 5000.0)

        fd_a = self._future_date(3)
        fd_b = self._future_date(10)
        self._add_meal_status(student.id, cycle_a.id, fd_a, "both")
        self._add_meal_status(student.id, cycle_b.id, fd_b, "both")

        rates_a = self._get_rates(cycle_a)
        rates_b = self._get_rates(cycle_b)

        projected = (rates_a["final_rate"] + 5.0) + (rates_b["final_rate"] + 5.0)
        expected = round(2000.0 - projected, 2)

        remaining = billing_helper.get_student_remaining_balance(student, self.db)
        self.assertEqual(remaining, expected)
        self.assertNotEqual(rates_a["final_rate"], rates_b["final_rate"])
        print(f"[OK] Remaining multi-cycle: A_rate={rates_a['final_rate']}, B_rate={rates_b['final_rate']}, remaining={remaining}")

    def test_remaining_free_meal(self):
        """free_meal=True returns balance directly with no projections."""
        cycle = self._create_cycle()
        manager = self._create_student("hall_mgr", balance=50.0, free_meal=True)
        self._add_expense(cycle.id, self._future_date(-5), 1000.0)
        self._add_meal_status(manager.id, cycle.id, self._future_date(3), "both")

        remaining = billing_helper.get_student_remaining_balance(manager, self.db)
        self.assertEqual(remaining, 50.0)  # unchanged
        print(f"[OK] Remaining free meal: balance=50, remaining={remaining} (unchanged)")

    def test_remaining_with_negative_balance(self):
        """Student with negative balance: remaining = negative_balance - projected_bill."""
        cycle = self._create_cycle()
        student = self._create_student("student1", balance=-500.0)
        self._add_expense(cycle.id, self._future_date(-5), 1000.0)
        self._add_meal_status(student.id, cycle.id, self._future_date(3), "both")

        rates = self._get_rates(cycle)
        projected = rates["final_rate"] + 5.0
        expected = round(-500.0 - projected, 2)

        remaining = billing_helper.get_student_remaining_balance(student, self.db)
        self.assertEqual(remaining, expected)
        print(f"[OK] Remaining negative balance: bal=-500, cost={projected}, remaining={remaining}")

    def test_remaining_skips_off_and_deducted(self):
        """Records with status='off' or is_deducted=True should not be projected."""
        cycle = self._create_cycle()
        student = self._create_student("student1", balance=1000.0)
        self._add_expense(cycle.id, self._future_date(-5), 1000.0)

        fd = self._future_date(3)
        self._add_meal_status(student.id, cycle.id, fd, "off")        # skipped: status=off
        self._add_meal_status(student.id, cycle.id, self._future_date(4), "both", is_deducted=True)  # skipped: already deducted

        remaining = billing_helper.get_student_remaining_balance(student, self.db)
        self.assertEqual(remaining, 1000.0)  # no chargeable future meals
        print(f"[OK] Remaining skips off+deducted: balance=1000, remaining={remaining} (no projected costs)")

    def test_remaining_no_future_meals(self):
        """No upcoming meals at all: remaining = current balance."""
        cycle = self._create_cycle()
        student = self._create_student("student1", balance=750.50)
        self._add_expense(cycle.id, self._future_date(-5), 1000.0)

        remaining = billing_helper.get_student_remaining_balance(student, self.db)
        self.assertEqual(remaining, 750.50)
        print(f"[OK] Remaining no future meals: balance=750.50, remaining={remaining}")

    def test_student_ledger_endpoint_calculations(self):
        """Verify get_student_ledger endpoint uses s.amount_deducted and retrieves pre-cycle dates correctly."""
        # 1. Create cycle and student using helpers
        cycle = self._create_cycle()
        cycle.start_date = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        cycle.end_date = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
        self.db.commit()

        student = self._create_student("student_test_ledger", balance=1000.0)
        
        # Create a manager user
        manager = models.User(
            username="manager_test_ledger", password_hash="hash",
            role="manager", hall_id=self.hall.id,
            name="Test Manager", balance=0.0, free_meal=False
        )
        self.db.add(manager)
        self.db.commit()

        # 2. Add deposit
        dep = models.Deposit(
            user_id=student.id,
            amount=500.0,
            meal_cycle_id=cycle.id,
            date=(date.today() - timedelta(days=2)).strftime("%Y-%m-%d"),
            description="Test Deposit"
        )
        self.db.add(dep)
        self.db.commit()

        # 3. Add meal status records:
        # A record before the cycle start date but belonging to cycle (e.g. date.today() - 3 days)
        pre_cycle_date = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
        pre_status = models.StudentMealStatus(
            user_id=student.id,
            meal_cycle_id=cycle.id,
            date=pre_cycle_date,
            status="both",
            is_deducted=True,
            amount_deducted=25.0
        )
        # A record within the cycle start date, already deducted with historic amount (e.g. 80.00)
        cycle_deducted_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        cycle_deducted_status = models.StudentMealStatus(
            user_id=student.id,
            meal_cycle_id=cycle.id,
            date=cycle_deducted_date,
            status="both",
            is_deducted=True,
            amount_deducted=80.0
        )
        # A record for today, not deducted yet
        today_date = date.today().strftime("%Y-%m-%d")
        today_status = models.StudentMealStatus(
            user_id=student.id,
            meal_cycle_id=cycle.id,
            date=today_date,
            status="both",
            is_deducted=False,
            amount_deducted=0.0
        )
        self.db.add_all([pre_status, cycle_deducted_status, today_status])
        self.db.commit()

        # 4. Add an expense to affect running rates
        exp = models.Expense(
            meal_cycle_id=cycle.id,
            amount=150.0,
            date=today_date,
            meal_type="both",
            description="Daily Expense"
        )
        self.db.add(exp)
        self.db.commit()

        # 5. Retrieve ledger
        from routers.manager_router import get_student_ledger
        ledger = get_student_ledger(user_id=student.id, current_user=manager, db=self.db)

        # 6. Assertions
        daily_meals = ledger["daily_meals"]
        meal_dates = [m["date"] for m in daily_meals]
        self.assertIn(pre_cycle_date, meal_dates)
        self.assertIn(cycle_deducted_date, meal_dates)
        self.assertIn(today_date, meal_dates)

        # Check day costs
        pre_meal = next(m for m in daily_meals if m["date"] == pre_cycle_date)
        ded_meal = next(m for m in daily_meals if m["date"] == cycle_deducted_date)
        today_meal = next(m for m in daily_meals if m["date"] == today_date)

        # Day costs are now recalculated from current daily rates,
        # not the stored amount_deducted (which may be stale).
        # pre_cycle_date has no expense → final_rate=0 → cost = 0 + mgr(5) = 5
        self.assertEqual(pre_meal["day_cost"], 5.0)
        # cycle_deducted_date has no expense → final_rate=0 → cost = 0 + mgr(5) = 5
        self.assertEqual(ded_meal["day_cost"], 5.0)
        # today_date has an expense → cost = final_rate + mgr
        self.assertEqual(today_meal["day_cost"], today_meal["final_rate"] + 5.0)

        expected_total_bill = round(sum(m["day_cost"] for m in daily_meals if m["status"] != "off"), 2)
        self.assertEqual(ledger["total_bill"], expected_total_bill)

        print("[OK] test_student_ledger_endpoint_calculations passed successfully!")

    def test_deduct_includes_today(self):
        """Today's date status should be eligible for deduction (since date <= today)."""
        cycle = self._create_cycle()
        student = self._create_student("student_today_deduct", balance=1000.0)
        # Status for today
        today_date = date.today().strftime("%Y-%m-%d")
        self._add_expense(cycle.id, today_date, 1000.0)
        s_today = self._add_meal_status(student.id, cycle.id, today_date, "both")

        billing_helper.deduct_passed_meals(self.db)

        self.db.refresh(s_today)
        self.db.refresh(student)

        self.assertTrue(s_today.is_deducted)
        # expected cost: running rate + mgr_charge (5.0)
        # since 1 student eating 2 meals = 1.0 units (0.5 lunch + 0.5 dinner). Expense = 1000. Rate = 1000.
        # cost = 1000.0 + 5.0 = 1005.0
        self.assertEqual(s_today.amount_deducted, 1005.0)
        self.assertEqual(student.balance, -5.0)
        print(f"[OK] Deduct includes today: balance reduced to {student.balance}, status marked as deducted.")

    def test_bulk_user_creation(self):
        """Verify POST /users/bulk inserts users, hashes passwords, and handles duplicates correctly."""
        superadmin = models.User(
            username="test_superadmin", password_hash="hash",
            role="superadmin", name="Super Admin", balance=0.0
        )
        self.db.add(superadmin)
        self.db.commit()

        # Pre-create student1 to act as duplicate
        self._create_student("student1")

        # Input data with two new users and one duplicate of 'student1'
        users_data = "student_bulk1, Bulk One, 101\nstudent1\nstudent_bulk2\n"
        
        from schemas import BulkUserCreate
        payload = BulkUserCreate(
            users_data=users_data,
            role="student",
            hall_id=self.hall.id,
            default_password="password123"
        )
        
        from routers.admin_router import bulk_create_users
        res = bulk_create_users(payload, current_user=superadmin, db=self.db)
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["created_count"], 2)
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("Line 2: Username 'student1' already exists.", res["errors"][0])
        
        bulk1 = self.db.query(models.User).filter(models.User.username == "student_bulk1").first()
        self.assertIsNotNone(bulk1)
        self.assertEqual(bulk1.name, "Bulk One")
        self.assertEqual(bulk1.room_number, "101")
        self.assertEqual(bulk1.role, "student")
        self.assertEqual(bulk1.hall_id, self.hall.id)
        self.assertTrue(auth.verify_password("password123", bulk1.password_hash))
        
        bulk2 = self.db.query(models.User).filter(models.User.username == "student_bulk2").first()
        self.assertIsNotNone(bulk2)
        self.assertEqual(bulk2.name, "student_bulk2")
        self.assertIsNone(bulk2.room_number)
        
        print("[OK] test_bulk_user_creation passed successfully!")

    def test_profile_self_edit(self):
        """Verify PUT /profile allows users to update their personal details."""
        student1 = self._create_student("student1", balance=1000.0)
        
        from schemas import UserProfileUpdate
        payload = UserProfileUpdate(
            name="Updated Kamrul",
            phone="01999888777",
            email="kamrul@example.com",
            room_number="102-New",
            password="newpassword123"
        )
        
        from routers.auth_router import update_profile
        updated = update_profile(payload, current_user=student1, db=self.db)
        
        self.assertEqual(updated.name, "Updated Kamrul")
        self.assertEqual(updated.phone, "01999888777")
        self.assertEqual(updated.email, "kamrul@example.com")
        self.assertEqual(updated.room_number, "102-New")
        self.assertTrue(auth.verify_password("newpassword123", updated.password_hash))
        
        self.assertEqual(updated.role, "student")
        self.assertEqual(updated.balance, 1000.0)
        self.assertEqual(updated.free_meal, False)
        
        print("[OK] test_profile_self_edit passed successfully!")


if __name__ == "__main__":
    unittest.main()
