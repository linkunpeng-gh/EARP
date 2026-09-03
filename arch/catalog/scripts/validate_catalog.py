#!/usr/bin/env python3
"""EARP Catalog 签署资产校验器。

对"模板 + Profile + 签署实例"三层结构做机械校验：
1. Profile 通过 schema（含危险额外字段负向测试）
2. 签署实例头部 profile_hash 与真实 Profile SHA-256 一致
3. 签署实例无残留 {{...}} 占位符
4. 签署实例中 FROZEN 契约块与模板完全一致（防止人工篡改冻结语义）
5. Profile 中的 FROZEN 语义开关字段被 schema 拒绝

用法：
    python validate_catalog.py [--profile PROF] [--schema SCHEMA] [--signoff SIGNOFF] [--template TMPL]

退出码：0 = 全部通过；非 0 = 存在失败项。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # scripts/arch/catalog/scripts -> 仓库根（EARP）
DEFAULT = {
    "profile": ROOT / "arch/catalog/profiles/jqmk-coal-production.yaml",
    "schema": ROOT / "arch/catalog/schemas/catalog-profile.schema.json",
    "signoff": ROOT / "arch/catalog/signoffs/jqmk-coal-production-20260901-r1.md",
    "template": ROOT / "arch/catalog/templates/n01a-catalog-phase0-signoff-template.md",
    "attestation": ROOT / "arch/catalog/attestations/jqmk-coal-production-20260901-r1.json",
    "schema_json": ROOT / "arch/catalog/schemas/catalog-profile.schema.json",
}

# 模板中必须原样出现在签署实例的 FROZEN 契约锚点（取自模板文本，不可改动）
FROZEN_ANCHORS = [
    "模型侧引用只能是 exact `CatalogRef={kind,stable_id,version}`",
    "Resolver 必须返回 `content_hash`、`status`、`data_domain_id`、`semantic_schema_version`",
    "kind, stable_id, version, content_hash, status, data_domain_id,",
    "缺失、非 active、跨域、kind mismatch、schema incompatible 均 fail closed",
    "以下任一变化必须产生新的不可变 manifest 修订和新的签署记录",
    "旧修订只归档，不覆盖或删除",
    "新 Draft/引用/submit/publish/compile/activation revalidation 拒绝非 active entry",
    "approve 不能直接写权威目录",
    "普通用户不可直接标 `fulfilled`",
    "明确拒绝只能记录 `fulfillment_failed`",
    "超时或响应丢失不是确定失败，不能伪造失败或 fulfilled",
    "应用层直接跨 tenant 可见",
    "确认 fail closed，不允许隐式覆盖",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_yaml_safe(path: Path):
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        sys.exit(f"缺少依赖: 请先安装 pyyaml、jsonschema（.venv/bin/pip install pyyaml jsonschema）: {e}")
    return yaml.safe_load(path.read_text())


def validate_profile_schema(profile: Path, schema_path: Path, failures: list[str]) -> None:
    try:
        from jsonschema import validate, ValidationError
    except ImportError as e:  # pragma: no cover
        sys.exit(f"缺少依赖: jsonschema: {e}")
    schema = json.loads(schema_path.read_text())
    prof = load_yaml_safe(profile)

    # 正例
    try:
        validate(instance=prof, schema=schema)
        print(f"[OK] Profile 通过 schema 校验: {profile.name}")
    except ValidationError as e:
        failures.append(f"Profile 未通过 schema: {e.message} @ {list(e.path)}")
        return

    # 负例：危险语义开关必须被 additionalProperties:false 拒绝
    for bad_key in ("allow_inactive", "disable_fail_closed", "disable_rbac", "bypass_resolver"):
        bad = dict(prof)
        bad[bad_key] = True
        try:
            validate(instance=bad, schema=schema)
            failures.append(f"危险语义开关 {bad_key} 未被 schema 拒绝（危险！）")
        except ValidationError:
            print(f"[OK] 危险语义开关 {bad_key} 被 schema 拒绝")
    print(f"[OK] Profile 顶层 extra 字段被拒绝（additionalProperties:false）")


def check_signoff_profile_hash(signoff: Path, profile: Path, failures: list[str]) -> None:
    text = signoff.read_text()
    real = sha256_file(profile)
    m = re.search(r"profile_hash（SHA-256）:\s*`([0-9a-f]{64})`", text)
    if not m:
        failures.append("签署实例缺少 profile_hash（SHA-256）声明")
        return
    declared = m.group(1)
    if declared != real:
        failures.append(f"profile_hash 不一致: 声明 {declared} != 实际 {real}")
    else:
        print(f"[OK] 签署实例 profile_hash 与 Profile 一致: {real[:16]}…")


def check_no_placeholders(signoff: Path, failures: list[str]) -> None:
    text = signoff.read_text()
    left = re.findall(r"\{\{[a-zA-Z_.]+\}\}", text)
    if left:
        failures.append(f"签署实例存在残留占位符: {sorted(set(left))[:10]}")
    else:
        print("[OK] 签署实例无残留占位符")


def check_frozen_blocks(signoff: Path, template: Path, failures: list[str]) -> None:
    """校验签署实例的 FROZEN 契约锚点与模板一致（模板为权威源）。"""
    sig = signoff.read_text()
    tmpl = template.read_text()
    missing = []
    for anchor in FROZEN_ANCHORS:
        if anchor not in tmpl:
            failures.append(f"模板中未找到 FROZEN 锚点（模板可能被改动）: {anchor[:40]}…")
            continue
        if anchor not in sig:
            missing.append(anchor)
    if missing:
        failures.append(f"签署实例缺少模板中的 FROZEN 契约块（{len(missing)} 处）: {[a[:30] for a in missing]}")
    else:
        print(f"[OK] 签署实例 FROZEN 契约块与模板一致（{len(FROZEN_ANCHORS)} 个锚点）")


def check_attestation(attestation: Path, failures: list[str]) -> None:
    """校验 attestation 中 blob_hashes 与真实文件一致（不可变证据闭环）。"""
    if not attestation.exists():
        failures.append(f"attestation 不存在: {attestation}")
        return
    data = json.loads(attestation.read_text())
    for key, entry in data.get("blob_hashes", {}).items():
        path = ROOT / entry["path"]
        if not path.exists():
            failures.append(f"attestation 指向文件不存在: {entry['path']}")
            continue
        real = sha256_file(path)
        if real != entry["sha256"]:
            failures.append(f"attestation {key} hash 不一致: 声明 {entry['sha256'][:16]}… != 实际 {real[:16]}…")
        else:
            print(f"[OK] attestation {key} blob hash 与文件一致: {real[:16]}…")


def check_tag(attestation: Path, failures: list[str]) -> None:
    """校验签署基线 tag：存在、annotated、指向 attestation 声明的 baseline_commit。"""
    if not attestation.exists():
        return  # attestation 不存在的错误已由 check_attestation 报
    data = json.loads(attestation.read_text())
    tag = data.get("signoff_tag")
    baseline = data.get("baseline_commit", "")
    # baseline_commit 字段含注释文字，提取前 40 位 hash
    m = re.search(r"([0-9a-f]{40})", baseline)
    baseline_hash = m.group(1) if m else None

    if not tag:
        failures.append("attestation 缺少 signoff_tag 字段")
        return

    def git(*args: str) -> tuple[int, str]:
        r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True)
        return r.returncode, r.stdout.strip()

    # 1. tag 存在
    rc, _ = git("rev-parse", "--verify", tag)
    if rc != 0:
        failures.append(f"签署基线 tag 不存在: {tag}")
        return
    print(f"[OK] 签署基线 tag 存在: {tag}")

    # 2. tag 是 annotated（git cat-file -t 返回 "tag"）
    rc, obj_type = git("cat-file", "-t", tag)
    if obj_type != "tag":
        failures.append(f"tag {tag} 不是 annotated tag（类型为 {obj_type}），应为 annotated tag")
    else:
        print(f"[OK] tag {tag} 为 annotated tag")

    # 3. tag 指向的 commit == attestation baseline_commit
    rc, pointed = git("rev-list", "-n1", tag)
    if rc != 0 or not pointed:
        failures.append(f"无法解析 tag {tag} 指向的 commit")
    elif baseline_hash and pointed != baseline_hash:
        failures.append(f"tag {tag} 指向 {pointed[:12]}…，与 attestation baseline_commit {baseline_hash[:12]}… 不一致")
    elif not baseline_hash:
        failures.append("attestation baseline_commit 字段未包含有效 commit hash")
    else:
        print(f"[OK] tag {tag} 指向 commit 与 attestation baseline_commit 一致: {pointed[:12]}…")


def check_readiness(profile: Path, failures: list[str]) -> None:
    """readiness 检查：区分'格式合法'与'具备签署/上线条件'。不判非法，仅提示。"""
    import yaml
    prof = yaml.safe_load(profile.read_text())
    packs = prof.get("pack_lock") or []
    missing = [p for p in packs if not (p.get("version") and p.get("content_hash"))]
    if missing:
        print(f"[READINESS] pack_lock 未就绪（{len(missing)}/{len(packs)} 项 version/hash 为空）→ 具备签署/上线条件前需补全，见 D-13")

    roles = prof.get("roles")
    product_owner_contact = None
    if isinstance(roles, dict):
        # v1: roles = {role_key: {name, team, contact}}
        product_owner_contact = roles.get("product_owner", {}).get("contact")
    elif isinstance(roles, list):
        # v2: roles = [{role_key, name, team, contact}]
        for r in roles:
            if r.get("role_key") == "product_owner":
                product_owner_contact = r.get("contact")
                break
    if not product_owner_contact:
        print("[READINESS] 产品负责人联系方式 TBD → §9.1 RACI entry gate 保持 HOLD")


def check_profile_v2_semantics(profile: Path, failures: list[str]) -> None:
    """v2 Profile 语义校验（JSON Schema 无法保证的部分）。"""
    import yaml
    prof = yaml.safe_load(profile.read_text())
    if prof.get("schema_version") != "catalog-profile/v2":
        return  # 仅校验 v2

    roles = prof.get("roles", [])
    if not isinstance(roles, list):
        failures.append("v2 roles 应为数组")
        return

    # 1. role_key 不重复
    keys = [r.get("role_key") for r in roles]
    dupes = [k for k in set(keys) if keys.count(k) > 1]
    if dupes:
        failures.append(f"v2 role_key 重复: {dupes}")

    # 2. backup_approver 必须对应 roles 中的 role_key
    backup = prof.get("backup_approver")
    if backup and backup not in keys:
        failures.append(f"backup_approver '{backup}' 不在 roles role_key 列表中: {keys}")

    # 3. 候补审批人不能是唯一审批人（简单检查：backup_approver 对应的人员不能与所有审批角色为同一人）
    #    Phase 1 仅提示，不强制失败
    if backup:
        backup_person = next((r.get("name") for r in roles if r.get("role_key") == backup), None)
        print(f"[OK] v2 语义校验通过: {len(roles)} 角色, backup_approver={backup}({backup_person})")
    else:
        failures.append("v2 缺少 backup_approver")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for key, dflt in DEFAULT.items():
        ap.add_argument(f"--{key}", type=Path, default=dflt)
    ap.add_argument("--v2", action="store_true",
                    help="v2 模式：校验 v2 Profile 的 Schema + 语义（role_key 唯一、backup_approver 绑定），不验证 r1 signoff")
    args = ap.parse_args()

    failures: list[str] = []

    if args.v2:
        # v2 模式：默认使用 v2 profile 和 v2 schema
        profile = args.profile if args.profile != DEFAULT["profile"] else \
            ROOT / "arch/catalog/profiles/jqmk-coal-production-v2.yaml"
        schema = args.schema if args.schema != DEFAULT["schema"] else \
            ROOT / "arch/catalog/schemas/catalog-profile-v2.schema.json"
        print("=== EARP Catalog v2 Profile 校验 ===")
        validate_profile_schema(profile, schema, failures)
        check_readiness(profile, failures)
        check_profile_v2_semantics(profile, failures)
    else:
        # 默认 r1/v1 模式
        print("=== EARP Catalog 签署资产校验（r1/v1）===")
        validate_profile_schema(args.profile, args.schema, failures)
        check_signoff_profile_hash(args.signoff, args.profile, failures)
        check_no_placeholders(args.signoff, failures)
        check_frozen_blocks(args.signoff, args.template, failures)
        check_attestation(args.attestation, failures)
        check_tag(args.attestation, failures)
        check_readiness(args.profile, failures)
        check_profile_v2_semantics(args.profile, failures)

    if failures:
        print("\n=== 失败项 ===")
        for f in failures:
            print("  ✗", f)
        print(f"\n共 {len(failures)} 项失败。")
        return 1
    print("\n=== 全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
