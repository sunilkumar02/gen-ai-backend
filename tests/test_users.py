import os
import base64
import json
import logging
import unittest
from uuid import UUID, uuid4

# Tests never connect to PostgreSQL or need a local .env.
for key, value in {
    "DB_USER": "test", "DB_PASSWORD": "test", "DB_HOST": "localhost",
    "DB_PORT": "5432", "DB_NAME": "test",
}.items():
    os.environ.setdefault(key, value)

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.router.users import router
from app.router.auth import router as auth_router
from app.router.thread import router as thread_router
from app.router.errors import ERROR_RESPONSES, configure_api
from app.db.base import Base
from app.db.database import get_db
from app.models import Thread, User

PASSWORD = "Example-password-123!"


class UserAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")

        @event.listens_for(self.engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.app = FastAPI(responses=ERROR_RESPONSES)
        configure_api(self.app)
        self.app.include_router(router)
        self.app.include_router(auth_router)
        self.app.include_router(thread_router)

        async def database_override():
            async with self.sessions() as session:
                yield session

        self.app.dependency_overrides[get_db] = database_override
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()

    async def create_user(self, email="user@example.com", **fields):
        response = await self.client.post(
            "/users", json={"email": email, "password": PASSWORD, **fields}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn("password", response.json())
        self.assertNotIn("password_hash", response.json())
        return response.json()

    async def test_create_read_update_delete_and_thread_cascade(self):
        user = await self.create_user(name="Original")
        user_id = user["id"]
        async with self.sessions() as session:
            stored = await session.get(User, UUID(user_id))
            self.assertNotEqual(stored.password_hash, PASSWORD)
            self.assertTrue(PasswordHash.recommended().verify(PASSWORD, stored.password_hash))
            session.add(Thread(user_id=stored.id, title="Test"))
            await session.commit()

        response = await self.client.get(f"/users/{user_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Original")
        response = await self.client.patch(
            f"/users/{user_id}", json={"name": "Updated", "email": "NEW@example.com"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["email"], "new@example.com")
        self.assertEqual(response.json()["name"], "Updated")
        self.assertNotIn("password_hash", response.json())
        self.assertEqual((await self.client.delete(f"/users/{user_id}")).status_code, 204)
        self.assertEqual((await self.client.get(f"/users/{user_id}")).status_code, 404)
        async with self.sessions() as session:
            self.assertEqual((await session.scalars(select(Thread))).all(), [])

    async def test_duplicate_email_and_conflicting_update(self):
        await self.create_user()
        response = await self.client.post(
            "/users", json={"email": "USER@example.com", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 409)
        other = await self.create_user("other@example.com")
        response = await self.client.patch(
            f"/users/{other['id']}", json={"email": "USER@example.com"}
        )
        self.assertEqual(response.status_code, 409)

    async def test_list_pagination_and_input_validation(self):
        first = await self.create_user()
        await self.create_user("other@example.com")
        response = await self.client.get("/users?limit=1&offset=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertNotIn("password_hash", response.json()[0])
        for payload in [
            {"email": "bad", "password": PASSWORD},
            {"email": "good@example.com", "password": "short"},
            {"email": "good@example.com", "password": PASSWORD, "is_admin": True},
        ]:
            self.assertEqual((await self.client.post("/users", json=payload)).status_code, 422)
        for payload in [{"email": None}, {"password": None}]:
            self.assertEqual((await self.client.patch(f"/users/{first['id']}", json=payload)).status_code, 422)
        self.assertEqual((await self.client.get("/users?limit=101")).status_code, 422)
        self.assertEqual((await self.client.get("/users/not-a-uuid")).status_code, 422)
        missing = str(uuid4())
        self.assertEqual((await self.client.get(f"/users/{missing}")).status_code, 404)
        self.assertEqual((await self.client.patch(f"/users/{missing}", json={"name": "New"})).status_code, 404)
        self.assertEqual((await self.client.delete(f"/users/{missing}")).status_code, 404)

    async def test_password_update_and_name_clear(self):
        user = await self.create_user(name="Example")
        response = await self.client.patch(
            f"/users/{user['id']}", json={"password": "Changed-password-456!", "name": None}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["name"])
        self.assertNotIn("password", response.json())
        async with self.sessions() as session:
            stored = await session.get(User, UUID(user["id"]))
            self.assertTrue(PasswordHash.recommended().verify("Changed-password-456!", stored.password_hash))

    async def test_openapi_has_login_without_jwt(self):
        schema = self.app.openapi()
        self.assertIn("/auth/login", schema["paths"])
        self.assertNotIn("securitySchemes", schema.get("components", {}))

    async def test_login_success_uses_email_and_never_returns_credentials(self):
        user = await self.create_user()
        response = await self.client.post("/auth/login", json={
            "username": " USER@example.com ",
            "password": base64.b64encode(PASSWORD.encode()).decode(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), user)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn("password", response.json())
        self.assertNotIn("password_hash", response.json())
        self.assertNotIn("access_token", response.json())

    async def test_login_failure_does_not_reveal_account_existence(self):
        await self.create_user()
        responses = []
        for username, password in [
            ("user@example.com", "wrong-password"),
            ("missing@example.com", PASSWORD),
        ]:
            response = await self.client.post("/auth/login", json={
                "username": username,
                "password": base64.b64encode(password.encode()).decode(),
            })
            self.assertEqual(response.status_code, 403)
            body = response.json()
            self.assertEqual(body["request_id"], response.headers["X-Request-ID"])
            UUID(body["request_id"])
            responses.append(body["error"])
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(responses[0]["message"], "Invalid username or password")

    async def test_login_legacy_and_corrupt_hashes_are_forbidden(self):
        async with self.sessions() as session:
            session.add_all([
                User(email="legacy@example.com"),
                User(email="corrupt@example.com", password_hash="invalid-hash"),
            ])
            await session.commit()
        for email in ("legacy@example.com", "corrupt@example.com"):
            response = await self.client.post("/auth/login", json={
                "username": email,
                "password": base64.b64encode(PASSWORD.encode()).decode(),
            })
            self.assertEqual(response.status_code, 403)

    async def test_invalid_base64_utf8_and_missing_fields(self):
        for encoded in ("not valid base64", "////", "IA==" * 200, "A" * 688):
            response = await self.client.post("/auth/login", json={
                "username": "user@example.com", "password": encoded,
            })
            self.assertEqual(response.status_code, 422, response.text)
            body = response.json()
            self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
            self.assertNotIn(encoded, response.text)
        response = await self.client.post("/auth/login", json={})
        self.assertEqual(response.status_code, 422)

    async def test_error_handling_and_logs_do_not_expose_secrets(self):
        from sqlalchemy.exc import OperationalError

        secret = "secret-value-that-must-not-appear"

        @self.app.get("/test/unexpected")
        async def unexpected():
            raise RuntimeError(secret)

        @self.app.get("/test/database")
        async def unavailable():
            raise OperationalError("SELECT secret", {"password": secret}, Exception(secret))

        with self.assertLogs("app.api", level="INFO") as captured:
            for path, status in [("/test/unexpected", 500), ("/test/database", 503), ("/missing", 404)]:
                response = await self.client.get(
                    path + "?password=" + secret,
                    headers={"Authorization": "Bearer " + secret, "Origin": "http://localhost:3000"},
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:3000")
                self.assertEqual(response.json()["request_id"], response.headers["X-Request-ID"])
                self.assertNotIn(secret, response.text)
            response = await self.client.post(
                "/users", json={"email": "user@example.com", "password": secret, "extra": secret}
            )
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(secret, response.text)
        output = "\n".join(captured.output)
        self.assertNotIn(secret, output)
        self.assertNotIn("SELECT secret", output)
        events = [json.loads(record.getMessage()) for record in captured.records]
        requests = [event for event in events if event["event"] == "api_request"]
        self.assertEqual(len(requests), 4)
        self.assertEqual([event["status"] for event in requests], [500, 503, 404, 422])
        self.assertTrue(all(event["duration_ms"] >= 0 for event in requests))
        self.assertTrue(any(event["event"] == "unexpected_error" for event in events))
        self.assertTrue(any(event["event"] == "database_error" for event in events))

    async def test_standard_errors_keep_http_headers_and_redact_validation(self):
        response = await self.client.put("/auth/login", json={})
        self.assertEqual(response.status_code, 405)
        self.assertIn("POST", response.headers["Allow"])
        self.assertEqual(response.json()["error"]["code"], "METHOD_NOT_ALLOWED")
        response = await self.client.post("/auth/login", content="{", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        for issue in response.json()["error"]["details"]:
            self.assertEqual(set(issue), {"location", "message", "type"})

    async def test_cors_preflight_allows_local_frontend_and_is_logged(self):
        with self.assertLogs("app.api", level="INFO") as captured:
            for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
                response = await self.client.options("/auth/login", headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,authorization,x-request-id",
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Access-Control-Allow-Origin"], origin)
                self.assertEqual(response.headers["Access-Control-Allow-Credentials"], "true")
                self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
                self.assertIn("Origin", response.headers["Vary"])
                UUID(response.headers["X-Request-ID"])
        events = [json.loads(record.getMessage()) for record in captured.records]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event["method"] == "OPTIONS" and event["status"] == 200 for event in events))

    async def test_cors_allows_browser_to_read_success_and_auth_errors(self):
        headers = {"Origin": "http://localhost:3000"}
        responses = [
            (await self.client.get("/users", headers=headers), 200),
            (await self.client.post("/auth/login", json={}, headers=headers), 422),
            (await self.client.post("/auth/login", json={
                "username": "missing@example.com",
                "password": base64.b64encode(PASSWORD.encode()).decode(),
            }, headers=headers), 403),
        ]
        for response, status in responses:
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], headers["Origin"])
            self.assertIn("X-Request-ID", response.headers["Access-Control-Expose-Headers"])

    async def test_cors_rejects_unlisted_origins(self):
        response = await self.client.options("/auth/login", headers={
            "Origin": "https://unlisted.example.com",
            "Access-Control-Request-Method": "POST",
        })
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        response = await self.client.get("/users", headers={"Origin": "https://unlisted.example.com"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    async def test_thread_crud_and_filtering(self):
        user = await self.create_user()
        other = await self.create_user("other@example.com")
        created = []
        for owner in (user, user, other):
            response = await self.client.post("/thread", json={"user_id": owner["id"], "title": "New thread"})
            self.assertEqual(response.status_code, 201, response.text)
            thread = response.json()
            self.assertEqual(thread["user_id"], owner["id"])
            self.assertTrue(thread["created_at"])
            self.assertTrue(thread["updated_at"])
            created.append(thread)
        response = await self.client.get("/thread", params={"user_id": user["id"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()}, {item["id"] for item in created[:2]})
        self.assertEqual(len((await self.client.get("/thread?limit=1&offset=1")).json()), 1)
        path = "/thread/" + created[0]["id"]
        self.assertEqual((await self.client.get(path)).json(), created[0])
        response = await self.client.patch(path, json={"title": "Renamed"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Renamed")
        self.assertEqual(response.json()["created_at"], created[0]["created_at"])
        self.assertEqual(response.json()["user_id"], user["id"])
        response = await self.client.patch(path, json={"title": None})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["title"])
        self.assertEqual((await self.client.delete(path)).status_code, 204)
        self.assertEqual((await self.client.get(path)).status_code, 404)
        self.assertEqual((await self.client.get("/users/" + user["id"])).status_code, 200)

    async def test_deleting_user_removes_all_their_threads_only(self):
        user = await self.create_user()
        other = await self.create_user("other@example.com")
        ids = []
        for owner in (user, user, other):
            response = await self.client.post("/thread", json={"user_id": owner["id"], "title": "Cascade test"})
            self.assertEqual(response.status_code, 201)
            ids.append(response.json()["id"])
        self.assertEqual((await self.client.delete("/users/" + user["id"])).status_code, 204)
        for thread_id in ids[:2]:
            self.assertEqual((await self.client.get("/thread/" + thread_id)).status_code, 404)
        self.assertEqual((await self.client.get("/thread/" + ids[2])).status_code, 200)
        self.assertEqual((await self.client.get("/thread", params={"user_id": user["id"]})).json(), [])
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(Thread.id))), [UUID(ids[2])])

    async def test_thread_validation_missing_owner_and_missing_thread(self):
        response = await self.client.post("/thread", json={"user_id": str(uuid4()), "title": "Test"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "User not found")
        user = await self.create_user()
        for payload in [
            {"user_id": "invalid", "title": "Test"},
            {"title": "Test"},
            {"user_id": user["id"], "title": ""},
            {"user_id": user["id"], "title": "a" * 256},
            {"user_id": user["id"], "title": "Test", "created_at": "2020-01-01T00:00:00Z"},
        ]:
            self.assertEqual((await self.client.post("/thread", json=payload)).status_code, 422)
        for query in ("user_id=invalid", "limit=101", "offset=-1"):
            self.assertEqual((await self.client.get("/thread?" + query)).status_code, 422)
        self.assertEqual((await self.client.get("/thread/invalid")).status_code, 422)
        path = "/thread/" + str(uuid4())
        self.assertEqual((await self.client.get(path)).status_code, 404)
        self.assertEqual((await self.client.patch(path, json={"title": "Missing"})).status_code, 404)
        self.assertEqual((await self.client.delete(path)).status_code, 404)
        thread = (await self.client.post("/thread", json={"user_id": user["id"], "title": "Test"})).json()
        response = await self.client.patch("/thread/" + thread["id"], json={"user_id": str(uuid4())})
        self.assertEqual(response.status_code, 422)
