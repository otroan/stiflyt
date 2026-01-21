"""Event store for changeset events."""
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from services.operational_database import op_db_connection
from psycopg.rows import dict_row
from .models import ChangeEvent, EventType


class EventStore:
    """Event store for managing changeset events."""

    @staticmethod
    def add_event(
        changeset_id: str,
        user_id: str,
        event: Dict,
    ) -> str:
        """Add an event to a changeset. Returns event_id."""
        with op_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                event_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO changeset.change_event
                    (event_id, changeset_id, ts, user_id, event)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    RETURNING event_id
                    """,
                    (event_id, changeset_id, datetime.utcnow(), user_id, json.dumps(event)),
                )
                return event_id

    @staticmethod
    def get_events(changeset_id: str) -> List[Dict]:
        """Get all events for a changeset, ordered by timestamp."""
        with op_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT event_id, changeset_id, ts, user_id, event
                    FROM changeset.change_event
                    WHERE changeset_id = %s
                    ORDER BY ts ASC
                    """,
                    (changeset_id,),
                )
                return [
                    {
                        "event_id": str(row["event_id"]),
                        "changeset_id": row["changeset_id"],
                        "ts": row["ts"],
                        "user_id": row["user_id"],
                        "event": row["event"],
                    }
                    for row in cur.fetchall()
                ]

    @staticmethod
    def get_event(event_id: str) -> Optional[Dict]:
        """Get a specific event by ID."""
        with op_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT event_id, changeset_id, ts, user_id, event
                    FROM changeset.change_event
                    WHERE event_id = %s
                    """,
                    (event_id,),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "event_id": str(row["event_id"]),
                        "changeset_id": row["changeset_id"],
                        "ts": row["ts"],
                        "user_id": row["user_id"],
                        "event": row["event"],
                    }
                return None
