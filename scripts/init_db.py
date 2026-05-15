"""
数据库初始化脚本
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.database import init_db  # noqa: E402
from app.core.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


async def main():
    """初始化数据库表"""
    try:
        logger.info("开始初始化数据库...")
        await init_db()
        logger.info("数据库初始化成功！")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
