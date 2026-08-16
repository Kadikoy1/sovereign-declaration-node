import os
from pathlib import Path

DB = Path(__file__).parent / "test.db"
DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB.as_posix()}"
os.environ["PUBLIC_BASE_URL"] = "https://protocol.test"
os.environ["CORS_ORIGINS"] = "https://protocol.test"

import pytest
from fastapi.testclient import TestClient
import main
from storage import engine


@pytest.fixture(autouse=True)
def reset_in_memory_rate_limit():
    main._requests.clear()
    yield
    main._requests.clear()


@pytest.fixture(scope="session")
def client():
    main.submit_evidence = lambda _: {"status":"pending","error_code":"ATTESTER_NOT_CONFIGURED"}
    with TestClient(main.app) as value:
        yield value
    engine.dispose()
    DB.unlink(missing_ok=True)
