import os

from sqlalchemy import create_engine

from alembic import context

engine = create_engine(
    os.environ["AELEV_TRANSLATOR_DATABASE_URL"], hide_parameters=True
)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
