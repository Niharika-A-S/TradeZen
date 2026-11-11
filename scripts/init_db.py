"""Database initialization script: creates all tables and seed data."""
import sys
import logging
from sqlalchemy import text

from app.database import engine, Base, SessionLocal
from app.models import User, UserProfile, PriceBar, Account

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def ensure_database_exists():
    """Checks if the target database exists; if not, creates it via the default PostgreSQL maintenance connection."""
    target_db = engine.url.database
    if not target_db:
        return
    try:
        from sqlalchemy import create_engine
        maintenance_url = engine.url.set(database="postgres")
        m_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
        with m_engine.connect() as conn:
            check = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": target_db}
            ).scalar()
            if not check:
                logger.info("Database '%s' does not exist. Creating it...", target_db)
                conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                logger.info("Database '%s' created successfully.", target_db)
            else:
                logger.info("Database '%s' already exists.", target_db)
        m_engine.dispose()
    except Exception as e:
        logger.warning(
            "Could not verify/create database '%s' via maintenance connection (%s). Attempting direct connection.",
            target_db,
            e,
        )


def init_database(drop_first: bool = False):
    """Creates all tables defined in SQLAlchemy models."""
    ensure_database_exists()
    logger.info("Connecting to database: %s", engine.url)

    if drop_first:
        logger.warning("Dropping all existing tables...")
        Base.metadata.drop_all(bind=engine)

    logger.info("Creating tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created successfully: %s", list(Base.metadata.tables.keys()))

    # Ensure default user, user profile, and paper account exist
    with SessionLocal() as session:
        default_user = session.query(User).filter_by(username="default_trader").first()
        if not default_user:
            default_user = User(
                username="default_trader",
                email="trader@tradezen.local"
            )
            profile = UserProfile(user=default_user)
            account = Account(user=default_user, cash_balance=10_00_000.0, initial_cash=10_00_000.0)
            session.add(default_user)
            session.add(profile)
            session.add(account)
            session.commit()
            logger.info("Created default user '%s' (id=%d) with trading profile and 10L cash account.", default_user.username, default_user.id)
        else:
            # Ensure account exists for existing user
            acc = session.query(Account).filter_by(user_id=default_user.id).first()
            if not acc:
                acc = Account(user_id=default_user.id, cash_balance=10_00_000.0, initial_cash=10_00_000.0)
                session.add(acc)
                session.commit()
                logger.info("Created 10L cash account for existing user '%s'.", default_user.username)
            logger.info("Default user '%s' already exists (id=%d).", default_user.username, default_user.id)


if __name__ == "__main__":
    drop = "--drop" in sys.argv
    init_database(drop_first=drop)
