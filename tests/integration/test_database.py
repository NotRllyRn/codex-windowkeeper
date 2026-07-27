from pathlib import Path

import pytest

from windowkeeper.database import Database


@pytest.mark.asyncio
async def test_migrations_are_idempotent_and_foreign_keys_hold(tmp_path: Path) -> None:
    path = tmp_path / "windowkeeper.db"
    database = Database(path)
    database.start()
    version = await database.call(
        lambda connection: connection.execute(
            "SELECT max(version) FROM schema_migrations"
        ).fetchone()[0]
    )
    foreign_keys = await database.call(
        lambda connection: connection.execute("PRAGMA foreign_keys").fetchone()[0]
    )
    await database.close()
    assert version == 5
    assert foreign_keys == 1
    second = Database(path)
    second.start()
    assert (
        await second.call(lambda connection: connection.execute("PRAGMA quick_check").fetchone()[0])
        == "ok"
    )
    await second.close()
