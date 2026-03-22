"""
Order Manager — Recovery Companion Supplement Fulfillment
Handles in-chat orders from Aether/Forge companions.

Flow:
1. Agent recommends supplements as part of recovery protocol
2. User asks to buy → agent emits [ORDER:] marker
3. Orchestrator catches marker → creates order here
4. Tom gets notified in command-center
5. Tom fulfills via DBH/Tony's sourcing
6. Agent confirms delivery at next check-in

Monthly auto-reorder: agent tracks supplement adherence and prompts
user when they should be running low (based on dose × days since order).
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
NZ_TZ = ZoneInfo("Pacific/Auckland")

DB_PATH = Path(__file__).parent.parent / "data" / "orders.db"

# Product catalog with pricing (placeholder — update with Tony's actual costs)
PRODUCT_CATALOG = {
    # Supplements
    "magnesium_glycinate": {
        "name": "Magnesium Glycinate",
        "doses": {"400mg": 14.99, "600mg": 19.99},
        "default_dose": "400mg",
        "units_per_bottle": 60,  # capsules
        "daily_dose_units": 2,   # capsules per day
        "days_supply": 30,
        "category": "supplement",
        "dbh_available": True,
        "notes": "Neuroprotection, muscle relaxation, sleep support",
    },
    "omega3_fish_oil": {
        "name": "Omega-3 Fish Oil (EPA/DHA)",
        "doses": {"2g": 24.99, "3g": 29.99, "4g": 34.99},
        "default_dose": "3g",
        "units_per_bottle": 90,
        "daily_dose_units": 3,
        "days_supply": 30,
        "category": "supplement",
        "dbh_available": True,
        "notes": "Anti-inflammatory, nerve cell membrane repair, brain health",
    },
    "vitamin_d3": {
        "name": "Vitamin D3",
        "doses": {"2000IU": 9.99, "4000IU": 12.99},
        "default_dose": "2000IU",
        "units_per_bottle": 90,
        "daily_dose_units": 1,
        "days_supply": 90,
        "category": "supplement",
        "dbh_available": True,
        "notes": "Neuroprotective, immune support",
    },
    "b_complex": {
        "name": "B-Complex",
        "doses": {"standard": 14.99},
        "default_dose": "standard",
        "units_per_bottle": 60,
        "daily_dose_units": 1,
        "days_supply": 60,
        "category": "supplement",
        "dbh_available": True,
        "notes": "Nerve function, energy metabolism",
    },
    "creatine_monohydrate": {
        "name": "Creatine Monohydrate",
        "doses": {"5g": 19.99},
        "default_dose": "5g",
        "units_per_bottle": 1,  # tub
        "daily_dose_units": 1,
        "days_supply": 60,  # 300g tub at 5g/day
        "category": "supplement",
        "dbh_available": False,
        "notes": "Neuroprotective, post-TBI cognitive improvement, exercise performance",
    },
    "nac": {
        "name": "NAC (N-Acetyl Cysteine)",
        "doses": {"600mg": 16.99},
        "default_dose": "600mg",
        "units_per_bottle": 60,
        "daily_dose_units": 1,
        "days_supply": 60,
        "category": "supplement",
        "dbh_available": False,
        "notes": "Glutathione precursor, brain detox, substance recovery support",
    },
    "vitamin_b12": {
        "name": "Vitamin B12 Methylcobalamin",
        "doses": {"1000mcg": 12.99},
        "default_dose": "1000mcg",
        "units_per_bottle": 60,
        "daily_dose_units": 1,
        "days_supply": 60,
        "category": "supplement",
        "dbh_available": True,
        "notes": "Sublingual, brain recovery, nerve function",
    },
    "l_glutamine": {
        "name": "L-Glutamine",
        "doses": {"5g": 17.99},
        "default_dose": "5g",
        "units_per_bottle": 1,  # tub
        "daily_dose_units": 1,
        "days_supply": 50,  # 250g tub at 5g/day
        "category": "supplement",
        "dbh_available": False,
        "notes": "Gut lining repair, immune fuel",
    },
    "probiotics": {
        "name": "Probiotics Multi-Strain",
        "doses": {"20B_CFU": 24.99},
        "default_dose": "20B_CFU",
        "units_per_bottle": 30,
        "daily_dose_units": 1,
        "days_supply": 30,
        "category": "supplement",
        "dbh_available": False,
        "notes": "Gut microbiome restoration, 20+ billion CFU multi-strain",
    },
    "electrolyte_tablets": {
        "name": "Electrolyte Tablets",
        "doses": {"standard": 12.99},
        "default_dose": "standard",
        "units_per_bottle": 60,
        "daily_dose_units": 2,
        "days_supply": 30,
        "category": "supplement",
        "dbh_available": False,
        "notes": "POTS blood volume support, sodium/potassium/magnesium",
    },
    "zinc": {
        "name": "Zinc",
        "doses": {"15mg": 9.99, "30mg": 11.99},
        "default_dose": "15mg",
        "units_per_bottle": 60,
        "daily_dose_units": 1,
        "days_supply": 60,
        "category": "supplement",
        "dbh_available": True,
        "notes": "Immune function, nerve repair",
    },
    "lions_mane": {
        "name": "Lion's Mane Mushroom",
        "doses": {"standard": 22.99},
        "default_dose": "standard",
        "units_per_bottle": 60,
        "daily_dose_units": 2,
        "days_supply": 30,
        "category": "supplement",
        "dbh_available": False,
        "notes": "NGF stimulation, neurogenesis",
    },
    "coq10": {
        "name": "CoQ10",
        "doses": {"150mg": 19.99, "300mg": 29.99},
        "default_dose": "150mg",
        "units_per_bottle": 30,
        "daily_dose_units": 1,
        "days_supply": 30,
        "category": "supplement",
        "dbh_available": True,
        "notes": "Mitochondrial support, brain energy",
    },
    "l_theanine": {
        "name": "L-Theanine",
        "doses": {"200mg": 14.99, "400mg": 18.99},
        "default_dose": "400mg",
        "units_per_bottle": 60,
        "daily_dose_units": 1,
        "days_supply": 60,
        "category": "supplement",
        "dbh_available": False,
        "notes": "Calm focus, pairs with caffeine",
    },
    "phosphatidylserine": {
        "name": "Phosphatidylserine",
        "doses": {"200mg": 24.99},
        "default_dose": "200mg",
        "units_per_bottle": 30,
        "daily_dose_units": 1,
        "days_supply": 30,
        "category": "supplement",
        "dbh_available": False,
        "notes": "Memory, cortisol reduction, brain cell membranes",
    },
    # Nutrition
    "protein_powder": {
        "name": "Whey Protein Powder",
        "doses": {"1kg": 39.99, "2kg": 69.99},
        "default_dose": "1kg",
        "units_per_bottle": 1,
        "daily_dose_units": 1,
        "days_supply": 33,  # ~30g serving, 33 servings per kg
        "category": "nutrition",
        "dbh_available": False,
        "notes": "Caloric rehabilitation, muscle building protein target",
    },
    "mct_oil": {
        "name": "MCT Oil",
        "doses": {"500ml": 19.99},
        "default_dose": "500ml",
        "units_per_bottle": 1,
        "daily_dose_units": 1,
        "days_supply": 33,
        "category": "nutrition",
        "dbh_available": False,
        "notes": "Calorie-dense, brain fuel, ketone production",
    },
}

# Pre-built stacks per companion
COMPANION_STACKS = {
    "aether": {
        "phase_1": {
            "name": "Jackson's Foundation Stack",
            "products": [
                {"product_id": "magnesium_glycinate", "dose": "400mg"},
                {"product_id": "omega3_fish_oil", "dose": "3g"},
                {"product_id": "vitamin_d3", "dose": "2000IU"},
                {"product_id": "b_complex", "dose": "standard"},
                {"product_id": "protein_powder", "dose": "1kg"},
            ],
        },
        "phase_2": {
            "name": "Jackson's Regulation Stack",
            "products": [
                {"product_id": "magnesium_glycinate", "dose": "600mg"},
                {"product_id": "omega3_fish_oil", "dose": "4g"},
                {"product_id": "vitamin_d3", "dose": "2000IU"},
                {"product_id": "b_complex", "dose": "standard"},
                {"product_id": "electrolyte_tablets", "dose": "standard"},
                {"product_id": "zinc", "dose": "15mg"},
                {"product_id": "protein_powder", "dose": "1kg"},
            ],
        },
    },
    "forge": {
        "phase_1": {
            "name": "Tyler's Foundation Stack",
            "products": [
                {"product_id": "magnesium_glycinate", "dose": "400mg"},
                {"product_id": "omega3_fish_oil", "dose": "3g"},
                {"product_id": "creatine_monohydrate", "dose": "5g"},
                {"product_id": "nac", "dose": "600mg"},
                {"product_id": "vitamin_b12", "dose": "1000mcg"},
                {"product_id": "l_glutamine", "dose": "5g"},
                {"product_id": "probiotics", "dose": "20B_CFU"},
            ],
        },
        "phase_2": {
            "name": "Tyler's Brain Recovery Stack",
            "products": [
                {"product_id": "magnesium_glycinate", "dose": "600mg"},
                {"product_id": "omega3_fish_oil", "dose": "3g"},
                {"product_id": "creatine_monohydrate", "dose": "5g"},
                {"product_id": "nac", "dose": "600mg"},
                {"product_id": "vitamin_b12", "dose": "1000mcg"},
                {"product_id": "l_glutamine", "dose": "5g"},
                {"product_id": "probiotics", "dose": "20B_CFU"},
                {"product_id": "coq10", "dose": "150mg"},
                {"product_id": "phosphatidylserine", "dose": "200mg"},
                {"product_id": "protein_powder", "dose": "2kg"},
            ],
        },
    },
}


def _get_db():
    """Get or create the orders database."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            products TEXT NOT NULL,
            total_price REAL DEFAULT 0,
            shipping_address TEXT,
            notes TEXT,
            is_reorder BOOLEAN DEFAULT 0,
            parent_order_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            shipped_at TEXT,
            delivered_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            dose TEXT,
            quantity INTEGER DEFAULT 1,
            unit_price REAL DEFAULT 0,
            days_supply INTEGER DEFAULT 30,
            reorder_date TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)
    db.commit()
    return db


