from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os, logging

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./freight.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = "sqlite" in DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=True,
)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def set_wal_mode(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def run_migrations():
    """Safe column-add migrations — won't fail if column already exists."""
    migrations = [
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS booking_no VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS client_email VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS note TEXT",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS vessel VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS shipsgo_id INTEGER",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS last_tracked VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS created_at VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS ref2 VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS etd VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS quotation_number VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS direction VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS incoterm VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS stuffing_date VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS agent VARCHAR",
        "CREATE TABLE IF NOT EXISTS alert_logs (id SERIAL PRIMARY KEY, key VARCHAR NOT NULL, sent_date VARCHAR NOT NULL, created_at VARCHAR)",
        """CREATE TABLE IF NOT EXISTS quotations (
            id SERIAL PRIMARY KEY, ref VARCHAR NOT NULL UNIQUE,
            mode VARCHAR DEFAULT 'Ocean', client VARCHAR, client_email VARCHAR,
            carrier VARCHAR, pol VARCHAR, pod VARCHAR, etd VARCHAR, eta VARCHAR,
            booking_no VARCHAR, incoterm VARCHAR, status VARCHAR DEFAULT 'Pending',
            note TEXT, shipper VARCHAR, consignee VARCHAR,
            created_at VARCHAR, updated_at VARCHAR
        )""",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS shipper VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS consignee VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS updated_at VARCHAR",
    ]
    try:
        with engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
    except Exception as e:
        logger.warning(f"Migration error: {e}")

