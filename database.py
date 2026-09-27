import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from influxdb_client_3 import InfluxDBClient3

load_dotenv()

# ============================================================
# 1. CONEXIÓN A POSTGRESQL / NEON (Taller 1)
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida. Revisa tu archivo .env")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# 2. CONEXIÓN A INFLUXDB 3 (Telemetría MQTT - Taller 2)
# ============================================================
INFLUX_HOST = os.getenv("INFLUX_HOST", "http://localhost:8181")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_DATABASE = os.getenv("INFLUX_DATABASE", "sensores")

def get_influx_client():
    """
    Retorna la instancia del cliente InfluxDB 3 para consultar la telemetría.
    """
    if not INFLUX_TOKEN:
        raise RuntimeError("INFLUX_TOKEN no está definido en el archivo .env")
    
    return InfluxDBClient3(
        host=INFLUX_HOST,
        token=INFLUX_TOKEN,
        database=INFLUX_DATABASE
    )