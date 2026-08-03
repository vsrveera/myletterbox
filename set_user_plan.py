"""
Admin utility — set a user's billing plan directly in Firestore.

Usage:
    python3 set_user_plan.py user@example.com free
    python3 set_user_plan.py user@example.com trial

Requires the same GCP credentials/project as the running app (e.g. run with
GOOGLE_APPLICATION_CREDENTIALS set, or `gcloud auth application-default login`).
"""
import sys
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

VALID_PLANS = {"free", "trial", "active", "past_due", "canceled"}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in VALID_PLANS:
        print(f"Usage: python3 set_user_plan.py <email> <{'|'.join(sorted(VALID_PLANS))}>")
        sys.exit(1)

    email, plan = sys.argv[1].strip().lower(), sys.argv[2]
    updates = {"plan": plan}
    if plan == "trial":
        updates["trial_ends_at"] = datetime.now(timezone.utc) + timedelta(days=30)

    firestore.Client().collection("users").document(email).set(updates, merge=True)
    print(f"Set plan={plan!r} for {email}")


if __name__ == "__main__":
    main()
