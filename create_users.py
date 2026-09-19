import sqlite3
import bcrypt

# List of users: (room_number, name, status)
users_data = [
    # 100s
    ("101", "Faisal", "On"),
    ("101", "Salman", "On"),
    ("101", "Milan", "On"),
    ("101", "Arnab", "On"),
    ("102", "Riaz", "Off"),
    ("102", "Saikat", "Off"),
    ("102", "Ovi", "On"),
    ("102", "Jamil", "On"),
    ("102", "Hasibul", "On"),
    ("103", "Biplob", "On"),
    ("103", "Biplop", "Off"),
    ("103", "Abir", "On"),
    ("103", "Kamrul", "On"),
    ("106", "Aurnab", "On"),
    ("106", "Parvej", "On"),
    ("106", "Tanvir", "On"),
    ("107", "Alif", "Off"),
    ("107", "Shihab", "On"),
    ("107", "Kibria", "On"),
    ("107", "Jamil", "On"),
    ("108", "Ibrahim", "On"),
    ("108", "Rafik", "On"),
    ("108", "Mahabub", "On"),
    ("108", "Noman", "On"),
    
    # 200s
    ("201", "Shahadad", "Off"),
    ("201", "Mahamudul", "On"),
    ("201", "Arman", "Off"),
    ("202", "Opu", "On"),
    ("202", "Zahid", "On"),
    ("202", "Rajdeep", "On"),
    ("203", "Maruf", "On"),
    ("203", "Akash", "Off"),
    ("204", "Naimur", "On"),
    ("204", "Mimog", "On"),
    ("204", "Farhan", "Off"),
    ("204", "Tonim", "Off"),
    ("205", "Limon", "On"),
    ("205", "Nayeem", "On"),
    ("205", "Choton", "Off"),
    ("205", "Dipok", "On"),
    ("206", "Sakib", "On"),
    ("206", "Sohan", "Off"),
    ("206", "Rahul", "On"),
    ("206", "Udoy", "On"),
    ("207", "Towhid", "On"),
    ("207", "Mehedi", "Off"),
    ("207", "Ayan", "On"),
    ("207", "Shoaj", "On"),
    ("208", "Sazid", "Off"),
    ("208", "Rafat", "On"),
    ("208", "Sajib", "On"),
    ("209", "Taj", "On"),
    ("209", "Sazid", "On"),
    ("209", "Najik", "On"),
    ("210", "Ibrahim", "Off"),
    ("210", "Anik", "Off"),
    ("210", "Rahul", "On"),
    ("210", "Siddique", "On"),
    ("210", "Rasel", "On"),
    ("210", "Sami", "On"),
    ("210", "Moni", "On"),
    ("210", "Prince", "On"),
    ("210", "Jihad", "On"),
    ("210", "Nafis", "On"),
    ("210", "Kaushik", "On"),
    
    # 300s
    ("301", "Mishbah", "Off"),
    ("301", "Hasan", "On"),
    ("301", "Ashik", "On"),
    ("301", "Amit", "On"),
    ("302", "Asif", "Lunch"),
    ("302", "Sajjad", "Lunch"),
    ("302", "Mehedi", "On"),
    ("302", "Razin", "On"),
    ("303", "Tadi", "On"),
    ("303", "Shahria", "On"),
    ("304", "Muzahid", "On"),
    ("304", "Shahriar", "On"),
    ("304", "Sagar", "On"),
    ("305", "Tafsir", "On"),
    ("305", "Muktadirul", "On"),
    ("305", "Tanim", "On"),
    ("306", "Wahid", "On"),
    ("306", "Sabbir", "On"),
    ("306", "Sourov", "On"),
    ("306", "Alif", "Off"),
    ("307", "Fahat", "On"),
    ("307", "Riyad", "On"),
    ("307", "Arman", "On"),
    ("307", "Topon", "On"),
    ("308", "Fuad", "On"),
    ("308", "Rokan", "On"),
    ("308", "Rezuna", "On"),
    ("309", "Murad", "On"),
    ("309", "Joy", "On"),
    ("309", "Shovon", "On"),
    ("309", "Tanvir", "On"),
    
    # 400s
    ("401", "Sami", "On"),
    ("401", "Tamjid", "On"),
    ("401", "Rana", "Off"),
    ("402", "Joynal", "On"),
    ("402", "Arif", "On"),
    ("402", "Yasir", "On"),
    ("402", "Robin", "On"),
    ("403", "Rajib", "On"),
    ("403", "Ety", "On"),
    ("403", "Topu", "On"),
    ("404", "Sazid", "On"),
    ("404", "Salman", "Lunch"),
    ("404", "Jihad", "On"),
    ("404", "Naim", "On"),
    ("405", "Kamruzzaman", "On"),
    ("405", "Nayeem", "On"),
    ("405", "Hamidul", "On"),
    ("406", "Rony", "On"),
    ("406", "Joy", "On"),
    ("406", "Araf", "Off"),
    ("407", "Jamil", "On"),
    ("407", "Promin", "On"),
    ("408", "Ariya", "Off"),
    ("408", "sajid", "On"),
    ("409", "Sabbir", "On"),
    ("409", "Tousif", "On"),
    ("409", "Shehadi", "On"),
    ("409", "Assadullah", "On"),
    
    # 500s
    ("501", "Emon", "On"),
    ("501", "Akash", "On"),
    ("501", "Najim", "On"),
    ("501", "Shobhom", "On"),
    ("502", "Robin", "On"),
    ("502", "Humayun", "On"),
    ("502", "Rab", "On"),
    ("502", "Kawsar", "On"),
    ("503", "Mizanur", "On"),
    ("503", "Fahim", "On"),
    ("503", "Manik", "On"),
    ("504", "Fida", "On"),
    ("504", "Zahid", "On"),
    ("504", "Arafat", "On"),
    ("505", "Morshed", "On"),
    ("505", "Mohaimin", "On"),
    ("505", "Pramod", "On"),
    ("505", "Sayeem", "On"),
    ("506", "Joyonto", "On"),
    ("506", "Ramin", "On"),
    ("506", "Ashik", "On"),
    ("506", "Alif", "On"),
    ("507", "Shani", "On"),
    ("507", "Plabon", "On"),
    ("507", "Rony", "On"),
    ("508", "Manik", "On"),
    ("508", "Morshed", "On"),
    ("508", "Milon", "On"),
    ("509", "Mitu", "On"),
    ("509", "Zimon", "On"),
    ("509", "Niloy", "On"),
    ("509", "Arafat", "On")
]

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def main():
    conn = sqlite3.connect('dining.db')
    cursor = conn.cursor()
    
    # 1. Fetch active meal cycle to seed initial meal statuses
    cursor.execute("SELECT id FROM meal_cycles WHERE status='active' LIMIT 1")
    cycle = cursor.fetchone()
    cycle_id = cycle[0] if cycle else None
    
    if cycle_id:
        # Fetch start/end dates of cycle
        cursor.execute("SELECT MIN(date), MAX(date) FROM student_meal_statuses WHERE meal_cycle_id = ?", (cycle_id,))
        min_date, max_date = cursor.fetchone()
        
        # If dates exist, let's build list of date strings
        import datetime as dt_mod
        if min_date and max_date:
            start_date = dt_mod.datetime.strptime(min_date, "%Y-%m-%d").date()
            end_date = dt_mod.datetime.strptime(max_date, "%Y-%m-%d").date()
            dates = []
            curr = start_date
            while curr <= end_date:
                dates.append(curr.strftime("%Y-%m-%d"))
                curr += dt_mod.timedelta(days=1)
        else:
            dates = []
    else:
        dates = []
        
    print(f"Active Cycle ID: {cycle_id}, Dates Count: {len(dates)}")
    
    created_users = []
    
    for room, name, status in users_data:
        # Consistent unique naming convention: name.lower() + room
        # We also support a pure lowercase name if we want, but appending room is safe and predictable.
        # Let's use name.lower() + room to guarantee uniqueness and consistency.
        username = f"{name.lower()}{room}"
        password = username # username is password
        
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        existing = cursor.fetchone()
        
        if existing:
            user_id = existing[0]
            print(f"User {username} already exists (ID: {user_id}). Skipping insertion.")
        else:
            hashed_pwd = get_password_hash(password)
            # Insert user (hall_id = 1 for Muktijoddha Hall, role = 'student', balance = 1000.0 like seed data)
            cursor.execute("""
                INSERT INTO users (username, password_hash, role, hall_id, room_number, name, balance, free_meal)
                VALUES (?, ?, 'student', 1, ?, ?, 1000.0, 0)
            """, (username, hashed_pwd, room, name))
            user_id = cursor.lastrowid
            created_users.append((name, room, username, password))
            
        # Seed meal statuses if cycle is active
        if cycle_id and dates:
            # Check if statuses already exist for this user in this cycle
            cursor.execute("SELECT count(*) FROM student_meal_statuses WHERE user_id = ? AND meal_cycle_id = ?", (user_id, cycle_id))
            exists_count = cursor.fetchone()[0]
            
            if exists_count == 0:
                # Determine daily status for insertion
                # Status options: off, both, lunch_only, dinner_only
                # We map: "On" -> "both", "Off" -> "off", "Lunch" -> "lunch_only"
                db_status = "off"
                if status == "On":
                    db_status = "both"
                elif status == "Lunch":
                    db_status = "lunch_only"
                
                # Insert statuses for each day of the active cycle
                status_rows = []
                for date_str in dates:
                    status_rows.append((user_id, cycle_id, date_str, db_status, 0, 0, 0, 0, None, 0, 0.0))
                
                cursor.executemany("""
                    INSERT INTO student_meal_statuses (
                        user_id, meal_cycle_id, date, status, ticked_lunch, ticked_dinner, 
                        kept_lunch_for_dinner, is_guest, guest_from_hall_id, is_deducted, amount_deducted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, status_rows)
                
    conn.commit()
    conn.close()
    
    print(f"\nSuccessfully created {len(created_users)} users in database.")
    
    # Save the created users credentials to a text file for formatting
    with open("created_users_credentials.txt", "w", encoding="utf-8") as f:
        f.write(f"{'Name':<15} | {'Room':<6} | {'Username':<15} | {'Password':<15}\n")
        f.write("-" * 60 + "\n")
        for u in created_users:
            f.write(f"{u[0]:<15} | {u[1]:<6} | {u[2]:<15} | {u[3]:<15}\n")
            
    # Also write a markdown file in scratch directory or workspace for the user
    with open("created_users.md", "w", encoding="utf-8") as f:
        f.write("# Created Users Credentials\n\n")
        f.write("All these users have been successfully registered in the database with their initial balance set to **1000.0 BDT** and their meal statuses pre-seeded according to the sheet.\n\n")
        f.write("| Name | Room | Username | Password |\n")
        f.write("| :--- | :--- | :--- | :--- |\n")
        for u in created_users:
            f.write(f"| {u[0]} | {u[1]} | `{u[2]}` | `{u[3]}` |\n")

if __name__ == '__main__':
    main()
