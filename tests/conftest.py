"""测试配置"""

import os
from typing import AsyncGenerator

# 设置测试环境变量（必须在导入app之前）
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DATABASE_USER", "test")
os.environ.setdefault("DATABASE_PASSWORD", "test")
os.environ.setdefault("DATABASE_NAME", "test")
os.environ.setdefault("AI_API_KEY", "test-api-key")
os.environ.setdefault("AI_BASE_URL", "https://api.test.com")
os.environ.setdefault("AI_MODEL_NAME", "test-model")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core import hash_password, create_access_token, get_db, Base
from app.models import Doctor
from main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_maker = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture
def legacy_uploads(monkeypatch):
    """Old API regression tests explicitly opt into the legacy compartment."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "MEDICAL_UPLOAD_AUTH_REQUIRED", False)


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    """Fail instead of reaching a real AI or authorization endpoint in tests."""
    import httpx

    def deny(*args, **kwargs):
        raise AssertionError(
            "Live HTTP is forbidden in tests; use MockTransport or AI mocks"
        )

    async def deny_async(*args, **kwargs):
        deny()

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_async)


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """创建测试数据库会话"""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_maker() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def test_doctor(db_session: AsyncSession) -> Doctor:
    """创建测试医生"""
    doctor = Doctor(
        username="test_doctor",
        password_hash=hash_password("password123"),
        name="测试医生",
        gender="MALE",
        phone="13900139000",
        department="中医科",
        position="主治医师",
    )
    db_session.add(doctor)
    await db_session.commit()
    await db_session.refresh(doctor)
    return doctor


@pytest.fixture(scope="function")
def auth_token(test_doctor: Doctor) -> str:
    """创建测试认证令牌"""
    return create_access_token(
        data={"doctor_id": test_doctor.doctor_id, "username": test_doctor.username}
    )


@pytest.fixture(scope="function")
def auth_headers(auth_token: str) -> dict:
    """创建认证请求头"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """创建测试客户端"""

    async def override_get_db():
        try:
            yield db_session
            await db_session.commit()
        except BaseException:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


class UploadVerifier:
    def __init__(self):
        import httpx
        from tests.org_helpers import identity

        self.requests = []
        self.responses = {
            "upload-a": httpx.Response(200, json=identity("org-a")),
            "upload-b": httpx.Response(200, json=identity("org-b")),
        }
        self.error = None

    def handle(self, request):
        import httpx

        self.requests.append(request)
        if self.error is not None:
            raise self.error
        token = request.headers["authorization"].removeprefix("Bearer ")
        return self.responses.get(
            token,
            httpx.Response(
                401,
                json={
                    "requestId": "test-rejected",
                    "code": "AUTH_TOKEN_INVALID",
                    "message": "invalid",
                    "data": None,
                },
            ),
        )


@pytest.fixture
def verifier(monkeypatch):
    import httpx
    import app.core.upload_auth as upload_auth
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "MEDICAL_UPLOAD_AUTH_REQUIRED", True)
    monkeypatch.setattr(get_settings(), "APKIO_BASE_URL", "https://apkio.invalid/api")
    verifier = UploadVerifier()
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["verify"] is True
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"].connect == 2
        return real_client(transport=httpx.MockTransport(verifier.handle), **kwargs)

    monkeypatch.setattr(upload_auth.httpx, "AsyncClient", factory)
    return verifier
