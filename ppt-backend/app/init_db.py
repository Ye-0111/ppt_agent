"""Create missing application tables without deleting or replacing existing data."""

import argparse

from sqlalchemy.engine import Engine

from app.core.database import Base, engine
from app.models import agent_log, ppt, ppt_template, user  # noqa: F401: register models


def initialize_database(bind: Engine = engine) -> None:
    Base.metadata.create_all(bind=bind)


def main() -> None:
    parser = argparse.ArgumentParser(description="创建缺失的业务表；不删除数据，也不迁移已有表结构。")
    parser.parse_args()
    initialize_database()
    print("数据库表初始化完成：sys_user、sys_ppt、sys_ppt_template、sys_agent_log")


if __name__ == "__main__":
    main()
