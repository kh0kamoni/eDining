import csv, re, io, urllib.request, json

data = open(r"C:\Users\Khoka Moni\Downloads\Khoka, Naine's Dinning - USERS.csv", "r", encoding="utf-8").read()

# Parse CSV headers
reader = csv.reader(io.StringIO(data))
headers = next(reader)
# Find room columns - they alternate: Room, User, Status, Room, User, Status, Room, User, Status
# So room columns are 0, 3, 6. User columns are 1, 4, 7.
room_cols = [0, 3, 6]
user_cols = [1, 4, 7]

def clean(name):
    if not name or not name.strip():
        return None
    name = name.strip()
    # Remove (E) suffix
    name = re.sub(r'\s*\(E\)\s*$', '', name, flags=re.IGNORECASE)
    # Remove extra spaces
    name = re.sub(r'\s+', '', name)
    return name

users = []
current_rooms = [None, None, None]

for row in reader:
    for i in range(3):
        room_val = row[room_cols[i]].strip() if room_cols[i] < len(row) else ""
        user_val = row[user_cols[i]].strip() if user_cols[i] < len(row) else ""
        
        if room_val:
            current_rooms[i] = room_val
        
        name = clean(user_val)
        if name and current_rooms[i]:
            username = (name.lower() + "_" + current_rooms[i])
            if username not in users:
                users.append(username)

print(f"Found {len(users)} unique users")
# Show first 10 and last 5
for u in users[:10]:
    print(f"  {u}")
print("  ...")
for u in users[-5:]:
    print(f"  {u}")

# Write to file for bulk import
with open(r"C:\Users\Khoka Moni\eDining\bulk_users.txt", "w", encoding="utf-8") as f:
    for u in users:
        f.write(u + "\n")
print(f"\nSaved {len(users)} users to bulk_users.txt")
