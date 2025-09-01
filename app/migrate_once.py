from sqlalchemy import text

MIGRATION_LOCK_KEY_1 = 42         # любые ваши константы
MIGRATION_LOCK_KEY_2 = 20250831   # для устойчивого "имени" блокировки

async def ensure_subscription_type_pg(engine):
    async with engine.begin() as conn:
        # Чтобы несколько инстансов не выполняли одно и то же параллельно:
        await conn.execute(text("SELECT pg_advisory_lock(:k1, :k2)"),
                           {"k1": MIGRATION_LOCK_KEY_1, "k2": MIGRATION_LOCK_KEY_2})
        try:
            # Добавляем nullable-колонку, если её нет
            # В PG безопасно и идемпотентно:
            await conn.execute(text("""
                ALTER TABLE "users"
                ADD COLUMN IF NOT EXISTS "subscription_type" TEXT
            """))
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k1, :k2)"),
                               {"k1": MIGRATION_LOCK_KEY_1, "k2": MIGRATION_LOCK_KEY_2})