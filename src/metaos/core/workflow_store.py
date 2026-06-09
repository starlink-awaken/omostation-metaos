"""WorkflowStore — Workflow 状态持久化与断点续跑

每次节点状态变化时写入 SQLite，支持：
- 保存工作流 + 节点状态到 DB
- 查询历史工作流
- 加载未完成的工作流恢复执行
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".metaos" / "workflow_history.db"


class WorkflowStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    task_description TEXT,
                    status TEXT DEFAULT 'running',
                    created_at TEXT,
                    updated_at TEXT,
                    dag_json TEXT
                );
                CREATE TABLE IF NOT EXISTS workflow_nodes (
                    workflow_id TEXT,
                    node_id TEXT,
                    task_type TEXT,
                    input_prompt TEXT,
                    depends_on TEXT,
                    status TEXT DEFAULT 'pending',
                    output TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (workflow_id, node_id)
                );
            """)

    def save_workflow(self, workflow_id: str, task_description: str, dag_dict: dict):
        """新建工作流记录"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO workflows
                (workflow_id, task_description, status, created_at, updated_at, dag_json)
                VALUES (?, ?, 'running', ?, ?, ?)
            """, (workflow_id, task_description, now, now, json.dumps(dag_dict, ensure_ascii=False)))

    def update_node(self, workflow_id: str, node_id: str, task_type: str,
                    input_prompt: str, depends_on: list, status: str, output: str = ""):
        """更新节点状态（checkpoint）"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO workflow_nodes
                (workflow_id, node_id, task_type, input_prompt, depends_on, status, output, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (workflow_id, node_id, task_type, input_prompt,
                  json.dumps(depends_on), status, output or "", now))

    def complete_workflow(self, workflow_id: str, status: str = "completed"):
        """标记工作流最终状态"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE workflows SET status=?, updated_at=? WHERE workflow_id=?",
                (status, now, workflow_id)
            )

    def list_workflows(self, limit: int = 20) -> list[dict]:
        """查询历史工作流列表"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT workflow_id, task_description, status, created_at, updated_at
                FROM workflows ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [
            {"id": r[0], "task": r[1], "status": r[2], "created": r[3], "updated": r[4]}
            for r in rows
        ]

    def get_workflow(self, workflow_id: str) -> dict | None:
        """获取单个工作流详情"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
            if not row:
                return None
            nodes = conn.execute(
                "SELECT * FROM workflow_nodes WHERE workflow_id=?", (workflow_id,)
            ).fetchall()

        return {
            "id": row[0], "task": row[1], "status": row[2],
            "created": row[3], "updated": row[4],
            "dag": json.loads(row[5]) if row[5] else {},
            "nodes": [
                {"id": n[1], "type": n[2], "status": n[5], "output": n[6]}
                for n in nodes
            ]
        }
