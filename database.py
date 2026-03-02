from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import psycopg2

URL = os.getenv("DATABASE_URL", "sqlite:///./freight.db")

if URL.startswith("postgres://"):
    URL = URL.replace("postgres://", "postgresql://", 1)

if "sqlite" in URL:
    engine = create_engine(URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def run_migrations():
    if "sqlite" in URL: return
    try:
        conn = psycopg2.connect(URL)
        conn.autocommit = True
        cur = conn.cursor()

        cols = [
            ("quotation_number", "VARCHAR(255)"),
            ("direction", "VARCHAR(50)"),
            ("incoterm", "VARCHAR(50)"),
            ("stuffing_date", "VARCHAR(50)"),
            ("agent", "VARCHAR(255)"),
            ("vessel", "VARCHAR(255)")
        ]

        for col_name, col_type in cols:
            try:
                cur.execute(f"ALTER TABLE shipments ADD COLUMN {col_name} {col_type};")
            except psycopg2.errors.DuplicateColumn:
                pass

        try:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS quotes (
                    id SERIAL PRIMARY KEY,
                    ref VARCHAR(255) UNIQUE,
                    client VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    pol VARCHAR(255) NOT NULL,
                    pod VARCHAR(255) NOT NULL,
                    mode VARCHAR(50) DEFAULT 'Ocean',
                    rate FLOAT NOT NULL,
                    totalTeu FLOAT NOT NULL,
                    notes TEXT,
                    status VARCHAR(50) DEFAULT 'pending',
                    containers TEXT,
                    created_at VARCHAR(100)
                );
            ''')
        except Exception as e:
            print(f"Error creating quotes table manually: {e}")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Migration error: {e}")
