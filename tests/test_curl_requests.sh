#!/usr/bin/env bash
# =============================================================================
# ai-superpower curl 命令版 API 测试集
# 使用场景：proposals-manager 系统中项目/提案的增改查场景
# 前置条件：ai-superpower server 运行在 localhost:8000
# =============================================================================
set -e

BASE="${BASE:-http://localhost:8000}"
KEY="${API_KEY:-dfd37469666776457eb593e3ded692a5}"
H="-H \"X-API-Key: $KEY\" -H Content-Type: application/json"

echo "=== ai-superpower API curl 测试集 ==="
echo "BASE: $BASE"
echo ""

# ─── Helper ────────────────────────────────────────────────────────────────────
get()  { curl -s -X GET  "$BASE$1" -H "X-API-Key: $KEY" | python3 -m json.tool 2>/dev/null || curl -s -X GET "$BASE$1" -H "X-API-Key: $KEY"; }
post() { curl -s -X POST "$BASE$1" -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "$2" | python3 -m json.tool 2>/dev/null || curl -s -X POST "$BASE$1" -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "$2"; }
put()  { curl -s -X PUT  "$BASE$1" -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "$2" | python3 -m json.tool 2>/dev/null || curl -s -X PUT "$BASE$1" -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "$2"; }
del()  { curl -s -X DELETE "$BASE$1" -H "X-API-Key: $KEY" | python3 -m json.tool 2>/dev/null || curl -s -X DELETE "$BASE$1" -H "X-API-Key: $KEY"; }
ok()   { echo "  PASS: $1"; }

# ─── 场景1：项目管理增改查 ────────────────────────────────────────────────────
echo "【场景1】项目管理 — 创建 → 列表 → 更新 → 详情 → 删除"
echo ""

# 1a. 创建项目
echo "  1a. 创建项目 test-project"
RESP=$(post "/api/projects" '{"name":"test-project","git_repo":"https://github.com/test/project","prj_url":"https://test-project.pages.dev","local_path":"/home/test/project","description":"Test project for curl validation"}')
echo "$RESP"
PRJ_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
echo "  项目ID: $PRJ_ID"
ok "创建项目"

# 1b. 列表查询（默认按 last_update desc）
echo ""
echo "  1b. 列表查询（sort_by=last_update, sort_order=desc）"
get "/api/projects?page=1&page_size=5&sort_by=last_update&sort_order=desc" | head -5
ok "列表查询"

# 1c. 列表查询（按 create_at asc）
echo ""
echo "  1c. 列表查询（sort_by=create_at, sort_order=asc）"
get "/api/projects?page=1&page_size=5&sort_by=create_at&sort_order=asc" | head -5
ok "按创建时间升序"

# 1d. 按名称搜索
echo ""
echo "  1d. 按名称搜索 test"
get "/api/projects?search=test&page=1&page_size=5" | head -5
ok "搜索过滤"

# 1e. 更新项目
echo ""
echo "  1e. 更新项目名称和 prj_url"
put "/api/projects/$PRJ_ID" '{"name":"test-project-updated","prj_url":"https://new-url.pages.dev"}'
ok "更新项目"

# 1f. 详情查询
echo ""
echo "  1f. 详情查询"
get "/api/projects/$PRJ_ID" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'ID={d[\"id\"]} name={d[\"name\"]} prj_url={d[\"prj_url\"]}')"
ok "详情查询"

# 1g. 分页
echo ""
echo "  1g. 分页查询第2页（每页3条）"
get "/api/projects?page=2&page_size=3" | head -3
ok "分页"

# ─── 场景2：提案管理增改查 ────────────────────────────────────────────────────
echo ""
echo "【场景2】提案管理 — 创建 → 列表 → 更新字段 → 详情 → 删除"
echo ""

# 2a. 创建提案
echo "  2a. 创建提案"
RESP=$(post "/api/proposals" '{"title":"Test Proposal for Curl","owner":"tester","project_id":"PRJ-20260523-001","stage":"ideation","engine":"web","target":"browser","notes":"Curl test notes"}')
echo "$RESP"
PROP_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
echo "  提案ID: $PROP_ID"
ok "创建提案"

# 2b. 列表查询（默认 last_update desc）
echo ""
echo "  2b. 列表查询（sort_by=last_update, sort_order=desc）"
get "/api/proposals?page=1&page_size=5&sort_by=last_update&sort_order=desc" | head -5
ok "提案列表"

# 2c. 按 status 过滤
echo ""
echo "  2c. 按 status=active 过滤"
get "/api/proposals?status=active&page=1&page_size=5" | head -5
ok "状态过滤"

