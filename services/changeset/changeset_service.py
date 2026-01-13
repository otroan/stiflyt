"""Changeset service for managing changesets."""
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from services.database import db_connection
from psycopg.rows import dict_row
from .models import ChangesetResponse


class ChangesetService:
    """Service for managing changesets."""

    @staticmethod
    def create(
        title: str,
        created_by: str,
        description: Optional[str] = None,
        area: Optional[str] = None,
        linked_issue_url: Optional[str] = None,
        base_snapshot: str = "default",
    ) -> str:
        """Create a new changeset. Returns changeset_id."""
        changeset_id = str(uuid.uuid4())
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO changeset.changeset
                    (id, title, description, area, status, created_by, created_at, updated_at, base_snapshot, linked_issue_url)
                    VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s)
                    """,
                    (
                        changeset_id,
                        title,
                        description,
                        area,
                        created_by,
                        datetime.utcnow(),
                        datetime.utcnow(),
                        base_snapshot,
                        linked_issue_url,
                    ),
                )
                return changeset_id

    @staticmethod
    def get(changeset_id: str) -> Optional[ChangesetResponse]:
        """Get a changeset by ID."""
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, title, description, area, status, created_by, 
                           created_at, updated_at, base_snapshot, linked_issue_url, pr_url
                    FROM changeset.changeset
                    WHERE id = %s
                    """,
                    (changeset_id,),
                )
                row = cur.fetchone()
                if row:
                    return ChangesetResponse(**row)
                return None

    @staticmethod
    def update_status(changeset_id: str, status: str) -> bool:
        """Update changeset status."""
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE changeset.changeset
                    SET status = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (status, datetime.utcnow(), changeset_id),
                )
                return cur.rowcount > 0

    @staticmethod
    def update_pr_url(changeset_id: str, pr_url: str) -> bool:
        """Update changeset PR URL."""
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE changeset.changeset
                    SET pr_url = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (pr_url, datetime.utcnow(), changeset_id),
                )
                return cur.rowcount > 0

    @staticmethod
    def list_all(limit: int = 100, offset: int = 0) -> List[ChangesetResponse]:
        """List all changesets."""
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, title, description, area, status, created_by,
                           created_at, updated_at, base_snapshot, linked_issue_url, pr_url
                    FROM changeset.changeset
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
                return [ChangesetResponse(**row) for row in cur.fetchall()]
