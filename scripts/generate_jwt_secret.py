#!/usr/bin/env python3
"""
generate_jwt_secret.py

生成强随机 JWT_SECRET_KEY 的小工具。

用法示例:
  python generate_jwt_secret.py                 # 生成 32 字节的 URL-safe token 并打印
  python generate_jwt_secret.py --bytes 64      # 生成 64 字节（512-bit）
  python generate_jwt_secret.py --format hex    # hex 格式
  python generate_jwt_secret.py --outfile secret.txt --envvar JWT_SECRET_KEY
"""

import argparse
import base64
import os
import secrets
import sys


def generate_secret(nbytes: int, fmt: str) -> str:
    if fmt == "hex":
        return secrets.token_hex(nbytes)
    elif fmt == "urlsafe":
        # token_urlsafe takes nbytes and returns a URL-safe base64-encoded string
        return secrets.token_urlsafe(nbytes)
    elif fmt == "base64":
        raw = secrets.token_bytes(nbytes)
        return base64.b64encode(raw).decode("ascii")
    else:
        raise ValueError("Unsupported format: " + fmt)


def safe_write_file(path: str, content: str, make_private: bool = True):
    # Write file (overwrite) and try to set permissions to owner-only on POSIX
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        if make_private and os.name == "posix":
            os.chmod(path, 0o600)
        elif make_private and os.name == "nt":
            # On Windows, os.chmod has limited effect. We avoid raising errors.
            pass
    except Exception as e:
        print(f"警告：无法修改文件权限 ({e}). 请手动检查权限。", file=sys.stderr)


def append_env_file(path: str, key: str, value: str):
    line = f"{key}={value}\n"
    # If file exists, append; else create
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
    except Exception as e:
        print(f"警告：无法修改 .env 文件权限 ({e}).", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="生成强随机 JWT_SECRET_KEY")
    p.add_argument(
        "--bytes",
        type=int,
        default=32,
        help="生成的随机原始字节长度（默认 32 bytes = 256 bits）。更高的字节数更强壮。",
    )
    p.add_argument(
        "--format",
        choices=["hex", "urlsafe", "base64"],
        default="urlsafe",
        help="输出格式：hex / urlsafe / base64（默认 urlsafe）。urlsafe 常用于 env 与 URL。",
    )
    p.add_argument("--outfile", type=str, default=None, help="将密钥写入文件（覆盖）。")
    p.add_argument(
        "--envfile",
        type=str,
        default=None,
        help="将密钥以 KEY=VALUE 追加到指定的 env 文件（不会覆盖文件，只追加）。",
    )
    p.add_argument(
        "--envvar",
        type=str,
        default="JWT_SECRET_KEY",
        help="如果使用 --envfile，指定环境变量名（默认 JWT_SECRET_KEY）。",
    )
    args = p.parse_args()

    if args.bytes <= 0:
        print("错误：--bytes 必须为正整数。", file=sys.stderr)
        sys.exit(2)

    secret = generate_secret(args.bytes, args.format)
    print(secret)

    if args.outfile:
        safe_write_file(args.outfile, secret + "\n", make_private=True)
        print(f"已写入文件: {args.outfile}")

    if args.envfile:
        append_env_file(args.envfile, args.envvar, secret)
        print(f"已追加到 env 文件: {args.envfile} （键名：{args.envvar}）")

    # 安全提示
    print("\n安全提示：")
    print("- 请不要把生成的密钥提交到版本控制（git 等）。")
    print(
        "- 生产环境优先使用专用密钥管理服务（如 Vault、AWS Secrets Manager、Azure Key Vault）。"
    )
    print(
        "- 如果用于生产，请确保密钥至少为 32 bytes（256-bit），更高长度更安全（例如 64 bytes）。"
    )


if __name__ == "__main__":
    main()
