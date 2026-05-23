#!/usr/bin/env python3
"""
ai-superpower API 场景测试集
使用场景：prj-proposals-manager 系统中项目/提案的增改查验证
前置条件：ai-superpower server 运行在 localhost:8000
"""
import os
import sys
import json
import requests

BASE = os.environ.get("AI_SUPERPOWER_BASE", "http://localhost:8000")
KEY = os.environ.get("API_KEY", "dfd37469666776457eb593e3ded692a5")
H = {"X-API-Key": KEY, "Content-Type": "application/json"}


def api(method: str, path: str, data=None) -> dict:
    url = f"{BASE}{path}"
    r = requests.request(method, url, json=data, headers=H)
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text, "_status": r.status_code}


def ok(msg: str):
    print(f"  PASS: {msg}")


def get_id(resp: dict) -> str:
    if isinstance(resp, dict) and "id" in resp:
        return resp["id"]
    return ""


def main():
    print("=== ai-superpower API 场景测试集 ===")
    print(f"BASE: {BASE}")
    print()

    # ─── 场景1：项目管理增改查 ───────────────────────────────────────────────
    print("【场景1】项目管理 — 创建 → 列表 → 更新 → 详情 → 删除")
    print()

    # 1a. 创建项目
    print("  1a. 创建项目 test-project")
    resp = api("POST", "/api/projects", {
        "name": "test-project",
        "git_repo": "https://github.com/test/project",
        "prj_url": "https://test-project.pages.dev",
        "local_path": "/home/test/project",
        "description": "Test project for scenario validation"
    })
    prj_id = get_id(resp)
    print(f"    响应: {resp}")
    print(f"    项目ID: {prj_id}")
    ok("创建项目")

    # 1b. 列表查询（默认 last_update desc）
    print()
    print("  1b. 列表查询（sort_by=last_update, sort_order=desc）")
    resp = api("GET", "/api/projects?page=1&page_size=5&sort_by=last_update&sort_order=desc")
    print(f"    total={resp.get('total', '?')}, items={len(resp.get('items', []))}")
    ok("列表查询")

    # 1c. 按 create_at asc 排序
    print()
    print("  1c. 列表查询（sort_by=create_at, sort_order=asc）")
    resp = api("GET", "/api/projects?page=1&page_size=5&sort_by=create_at&sort_order=asc")
    print(f"    total={resp.get('total', '?')}")
    ok("按创建时间升序")

    # 1d. 按名称搜索
    print()
    print("  1d. 按名称搜索 test")
    resp = api("GET", "/api/projects?search=test&page=1&page_size=5")
    print(f"    total={resp.get('total', '?')}")
    ok("搜索过滤")

    # 1e. 更新项目
    print()
    print("  1e. 更新项目名称和 prj_url")
    resp = api("PUT", f"/api/projects/{prj_id}", {
        "name": "test-project-updated",
        "prj_url": "https://new-url.pages.dev"
    })
    print(f"    name={resp.get('name')}, prj_url={resp.get('prj_url')}")
    ok("更新项目")

    # 1f. 详情查询
    print()
    print("  1f. 详情查询")
    resp = api("GET", f"/api/projects/{prj_id}")
    print(f"    ID={resp.get('id')} name={resp.get('name')} prj_url={resp.get('prj_url')}")
    ok("详情查询")

    # 1g. 分页
    print()
    print("  1g. 分页查询第2页（每页3条）")
    resp = api("GET", "/api/projects?page=2&page_size=3")
    print(f"    page={resp.get('page')} total={resp.get('total')} items={len(resp.get('items', []))}")
    ok("分页")

    # ─── 场景2：提案管理增改查 ───────────────────────────────────────────────
    print()
    print("【场景2】提案管理 — 创建 → 列表 → 更新字段 → 详情 → 删除")
    print()

    # 2a. 创建提案
    print("  2a. 创建提案")
    resp = api("POST", "/api/proposals", {
        "title": "Test Proposal for Scenarios",
        "owner": "tester",
        "project_id": "PRJ-20260523-001",
        "stage": "ideation",
        "engine": "web",
        "target": "browser",
        "notes": "Scenario test notes"
    })
    prop_id = get_id(resp)
    print(f"    响应: {resp}")
    print(f"    提案ID: {prop_id}")
    ok("创建提案")

    # 2b. 列表查询
    print()
    print("  2b. 列表查询（sort_by=last_update, sort_order=desc）")
    resp = api("GET", "/api/proposals?page=1&page_size=5&sort_by=last_update&sort_order=desc")
    print(f"    total={resp.get('total', '?')}")
    ok("提案列表")

    # 2c. 按 status 过滤
    print()
    print("  2c. 按 status=active 过滤")
    resp = api("GET", "/api/proposals?status=active&page=1&page_size=5")
    print(f"    total={resp.get('total', '?')}")
    ok("状态过滤")

    # 2d. 按 stage 过滤
    print()
    print("  2d. 按 stage=ideation 过滤")
    resp = api("GET", "/api/proposals?stage=ideation&page=1&page_size=5")
    print(f"    total={resp.get('total', '?')}")
    ok("阶段过滤")

    # 2e. 按 project_id 过滤
    print()
    print("  2e. 按 project_id 过滤")
    resp = api("GET", "/api/proposals?project_id=PRJ-20260523-001&page=1&page_size=5")
    print(f"    total={resp.get('total', '?')}")
    ok("项目过滤")

    # 2f. 组合过滤 + 排序
    print()
    print("  2f. 组合过滤（status=active）+ 排序（sort_by=last_update, sort_order=asc）")
    resp = api("GET", "/api/proposals?status=active&sort_by=last_update&sort_order=asc&page=1&page_size=5")
    print(f"    total={resp.get('total', '?')}")
    ok("组合过滤")

    # 2g. 更新提案字段
    print()
    print("  2g. 更新提案标题和 engine")
    resp = api("PUT", f"/api/proposals/{prop_id}/fields", {
        "title": "Updated Proposal Title",
        "engine": "unity"
    })
    print(f"    title={resp.get('title')} engine={resp.get('engine')}")
    ok("更新提案字段")

    # 2h. 详情查询
    print()
    print("  2h. 详情查询")
    resp = api("GET", f"/api/proposals/{prop_id}")
    print(f"    ID={resp.get('id')} title={resp.get('title')} engine={resp.get('engine')}")
    ok("提案详情")

    # 2i. 更新提案状态
    print()
    print("  2i. 更新提案状态为 clarifying")
    resp = api("PUT", f"/api/proposals/{prop_id}/status", {"status": "clarifying"})
    print(f"    status={resp.get('status')}")
    ok("状态更新")

    # 2j. 搜索
    print()
    print("  2j. 搜索包含 curl 的提案")
    resp = api("GET", "/api/proposals?search=Scenario&page=1&page_size=5")
    print(f"    total={resp.get('total', '?')}")
    ok("提案搜索")

    # ─── 场景3：提案状态流转 ───────────────────────────────────────────────
    print()
    print("【场景3】提案状态流转测试")
    print()

    # 3a. 创建提案
    print("  3a. 创建提案用于状态流转")
    resp = api("POST", "/api/proposals", {
        "title": "Status Flow Test",
        "owner": "tester",
        "project_id": "PRJ-20260523-001",
        "stage": "prototype"
    })
    prop_id2 = get_id(resp)
    print(f"    提案ID: {prop_id2}")

    # 3b. intake → clarifying
    print()
    print("  3b. intake → clarifying")
    resp = api("PUT", f"/api/proposals/{prop_id2}/status", {"status": "clarifying"})
    print(f"    status={resp.get('status')}")
    ok("状态流转 intake→clarifying")

    # 3c. clarifying → prd_pending_confirmation
    print()
    print("  3c. clarifying → prd_pending_confirmation")
    resp = api("PUT", f"/api/proposals/{prop_id2}/status", {"status": "prd_pending_confirmation"})
    print(f"    status={resp.get('status')}")
    ok("状态流转 →prd_pending_confirmation")

    # 3d. prd_pending_confirmation → approved_for_dev
    print()
    print("  3d. prd_pending_confirmation → approved_for_dev")
    resp = api("PUT", f"/api/proposals/{prop_id2}/status", {"status": "approved_for_dev"})
    print(f"    status={resp.get('status')}")
    ok("状态流转 →approved_for_dev")

    # 3e. approved_for_dev → in_dev
    print()
    print("  3e. approved_for_dev → in_dev")
    resp = api("PUT", f"/api/proposals/{prop_id2}/status", {"status": "in_dev"})
    print(f"    status={resp.get('status')}")
    ok("状态流转 →in_dev")

    # 3f. in_dev → accepted
    print()
    print("  3f. in_dev → accepted")
    resp = api("PUT", f"/api/proposals/{prop_id2}/status", {"status": "accepted"})
    print(f"    status={resp.get('status')}")
    ok("状态流转 →accepted")

    # ─── 场景4：审计日志 ───────────────────────────────────────────────
    print()
    print("【场景4】审计日志查询")
    print()

    print("  4a. 查询最近审计记录")
    resp = api("GET", "/api/audit?page=1&page_size=10")
    print(f"    total={resp.get('total', '?')}, items={len(resp.get('items', []))}")
    ok("审计日志查询")

    # ─── 场景5：健康检查 ───────────────────────────────────────────────
    print()
    print("【场景5】健康检查")
    print()

    print("  5a. GET /health")
    resp = api("GET", "/health")
    print(f"    {resp}")
    ok("健康检查")

    # ─── 清理 ───────────────────────────────────────────────────────────
    print()
    print("【清理】删除测试数据")
    if prj_id:
        api("DELETE", f"/api/projects/{prj_id}")
        print(f"  已删除项目 {prj_id}")
    if prop_id:
        api("DELETE", f"/api/proposals/{prop_id}")
        print(f"  已删除提案 {prop_id}")
    if prop_id2:
        api("DELETE", f"/api/proposals/{prop_id2}")
        print(f"  已删除提案 {prop_id2}")

    print()
    print("=== 全部测试完成 ===")


if __name__ == "__main__":
    main()
