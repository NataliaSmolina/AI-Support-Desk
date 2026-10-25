"""Root conftest for all kb-index tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

COMPOSE_FILE = Path(__file__).parent / "docker-compose.integration.yml"
PROJECT_NAME = "kb-index-integration"

# Environment variables for integration tests
INTEGRATION_ENV = {
    "TEI_EMBED_URL": "http://127.0.0.1:8082",
    "KB_DIR": str(Path(__file__).parent),
    "EMBED_BATCH_SIZE": "8",
    "EMBEDDING_DIMENSION": "384",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5435",
    "POSTGRES_USER": "kb_index_it",
    "POSTGRES_PASSWORD": "kb_index_it_secret",
    "POSTGRES_DB": "kb_index_it",
}


def _run_compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run docker-compose with the specified file and project name."""
    cmd = ["docker", "compose", "-p", PROJECT_NAME, "-f", str(COMPOSE_FILE), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


@pytest.fixture(scope="session", autouse=True)
def integration_environment():
    """Inject environment variables BEFORE first import of kb_index.config."""
    original = {k: os.environ.get(k) for k in INTEGRATION_ENV}
    for key, value in INTEGRATION_ENV.items():
        os.environ[key] = value

    yield

    # Restore original values
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="session")
def containers(integration_environment):
    """Start TEI + Postgres, wait for healthcheck, cleanup after tests."""
    if not COMPOSE_FILE.exists():
        pytest.fail(
            f"❌ Compose file not found: {COMPOSE_FILE}\n"
            "Create services/kb-index/tests/docker-compose.integration.yml"
        )

    print(f"\n[integration] Compose file: {COMPOSE_FILE}")
    print("[integration] Starting containers (ports 8082 and 5435)...")

    result = _run_compose("up", "-d", "--wait", "--wait-timeout", "600")

    if result.returncode != 0:
        print(f"\n[integration] docker compose up FAILED (exit code {result.returncode})")
        print("=== STDOUT ===")
        print(result.stdout)
        print("=== STDERR ===")
        print(result.stderr)

        print("\n[integration] Container status:")
        ps_result = _run_compose("ps", "-a", check=False)
        print(ps_result.stdout)

        print("\n[integration] Container logs:")
        logs_result = _run_compose("logs", check=False)
        print(logs_result.stdout)
        print(logs_result.stderr)

        print("\n[integration] Port usage check (8082 and 5435):")
        lsof = subprocess.run(
            ["ss", "-tlnp"], capture_output=True, text=True, check=False
        )
        for port in [8082, 5435]:
            for line in lsof.stdout.splitlines():
                if f":{port}" in line:
                    print(f"  port {port}: {line.strip()}")

        pytest.fail(
            "Failed to start containers for integration test. "
            "Check logs above."
        )

    yield

    print("\n[integration] Stopping containers...")
    _run_compose("down", "-v", "--remove-orphans", check=False)


@pytest.fixture
def tmp_kb_dir(tmp_path: Path) -> Path:
    """Isolated directory with MD files for each test."""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    os.environ["KB_DIR"] = str(kb_dir)

    return kb_dir


@pytest.fixture(scope="session")
def _ensure_containers(containers):
    """Ensure containers are started before any test in the module."""
    return containers