"""Firebase Admin SDK wrapper for the TrashPoint smart bin."""

import random
import time
from collections import Counter

import firebase_admin
from firebase_admin import credentials, db

ECO_TIERS = [
    ("Eco-Legend", 1000),
    ("Eco-Hero", 500),
    ("Eco-Warrior", 200),
    ("Eco-Beginner", 0),
]

POINTS = {"PLASTIC": 75, "ALUMINUM": 200, "OTHER": 0}


_PUSH_CHARS = "-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"


def _push_id(timestamp_ms: int) -> str:
    """Generates a Firebase-style push key locally (8 time chars + 12
    random chars, sorts chronologically). The Admin SDK's push() would
    cost a network round trip per key; this costs none."""
    time_chars = []
    for _ in range(8):
        time_chars.append(_PUSH_CHARS[timestamp_ms % 64])
        timestamp_ms //= 64
    random_chars = [random.choice(_PUSH_CHARS) for _ in range(12)]
    return "".join(reversed(time_chars)) + "".join(random_chars)


def eco_status_for(points: int) -> str:
    for label, min_points in ECO_TIERS:
        if points >= min_points:
            return label
    return "Eco-Beginner"


class FirebaseClient:
    def __init__(self, service_account_path: str, database_url: str, bin_id: str = "bin-001"):
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred, {"databaseURL": database_url})
        self.bin_id = bin_id

    def find_user_by_rfid(self, rfid_uid: str):
        users = db.reference("users").order_by_child("rfidUid").equal_to(rfid_uid).get()
        if not users:
            return None, None
        uid = next(iter(users))
        return uid, users[uid]

    def record_deposit(self, uid: str, item_type: str) -> int:
        points = POINTS[item_type]

        db.reference("transactions").push({
            "studentId": uid,
            "itemType": item_type,
            "pointsEarned": points,
            "timestamp": int(time.time() * 1000),
            "binId": self.bin_id,
        })

        user_ref = db.reference(f"users/{uid}")
        count_field = "plasticCount" if item_type == "PLASTIC" else "canCount"

        def update_user(current):
            if current is None:
                return current
            current["totalPoints"] = current.get("totalPoints", 0) + points
            current[count_field] = current.get(count_field, 0) + 1
            current["ecoStatus"] = eco_status_for(current["totalPoints"])
            return current

        result = user_ref.transaction(update_user)

        db.reference(f"leaderboard/{uid}").update({
            "totalPoints": result.get("totalPoints", 0) if result else 0,
        })
        return points

    def record_session(self, uid: str, item_types: list) -> int:
        """Saves a whole deposit session in 3 requests instead of 3 per
        item. Writes the same data as calling record_deposit() once per
        item: one /transactions record each, user totals + ecoStatus
        updated atomically, leaderboard mirror refreshed.

        Returns the total points awarded.
        """
        if not item_types:
            return 0

        # 1) every transaction record in one multi-path write
        now_ms = int(time.time() * 1000)
        updates = {}
        for i, item_type in enumerate(item_types):
            timestamp = now_ms + i  # +i keeps per-item ordering stable
            updates[_push_id(timestamp)] = {
                "studentId": uid,
                "itemType": item_type,
                "pointsEarned": POINTS[item_type],
                "timestamp": timestamp,
                "binId": self.bin_id,
            }
        db.reference("transactions").update(updates)

        # 2) one atomic update for the user's totals
        total_points = sum(POINTS[t] for t in item_types)
        counts = Counter(item_types)
        plastic = counts.get("PLASTIC", 0)
        cans = sum(n for t, n in counts.items() if t != "PLASTIC")

        def update_user(current):
            if current is None:
                return current
            current["totalPoints"] = current.get("totalPoints", 0) + total_points
            current["plasticCount"] = current.get("plasticCount", 0) + plastic
            current["canCount"] = current.get("canCount", 0) + cans
            current["ecoStatus"] = eco_status_for(current["totalPoints"])
            return current

        result = db.reference(f"users/{uid}").transaction(update_user)

        # 3) leaderboard mirror (skipped if the user was deleted meanwhile,
        # so we don't resurrect a leaderboard row for them)
        if result:
            db.reference(f"leaderboard/{uid}").update({
                "totalPoints": result.get("totalPoints", 0),
            })
        return total_points
