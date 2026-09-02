from app import history
from app.services.smartpay import SmartPayService

if history.HISTORY_PATH.exists():
    history.HISTORY_PATH.unlink()

svc = SmartPayService()
purchases = [
    {"merchant": "Best Buy", "amount": "1200", "category": "shopping", "description": "Laptop"},
    {"merchant": "Whole Foods", "amount": "90", "category": "supermarket", "description": "Groceries"},
    {"merchant": "Delta", "amount": "450", "category": "airfare", "description": "Flight"},
]
for p in purchases:
    svc.optimise_purchase(purchase=p)

entries = history.load()
print("entries after 3 distinct purchases:", len(entries))
for e in entries:
    print("  key=", e.get("key"), "| title=", e.get("title"))

svc.optimise_purchase(purchase=purchases[0])
print("entries after re-asking one (should stay 3):", len(history.load()))

history.HISTORY_PATH.unlink()
