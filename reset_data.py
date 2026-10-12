"""Delete every service database so the system starts from fresh seed data.
Run this only while the services are STOPPED:   python reset_data.py"""
from pathlib import Path

root = Path(__file__).resolve().parent
count = 0
for db in root.glob("services/*/data/*.db"):
    db.unlink()
    count += 1
print(f"Removed {count} database file(s). They will be re-created on next start.")