def create_order(user_id: str, agent_name: str, product_ids: list,
                 shipping_address: str = None, notes: str = None,
                 is_reorder: bool = False, parent_order_id: str = None) -> dict:
    """
    Create a new order from product IDs.
    Returns order summary dict.
    """
    db = _get_db()
    now = datetime.now(NZ_TZ)
    order_id = f"ORD-{agent_name.upper()}-{now.strftime('%Y%m%d%H%M%S')}"

    items = []
    total = 0.0
    for entry in product_ids:
        if isinstance(entry, str):
            pid = entry
            dose = None
        elif isinstance(entry, dict):
            pid = entry.get("product_id", entry.get("id", ""))
            dose = entry.get("dose")
        else:
            continue

        product = PRODUCT_CATALOG.get(pid)
        if not product:
            logger.warning(f"Unknown product ID: {pid}")
            continue

        use_dose = dose or product["default_dose"]
        price = product["doses"].get(use_dose, list(product["doses"].values())[0])
        days = product["days_supply"]
        reorder_date = (now + timedelta(days=days - 5)).date().isoformat()  # 5 days before running out

        items.append({
            "product_id": pid,
            "product_name": product["name"],
            "dose": use_dose,
            "unit_price": price,
            "days_supply": days,
            "reorder_date": reorder_date,
        })
        total += price

    if not items:
        return {"error": "No valid products found"}

    # Insert order
    db.execute("""
        INSERT INTO orders (order_id, user_id, agent_name, status, products, total_price,
                           shipping_address, notes, is_reorder, parent_order_id, created_at)
        VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
    """, (order_id, user_id, agent_name, json.dumps([i["product_id"] for i in items]),
          total, shipping_address, notes, is_reorder, parent_order_id, now.isoformat()))

    # Insert items
    for item in items:
        db.execute("""
            INSERT INTO order_items (order_id, product_id, product_name, dose, quantity,
                                    unit_price, days_supply, reorder_date)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?)
        """, (order_id, item["product_id"], item["product_name"], item["dose"],
              item["unit_price"], item["days_supply"], item["reorder_date"]))

    db.commit()
    db.close()

    return {
        "order_id": order_id,
        "user_id": user_id,
        "agent_name": agent_name,
        "items": items,
        "total": total,
        "status": "pending",
        "created_at": now.isoformat(),
    }


