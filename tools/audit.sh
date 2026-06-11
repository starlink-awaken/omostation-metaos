#!/usr/bin/env bash
# audit.sh — B-2 P0 跨仓债审计 (R47 模板)
#
# 跑 metaos 仓跨仓债审计:
#   1. 检查 metaos.audit 模块入口
#   2. 检查 d_layer.append_trace_log 写 audit trail
#   3. 检查 task_manager._audit 写 audit trail
#   4. 输出 §17 R0 评分

set -euo pipefail

METAOS_DIR="${1:-$(git rev-parse --show-toplevel)}"
VENV_PYTHON="${METAOS_DIR}/.venv/bin/python"

echo "=== metaos 跨仓债审计 (B-2 P0) ==="
echo "METAOS_DIR: $METAOS_DIR"
echo

# 1. metaos.audit 模块入口
echo "1. metaos.audit AppendOnlyLog 入口"
"$VENV_PYTHON" -c "from metaos.audit import AppendOnlyLog, fcntl_lock, audit_log; print('  ✅ AppendOnlyLog + fcntl_lock + audit_log importable')"

# 2. d_layer 迁移
echo "2. d_layer.append_trace_log audit trail"
grep -q "from metaos.audit import audit_log" "$METAOS_DIR/src/metaos/layers/d_layer.py" \
    && echo "  ✅ d_layer.py 已注入 audit_log" \
    || echo "  ❌ d_layer.py 未迁移"

# 3. task_manager 迁移
echo "3. task_manager._audit 写 audit trail"
grep -q "audit_log" "$METAOS_DIR/src/metaos/a2a/task_manager.py" \
    && echo "  ✅ task_manager.py 已注入 audit_log" \
    || echo "  ❌ task_manager.py 未迁移"

# 4. §17 R0 评分
echo "4. §17 健康度评分"
"$VENV_PYTHON" - <<'PYEOF'
import os
import json
from pathlib import Path
from metaos.audit import audit_log

# 扫所有 d-layer-trace-*.jsonl + a2a-task-*.jsonl
total = 0
drift = 0
for jsonl in Path('.').rglob('d-layer-trace-*.jsonl'):
    if '.venv' in str(jsonl) or 'node_modules' in str(jsonl):
        continue
    for r in audit_log(jsonl.parent, "d-layer-trace").read_all():
        total += 1
        if not isinstance(r, dict) or 'ts' not in r:
            drift += 1
for jsonl in Path('.').rglob('a2a-task-*.jsonl'):
    if '.venv' in str(jsonl) or 'node_modules' in str(jsonl):
        continue
    for r in audit_log(jsonl.parent, "a2a-task").read_all():
        total += 1
        if not isinstance(r, dict) or 'ts' not in r:
            drift += 1

density = drift / total if total > 0 else 0.0
if density <= 0.01:
    grade = "R0"
elif density <= 0.05:
    grade = "R1"
elif density <= 0.10:
    grade = "R2"
elif density <= 0.30:
    grade = "R3"
elif density <= 0.50:
    grade = "R4"
else:
    grade = "R5"

print(json.dumps({
    "generated_at": "2026-06-11T00:00:00Z",
    "drift_count": drift,
    "total_records": total,
    "debt_density": round(density, 6),
    "health_grade": grade,
}, indent=2))
PYEOF

echo
echo "=== 审计完成 ==="
