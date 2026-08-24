import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.getenv("TEST_POSTGRES_ADMIN_URL")


@pytest.mark.skipif(not ADMIN_URL or not shutil.which("createdb"), reason="requires TEST_POSTGRES_ADMIN_URL")
def test_alembic_and_plain_sql_create_equivalent_schema() -> None:
    left = f"trading_alembic_{uuid.uuid4().hex[:8]}"
    right = f"trading_sql_{uuid.uuid4().hex[:8]}"
    admin = ADMIN_URL or ""
    subprocess.run(["createdb", "--maintenance-db", admin, left], check=True)
    subprocess.run(["createdb", "--maintenance-db", admin, right], check=True)
    try:
        left_url = f"{admin.rsplit('/', 1)[0]}/{left}"
        right_url = f"{admin.rsplit('/', 1)[0]}/{right}"
        env = {**os.environ, "TRADING_DATABASE_URL": left_url}
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
        subprocess.run(["psql", right_url, "-f", str(ROOT / "sql/business_schema.sql")], check=True)
        subprocess.run(["psql", right_url, "-f", str(ROOT / "sql/business_seed.sql")], check=True)
        left_dump = subprocess.check_output(["pg_dump", "--schema-only", "--no-owner", left_url], text=True)
        right_dump = subprocess.check_output(["pg_dump", "--schema-only", "--no-owner", right_url], text=True)

        def normalize(value: str) -> str:
            return "\n".join(
                line
                for line in value.splitlines()
                if "alembic_version" not in line and not line.startswith("--")
            )

        assert normalize(left_dump) == normalize(right_dump)
    finally:
        subprocess.run(["dropdb", "--maintenance-db", admin, "--if-exists", left], check=False)
        subprocess.run(["dropdb", "--maintenance-db", admin, "--if-exists", right], check=False)