def get_stack_for_companion(agent_name: str, phase: int = 1) -> dict:
    """Get the pre-built supplement stack for a companion at their current phase."""
    stacks = COMPANION_STACKS.get(agent_name, {})
    phase_key = f"phase_{phase}"
    stack = stacks.get(phase_key, stacks.get("phase_1", {}))

    if not stack:
        return {"error": f"No stack defined for {agent_name} phase {phase}"}

    items = []
    total = 0.0
    for entry in stack.get("products", []):
        product = PRODUCT_CATALOG.get(entry["product_id"])
        if not product:
            continue
        dose = entry.get("dose", product["default_dose"])
        price = product["doses"].get(dose, list(product["doses"].values())[0])
        items.append({
            "product_id": entry["product_id"],
            "name": product["name"],
            "dose": dose,
            "price": price,
            "days_supply": product["days_supply"],
            "dbh_available": product["dbh_available"],
        })
        total += price

    return {
        "stack_name": stack.get("name", "Recovery Stack"),
        "items": items,
        "total": total,
        "monthly_estimate": sum(i["price"] * (30 / i["days_supply"]) for i in items),
    }


def get_orders(user_id: str = None, agent_name: str = None, status: str = None) -> list:
    """Get orders with optional filters."""
    db = _get_db()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    if agent_name:
        query += " AND agent_name = ?"
        params.append(agent_name)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"

    orders = [dict(row) for row in db.execute(query, params).fetchall()]

    # Attach items
    for order in orders:
        order["items"] = [dict(row) for row in
                          db.execute("SELECT * FROM order_items WHERE order_id = ?",
                                     (order["order_id"],)).fetchall()]

    db.close()
    return orders


