"""
开发环境启动脚本
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import uvicorn  # noqa: E402
from app.core.config import get_settings  # noqa: E402

settings = get_settings()

if __name__ == "__main__":
    print(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"访问地址: http://{settings.APP_HOST}:{settings.APP_PORT}")
    print(f"API 文档: http://{settings.APP_HOST}:{settings.APP_PORT}/docs")

    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
        log_level="info",
    )