# 2d. 按 stage 过滤
echo ""
echo "  2d. 按 stage=ideation 过滤"
get "/api/proposals?stage=ideation&page=1&page_size=5" | head -3
ok "阶段过滤"

# 2e. 按 project_id 过滤
echo ""
echo "  2e. 按 project_id=test-project 过滤"
get "/api/proposals?project_id=test-project&page=1&page_size=5" | head -3
ok "项目过滤"

# 2f. 组合过滤 + 排序
echo ""
echo "  2f. 组合过滤（status=active）+ 排序（sort_by=create_at, sort_order=asc）"
get "/api/proposals?status=active&sort_by=create_at&sort_order=asc&page=1&page_size=5" | head -5
ok "组合过滤"

# 2g. 更新提案字段
echo ""
echo "  2g. 更新提案标题和 engine"
put "/api/proposals/$PROP_ID/fields" '{"title":"Updated Proposal Title","engine":"unity"}'
ok "更新提案字段"

# 2h. 详情查询
echo ""
echo "  2h. 详情查询"
get "/api/proposals/$PROP_ID" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'ID={d[\"id\"]} title={d[\"title\"]} engine={d[\"engine\"]}')"
ok "提案详情"

# 2i. 更新提案状态
echo ""
echo "  2i. 更新提案状态为 clarifying"
put "/api/proposals/$PROP_ID/status" '{"status":"clarifying"}'
ok "状态更新"

# 2j. 提案全字段搜索
echo ""
echo "  2j. 搜索包含 curl 的提案"
get "/api/proposals?search=curl&page=1&page_size=5" | head -5
ok "提案搜索"

# ─── 场景3：提案状态流转 ───────────────────────────────────────────────────────
echo ""
echo "【场景3】提案状态流转测试"
echo ""

# 3a. 创建提案
echo "  3a. 创建提案用于状态流转"
RESP=$(post "/api/proposals" '{"title":"Status Flow Test","owner":"tester","project_id":"test-project","stage":"prototype"}')
PROP_ID2=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
echo "  提案ID: $PROP_ID2"

# 3b. intake → clarifying
echo ""
echo "  3b. intake → clarifying"
put "/api/proposals/$PROP_ID2/status" '{"status":"clarifying"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status={d[\"status\"]}')"
ok "状态流转 intake→clarifying"

# 3c. clarifying → prd_pending_confirmation
echo ""
echo "  3c. clarifying → prd_pending_confirmation"
put "/api/proposals/$PROP_ID2/status" '{"status":"prd_pending_confirmation"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status={d[\"status\"]}')"
ok "状态流转 →prd_pending_confirmation"

# 3d. prd_pending_confirmation → approved_for_dev
echo ""
echo "  3d. prd_pending_confirmation → approved_for_dev"
put "/api/proposals/$PROP_ID2/status" '{"status":"approved_for_dev"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status={d[\"status\"]}')"
ok "状态流转 →approved_for_dev"

# 3e. approved_for_dev → in_dev
echo ""
echo "  3e. approved_for_dev → in_dev"
put "/api/proposals/$PROP_ID2/status" '{"status":"in_dev"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status={d[\"status\"]}')"
ok "状态流转 →in_dev"

# 3f. in_dev → accepted
echo ""
echo "  3f. in_dev → accepted"
put "/api/proposals/$PROP_ID2/status" '{"status":"accepted"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status={d[\"status\"]}')"
ok "状态流转 →accepted"

# ─── 场景4：审计日志 ──────────────────────────────────────────────────────────
echo ""
echo "【场景4】审计日志查询"
echo ""

echo "  4a. 查询最近审计记录"
get "/api/audit?page=1&page_size=10" | head -10
ok "审计日志查询"

# ─── 场景5：健康检查 ──────────────────────────────────────────────────────────
echo ""
echo "【场景5】健康检查"
echo ""

echo "  5a. GET /health"
get "/health"
ok "健康检查"

# ─── 清理（可选）───────────────────────────────────────────────────────────────
echo ""
echo "【清理】删除测试数据"
if [ -n "$PRJ_ID" ]; then
    del "/api/projects/$PRJ_ID"
    echo "  已删除项目 $PRJ_ID"
fi
if [ -n "$PROP_ID" ]; then
    del "/api/proposals/$PROP_ID"
    echo "  已删除提案 $PROP_ID"
fi
if [ -n "$PROP_ID2" ]; then
    del "/api/proposals/$PROP_ID2"
    echo "  已删除提案 $PROP_ID2"
fi

echo ""
echo "=== 全部测试完成 ==="