def update_order_status(order_id: str, status: str) -> bool:
    """Update order status: pending → confirmed → shipped → delivered"""
    db = _get_db()
    now = datetime.now(NZ_TZ).isoformat()
    updates = {"updated_at": now, "status": status}
    if status == "shipped":
        updates["shipped_at"] = now
    elif status == "delivered":
        updates["delivered_at"] = now

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    db.execute(f"UPDATE orders SET {set_clause} WHERE order_id = ?",
               (*updates.values(), order_id))
    db.commit()
    db.close()
    return True


def get_reorder_due(days_ahead: int = 7) -> list:
    """Get order items that will need reordering within the next N days."""
    db = _get_db()
    cutoff = (datetime.now(NZ_TZ) + timedelta(days=days_ahead)).date().isoformat()
    items = [dict(row) for row in db.execute("""
        SELECT oi.*, o.user_id, o.agent_name, o.order_id
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE oi.reorder_date <= ?
        AND o.status IN ('delivered', 'shipped')
        ORDER BY oi.reorder_date ASC
    """, (cutoff,)).fetchall()]
    db.close()
    return items


def format_stack_for_telegram(stack: dict) -> str:
    """Format a supplement stack for Telegram display."""
    lines = [f"Your {stack['stack_name']}:\n"]
    for item in stack["items"]:
        avail = " (DBH)" if item.get("dbh_available") else ""
        lines.append(f"- {item['name']} {item['dose']} — ${item['price']:.2f} ({item['days_supply']} days){avail}")
    lines.append(f"\nTotal: ${stack['total']:.2f}")
    lines.append(f"Monthly estimate: ~${stack['monthly_estimate']:.2f}/month")
    lines.append(f"\nReply 'order' to get this shipped to you.")
    return "\n".join(lines)


def format_order_for_notification(order: dict) -> str:
    """Format an order for Tom's command-center notification."""
    lines = [
        f"NEW ORDER — {order['order_id']}",
        f"User: {order['user_id']} via {order['agent_name']}",
        f"Status: {order['status']}",
        f"Items:"
    ]
    for item in order.get("items", []):
        lines.append(f"  - {item['product_name']} {item.get('dose', '')} — ${item.get('unit_price', 0):.2f}")
    lines.append(f"Total: ${order['total']:.2f}")
    lines.append(f"Created: {order['created_at']}")
    if order.get("shipping_address"):
        lines.append(f"Ship to: {order['shipping_address']}")
    return "\n".join(lines)
