"""
运行测试脚本
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest  # noqa: E402

if __name__ == "__main__":
    # 运行测试
    exit_code = pytest.main(
        [
            "tests/",
            "-v",
            "--tb=short",
            "--color=yes",
        ]
    )
    sys.exit(exit_code)
