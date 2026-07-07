"""Seed adjuster queues and adjuster records into the database."""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.claimiq.db.models import AdjusterORM, Base, QueueORM

DATABASE_SYNC_URL = os.getenv(
    "DATABASE_SYNC_URL",
    "postgresql+psycopg2://claimiq:claimiq_dev@localhost:5432/claimiq",
)

QUEUES = [
    {"name": "standard", "skill_requirements": ["general"], "geography": "pan-india", "max_workload": 50},
    {"name": "senior-adjuster", "skill_requirements": ["senior", "complex"], "geography": "pan-india", "max_workload": 20},
    {"name": "fraud-investigation", "skill_requirements": ["fraud", "investigation"], "geography": "pan-india", "max_workload": 10},
    {"name": "fast-track", "skill_requirements": ["general"], "geography": "pan-india", "max_workload": 100},
]

ADJUSTERS = [
    {"name": "Arun Mehta", "queue": "standard", "skills": ["general", "health"], "geography": "South India"},
    {"name": "Priya Nair", "queue": "standard", "skills": ["general", "motor"], "geography": "North India"},
    {"name": "Vikram Singh", "queue": "senior-adjuster", "skills": ["senior", "complex", "health"], "geography": "pan-india"},
    {"name": "Deepa Krishnamurthy", "queue": "senior-adjuster", "skills": ["senior", "complex", "property"], "geography": "pan-india"},
    {"name": "Amit Joshi", "queue": "fraud-investigation", "skills": ["fraud", "investigation"], "geography": "pan-india"},
    {"name": "Sunita Rao", "queue": "fast-track", "skills": ["general"], "geography": "pan-india"},
    {"name": "Ravi Patel", "queue": "fast-track", "skills": ["general", "motor"], "geography": "West India"},
]


def seed():
    engine = create_engine(DATABASE_SYNC_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # Create queues
        queue_map = {}
        for q in QUEUES:
            existing = session.query(QueueORM).filter_by(name=q["name"]).first()
            if existing:
                queue_map[q["name"]] = existing
                continue
            orm = QueueORM(
                id=uuid.uuid4(),
                name=q["name"],
                skill_requirements=q["skill_requirements"],
                geography=q["geography"],
                max_workload=q["max_workload"],
            )
            session.add(orm)
            queue_map[q["name"]] = orm
            print(f"Created queue: {q['name']}")

        session.flush()

        # Create adjusters
        for a in ADJUSTERS:
            existing = session.query(AdjusterORM).filter_by(name=a["name"]).first()
            if existing:
                continue
            queue = queue_map.get(a["queue"])
            orm = AdjusterORM(
                id=uuid.uuid4(),
                name=a["name"],
                queue_id=queue.id if queue else None,
                skills=a["skills"],
                geography=a["geography"],
                current_workload=0.0,
                is_active=True,
            )
            session.add(orm)
            print(f"Created adjuster: {a['name']} → {a['queue']}")

        session.commit()
        print("Seed complete.")


if __name__ == "__main__":
    seed()
