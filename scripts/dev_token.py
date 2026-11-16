#!/usr/bin/env python3
"""本地/CI 用的 OIDC 测试 token 签发器（HS256）。

只在有 OIDC_DEV_HS256_SECRET 时可用；生产走身份源 RS256，不需要这个脚本。

    export OIDC_DEV_HS256_SECRET=dev-secret
    python scripts/dev_token.py admin            # 输出一个 5 分钟有效的 token
    python scripts/dev_token.py viewer --ttl 60
"""

import argparse
import os
import time

import jwt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["viewer", "editor", "admin"], default="admin", nargs="?")
    parser.add_argument("--ttl", type=int, default=300)
    parser.add_argument("--email", default="dev@corp.com")
    args = parser.parse_args()

    secret = os.getenv("OIDC_DEV_HS256_SECRET", "")
    if not secret:
        raise SystemExit("请先 export OIDC_DEV_HS256_SECRET=...")

    now = int(time.time())
    payload = {
        "iss": os.getenv("OIDC_ISSUER", "http://localhost/realms/dev"),
        "aud": os.getenv("OIDC_AUDIENCE", "data-catalog-api"),
        "sub": f"dev-{args.role}",
        "email": args.email,
        "preferred_username": args.email.split("@")[0],
        "iat": now,
        "exp": now + args.ttl,
        "realm_access": {"roles": [f"data-catalog-{args.role}"]},
    }
    print(jwt.encode(payload, secret, algorithm="HS256"))


if __name__ == "__main__":
    main()
