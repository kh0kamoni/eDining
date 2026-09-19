import sqlite3

conn = sqlite3.connect('dining.db')
cursor = conn.cursor()

# Get halls info
cursor.execute("SELECT id, name FROM halls")
halls = cursor.fetchall()
print("Halls:")
for h in halls:
    print(f"ID: {h[0]} | Name: {h[1]}")

# Count users per hall_id
cursor.execute("SELECT hall_id, COUNT(*) FROM users GROUP BY hall_id")
counts = cursor.fetchall()
print("\nUsers count per Hall ID:")
for c in counts:
    print(f"Hall ID: {c[0]} | Count: {c[1]}")

conn.close()
