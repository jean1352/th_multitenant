import pytest
import asyncio
from typing import AsyncGenerator, Generator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from main import app
from app.core.database import Base, get_db
from app.core.config import settings
from app.modules.auth.models import User, UserRole
from app.core.security import create_access_token

# Usar DB de test en Postgres
TEST_DATABASE_URL = "postgresql+asyncpg://admin:secret_password@db:5432/test_db"

engine = create_async_engine(
    TEST_DATABASE_URL, 
    poolclass=NullPool
)

TestingSessionLocal = async_sessionmaker(
    bind=engine, 
    expire_on_commit=False, 
    autoflush=False
)

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()

@pytest.fixture
async def recruiter_token(db_session: AsyncSession) -> str:
    user = User(
        email="recruiter@test.com",
        full_name="Test Recruiter",
        role=UserRole.TH,
        is_active=True,
        hashed_password="hashed_password"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    return create_access_token({"sub": user.email, "id": user.id, "role": user.role.value})

@pytest.fixture
async def admin_token(db_session: AsyncSession) -> str:
    user = User(
        email="admin@test.com",
        full_name="Test Admin",
        role=UserRole.ADMIN,
        is_active=True,
        hashed_password="hashed_password"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    return create_access_token({"sub": user.email, "id": user.id, "role": user.role.value})
