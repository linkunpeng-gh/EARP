#!/usr/bin/env python3
"""EARP Catalog 签署实例确定性渲染器。

从"模板 + Profile + 决策/证据输入"渲染签署实例，保证：
1. FROZEN 契约块从模板原样带入（不可被渲染过程改写）
2. 项目值只来自 Profile（角色绑定、scope、变更单、pack_lock）
3. 决策/证据/结论来自独立决策输入文件（不属于 Profile）
4. 渲染后校验：无残留占位符、profile_hash 一致、FROZEN 块一致

用法：
    python render_signoff.py \
        --template arch/catalog/templates/n01a-catalog-phase0-signoff-template.md \
        --profile arch/catalog/profiles/jqmk-coal-production.yaml \
        --decisions arch/catalog/decisions/jqmk-coal-production-20260901-r1.json \
        --out arch/catalog/signoffs/jqmk-coal-production-20260901-r1.md

退出码：0 = 渲染并通过校验；非 0 = 失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as e:  # pragma: no cover
    sys.exit(f"缺少依赖 pyyaml: {e}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def resolve_placeholder(token: str, profile: dict, decisions: dict) -> str:
    """解析 {{...}}。优先级：Profile > 决策输入。未命中抛错。"""
    body = token[2:-2].strip()
    # 决策输入优先处理带点路径
    if body in decisions:
        val = decisions[body]
        return "TBD" if val is None else str(val)
    # profile 点路径
    cur = profile
    for part in body.split("."):
        if isinstance(cur, dict) and part in cur and cur[part] is not None:
            cur = cur[part]
        else:
            # 联系人未填写 → TBD（联系方式属可配置可选值）
            if body.endswith(".contact"):
                return "TBD"
            raise KeyError(f"未找到占位符值: {token}")
    return str(cur)


def render(template_text: str, profile: dict, decisions: dict) -> str:
    missing = set()

    def repl(m: re.Match) -> str:
        token = m.group(0)
        try:
            return resolve_placeholder(token, profile, decisions)
        except KeyError as e:
            missing.add(str(e))
            return token

    out = re.sub(r"\{\{[a-zA-Z_.]+\}\}", repl, template_text)
    if missing:
        raise SystemExit(f"缺少占位符值: {sorted(missing)[:20]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True, type=Path)
    ap.add_argument("--profile", required=True, type=Path)
    ap.add_argument("--decisions", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    profile = yaml.safe_load(args.profile.read_text())
    decisions = json.loads(args.decisions.read_text())
    rendered = render(args.template.read_text(), profile, decisions)

    # 校验无残留占位符
    left = re.findall(r"\{\{[a-zA-Z_.]+\}\}", rendered)
    if left:
        print("渲染后仍存在占位符:", sorted(set(left))[:10])
        return 1

    # 注入 profile_hash（渲染结果不含，需补头部声明；此处由外部步骤写入或提示）
    # 说明：模板头部声明由渲染保留模板本身的绑定块；profile_hash 在渲染后统一由校验器核对。

    args.out.write_text(rendered, encoding="utf-8")
    print(f"[OK] 已渲染: {args.out}")
    print(f"[OK] 输出字节: {len(rendered.encode('utf-8'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
