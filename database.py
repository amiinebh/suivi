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
    migrations = [
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS bookingno VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS clientemail VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS note TEXT",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS vessel VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS shipsgoid INTEGER",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS lasttracked VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS createdat VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS ref2 VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS etd VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS quotationnumber VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS direction VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS incoterm VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS stuffingdate VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS agent VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS shipper VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS consignee VARCHAR",
        "ALTER TABLE shipments ADD COLUMN IF NOT EXISTS teu VARCHAR",
        """CREATE TABLE IF NOT EXISTS quotations (
            id SERIAL PRIMARY KEY, ref VARCHAR NOT NULL UNIQUE,
            mode VARCHAR DEFAULT 'Ocean', client VARCHAR, clientemail VARCHAR,
            carrier VARCHAR, pol VARCHAR, pod VARCHAR, etd VARCHAR, eta VARCHAR,
            bookingno VARCHAR, incoterm VARCHAR, status VARCHAR DEFAULT 'Pending',
            note TEXT, shipper VARCHAR, consignee VARCHAR,
            createdat VARCHAR, updatedat VARCHAR
        )""",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS shipper VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS consignee VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS updatedat VARCHAR",
        """CREATE TABLE IF NOT EXISTS alertlogs (
            id SERIAL PRIMARY KEY, key VARCHAR NOT NULL,
            sentdate VARCHAR NOT NULL, createdat VARCHAR
        )""",
    ]
    try:
        with engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    log.debug(f"Migration skipped: {e}")
    except Exception as e:
        log.warning(f"Migration error: {e}")
