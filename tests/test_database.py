"""Exercise the migration and ORM against a fresh in-memory database."""

import importlib.util
from pathlib import Path
import unittest
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, delete, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.base import Base
from app.models import Thread, User


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        path = (
            Path(__file__).resolve().parents[1]
            / "alembic/versions/0001_create_users_and_threads.py"
        )
        spec = importlib.util.spec_from_file_location("initial_migration", path)
        self.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.migration)
        spec = importlib.util.spec_from_file_location(
            "password_migration", path.parent / "0003_add_user_password.py"
        )
        self.password_migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.password_migration)
        self.run_migration(self.migration.upgrade)
        self.run_migration(self.password_migration.upgrade)

    def run_migration(self, operation):
        with self.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                operation()

    def test_migration_matches_models_and_can_be_reversed(self):
        with self.engine.connect() as connection:
            differences = compare_metadata(
                MigrationContext.configure(connection), Base.metadata
            )
            self.assertEqual(differences, [])

        self.run_migration(self.password_migration.downgrade)
        self.run_migration(self.migration.downgrade)
        self.assertEqual(inspect(self.engine).get_table_names(), [])
        self.run_migration(self.migration.upgrade)
        self.run_migration(self.password_migration.upgrade)
        self.assertEqual(
            set(inspect(self.engine).get_table_names()), {"users", "threads"}
        )

    def test_round_trip_defaults_relationships_and_cascade(self):
        with Session(self.engine) as session:
            user = User(email="user@example.com", threads=[Thread(title="Hello")])
            session.add(user)
            session.commit()
            user_id = user.id
            self.assertIsNotNone(user.created_at)
            self.assertIsNotNone(user.updated_at)
            session.expunge_all()

            loaded = session.scalar(
                select(User).options(selectinload(User.threads))
            )
            self.assertEqual(loaded.id, user_id)
            self.assertEqual(loaded.threads[0].user_id, user_id)
            self.assertEqual(loaded.threads[0].title, "Hello")
            self.assertIsNotNone(loaded.threads[0].created_at)

            # A bulk delete verifies that the database enforces the cascade.
            session.execute(delete(User).where(User.id == user_id))
            session.commit()
            self.assertEqual(session.scalars(select(Thread)).all(), [])

    def test_password_migration_preserves_existing_users(self):
        self.run_migration(self.password_migration.downgrade)
        user_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                {"id": user_id.hex, "email": "legacy@example.com"},
            )
        self.run_migration(self.password_migration.upgrade)
        with Session(self.engine) as session:
            user = session.get(User, user_id)
            self.assertEqual(user.email, "legacy@example.com")
            self.assertIsNone(user.password_hash)

    def test_email_unique_and_thread_owner_required(self):
        with Session(self.engine) as session:
            session.add(User(email="user@example.com"))
            session.commit()
            session.add(User(email="user@example.com"))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

            session.add(Thread(user_id=uuid4()))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

            session.add(Thread())
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()


if __name__ == "__main__":
    unittest.main()
