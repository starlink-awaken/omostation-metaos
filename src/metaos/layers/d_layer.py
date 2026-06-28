"""D 层存储——数字资产引擎"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from metaos.core.types import Decision, DigitalAsset, Principle  # type: ignore[import-not-found]


class DLayer:
    """数字资产存储层——文件 + SQLite"""

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = str(Path.home() / ".metaos" / "data")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # SQLite 存结构化数据——使用可写路径
        self.db_path = self.data_dir / "metaos.db"
        self._init_db()

        # 文件存储
        self.assets_dir = self.data_dir / "assets"
        self.assets_dir.mkdir(exist_ok=True)

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                h_id TEXT, level TEXT, action TEXT,
                description TEXT, assets_used TEXT,
                immune_triggered TEXT, timestamp TEXT,
                outcome_pending_review INTEGER,
                review_deadline TEXT,
                access_level TEXT DEFAULT 'owner',
                api_version TEXT DEFAULT '1.0'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS principles_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                principle_id TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                content TEXT,
                source_h_id TEXT,
                source_experience TEXT,
                applicability_tags TEXT,
                verification_count INTEGER DEFAULT 0,
                conflict_principles TEXT,
                status TEXT DEFAULT 'active',
                superseded_by INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(principle_id, version)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_principles_id
            ON principles_v2(principle_id, status)
        """)
        # H Sessions 持久化表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS h_sessions (
                token TEXT PRIMARY KEY,
                h_id TEXT NOT NULL,
                name TEXT DEFAULT '',
                created_at TEXT,
                expires_at TEXT,
                last_used TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS asset_trace (
                asset_id TEXT PRIMARY KEY,
                level TEXT, source_h_id TEXT,
                content_summary TEXT,
                auth_timestamp TEXT,
                verification_count INTEGER DEFAULT 0,
                challenge_count INTEGER DEFAULT 0,
                verification_h_ids TEXT,
                rollback_snapshot_uri TEXT,
                status TEXT DEFAULT 'active'
            )
        """)
        # 资产溯源链表——禁止 DELETE
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trace_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT, event TEXT, detail TEXT,
                timestamp TEXT,
                UNIQUE(id)
            )
        """)
        conn.commit()
        conn.close()

    def save_decision(self, d: Decision):
        """保存决策——TD-04 修复：SQLite 事务包裹"""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR REPLACE INTO decisions
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    d.decision_id,
                    d.h_id,
                    d.level,
                    d.action,
                    d.description,
                    json.dumps(d.assets_used),
                    d.immune_triggered,
                    d.timestamp.isoformat(),
                    1 if d.outcome_pending_review else 0,
                    d.review_deadline.isoformat() if d.review_deadline else None,
                    d.access_level,
                    d.api_version,
                ),
            )
            conn.commit()
        except Exception:  # defensive fallback  # noqa: BLE001
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── V-002 修复：带调用者权限的数据查询 ──

    def get_decisions(self, h_id: str = "", limit: int = 20, caller_h_id: str = "") -> list[Decision]:
        """
        获取决策日志。
        V4#3 修复：使用 access_level 字段而非关键词过滤进行访问控制。
        """
        conn = sqlite3.connect(str(self.db_path))
        if caller_h_id and h_id and caller_h_id != h_id:
            # caller 尝试读取别人的决策 → 只返回 access_level='public' 的记录
            rows = conn.execute(
                "SELECT * FROM decisions WHERE access_level='public' ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        elif h_id:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE h_id=? ORDER BY timestamp DESC LIMIT ?", (h_id, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [self._row_to_decision(r) for r in rows]

    def _row_to_decision(self, r) -> Decision:
        d = Decision(
            decision_id=r[0],
            h_id=r[1],
            level=r[2],
            action=r[3],
            description=r[4],
            assets_used=json.loads(r[5]) if r[5] else [],
            immune_triggered=r[6],
            timestamp=datetime.fromisoformat(r[7]) if r[7] else datetime.now(),
            outcome_pending_review=bool(r[8]),
        )
        if r[9]:
            d.review_deadline = datetime.fromisoformat(r[9])
        if len(r) >= 11:  # 兼容旧 DB 格式
            d.access_level = r[10] or "owner"
        if len(r) >= 12:
            d.api_version = r[11] or "1.0"
        return d

    def save_asset(self, a: DigitalAsset) -> str:
        """保存数字资产——文件存储 + 溯源记录"""
        import uuid

        if not a.asset_id:
            a.asset_id = uuid.uuid4().hex[:12]
        # 写入文件
        asset_path = self.assets_dir / f"{a.asset_id}.json"
        asset_data = {
            "asset_id": a.asset_id,
            "level": a.level.value if hasattr(a.level, "value") else a.level,
            "content": a.content,
            "summary": a.summary,
            "source_h_id": a.source_h_id,
            "asset_type": a.asset_type,
            "tags": a.tags,
            "timestamp": datetime.now().isoformat(),
        }
        with open(asset_path, "w", encoding="utf-8") as f:
            json.dump(asset_data, f, ensure_ascii=False, indent=2)
        # 溯源记录
        self.append_trace_log(a.asset_id, "created", f"source={a.source_h_id} type={a.asset_type}")
        return a.asset_id

    def save_principle(self, p: Principle):
        """保存原则——版本化：每次修改写新版本，不覆盖旧版本。TD-04 修复：事务包裹"""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 检查是否存在活跃版本
            existing = conn.execute(
                "SELECT MAX(version) FROM principles_v2 WHERE principle_id=? AND status='active'", (p.principle_id,)
            ).fetchone()

            if existing and existing[0]:
                new_version = existing[0] + 1
                conn.execute(
                    "UPDATE principles_v2 SET status='superseded', superseded_by=? "
                    "WHERE principle_id=? AND status='active'",
                    (new_version, p.principle_id),
                )
            else:
                new_version = 1

            conn.execute(
                """
                INSERT INTO principles_v2
                (principle_id, version, content, source_h_id, source_experience,
                 applicability_tags, verification_count, conflict_principles, status)
                VALUES (?,?,?,?,?,?,?,?,?)
            """,
                (
                    p.principle_id,
                    new_version,
                    p.content,
                    p.source_h_id,
                    p.source_experience,
                    json.dumps(p.applicability_tags),
                    p.verification_count,
                    json.dumps(p.conflict_principles),
                    p.status,
                ),
            )
            conn.commit()
        except Exception:  # defensive fallback  # noqa: BLE001
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_principles(self, status: str = "active") -> list[Principle]:
        """返回原则——默认只返回最新活跃版本"""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT * FROM principles_v2 WHERE status=? ORDER BY verification_count DESC", (status,)
        ).fetchall()
        conn.close()
        return [self._row_to_principle(r) for r in rows]

    def get_principle_history(self, principle_id: str) -> list[Principle]:
        """返回某条原则的全部版本历史"""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT * FROM principles_v2 WHERE principle_id=? ORDER BY version", (principle_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_principle(r) for r in rows]

    def _row_to_principle(self, r) -> Principle:
        return Principle(
            principle_id=r[1],
            content=r[3],
            source_h_id=r[4],
            source_experience=r[5] or "",
            applicability_tags=json.loads(r[6]) if r[6] else [],
            verification_count=r[7] or 0,
            conflict_principles=json.loads(r[8]) if r[8] else [],
            status=r[9],
        )

    def write_asset_trace(
        self, asset_id: str, level: str, source_h_id: str, summary: str = "", verification_h_ids: str = ""
    ):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            INSERT OR REPLACE INTO asset_trace
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
            (asset_id, level, source_h_id, summary, datetime.now().isoformat(), 0, 0, verification_h_ids, "", "active"),
        )
        conn.commit()
        conn.close()

    def append_trace_log(self, asset_id: str, event: str, detail: str = ""):
        """B-2 P0: 除 SQLite 写入外, 并行追加 audit trail 到 JSONL (append-only).

        SQLite 是主存储 (可查询), AppendOnlyLog 是审计轨 (不可变, 跨仓可聚合).
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO trace_log (asset_id, event, detail, timestamp) VALUES (?,?,?,?)",
            (asset_id, event, detail, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        # B-2 跨仓债 audit trail: append-only JSONL
        try:
            from metaos.audit import audit_log
            log = audit_log(self.data_dir / "audit", "d-layer-trace")
            log.append({
                "ts": datetime.now().isoformat() + "Z",
                "asset_id": asset_id,
                "event": event,
                "detail": detail,
            })
        except Exception:  # defensive fallback  # noqa: BLE001
            # 审计失败不影响主流程
            pass

    # ── V7.0：Session 持久化 ──

    def save_session(self, token: str, h_id: str, name: str, created_at, expires_at, last_used):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            INSERT OR REPLACE INTO h_sessions
            (token, h_id, name, created_at, expires_at, last_used)
            VALUES (?,?,?,?,?,?)
        """,
            (token, h_id, name, created_at.isoformat(), expires_at.isoformat(), last_used.isoformat()),
        )
        conn.commit()
        conn.close()

    def delete_session(self, token: str):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("DELETE FROM h_sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()

    def load_sessions(self) -> list[dict]:
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT token, h_id, name, created_at, expires_at, last_used FROM h_sessions ORDER BY created_at"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            try:
                from datetime import datetime as dt

                result.append(
                    {
                        "token": r[0],
                        "h_id": r[1],
                        "name": r[2],
                        "created_at": dt.fromisoformat(r[3]),
                        "expires_at": dt.fromisoformat(r[4]),
                        "last_used": dt.fromisoformat(r[5]),
                    }
                )
            except Exception:  # defensive fallback  # noqa: BLE001
                pass
        return result

    def save_meta(self, key: str, value: str):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))
        conn.commit()
        conn.close()

    def load_meta(self, key: str, default: str = "") -> str:
        conn = sqlite3.connect(str(self.db_path))
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default

    def get_asset_trace(self, asset_id: str) -> dict:
        conn = sqlite3.connect(str(self.db_path))
        row = conn.execute("SELECT * FROM asset_trace WHERE asset_id=?", (asset_id,)).fetchone()
        logs = conn.execute(
            "SELECT event, detail, timestamp FROM trace_log WHERE asset_id=? ORDER BY id", (asset_id,)
        ).fetchall()
        conn.close()
        if not row:
            return {}
        return {
            "asset_id": row[0],
            "level": row[1],
            "source_h_id": row[2],
            "summary": row[3],
            "auth_timestamp": row[4],
            "verification_count": row[5],
            "challenge_count": row[6],
            "verification_h_ids": row[7].split(",") if row[7] else [],
            "rollback_snapshot_uri": row[8] or "",
            "status": row[9],
            "logs": [{"event": l[0], "detail": l[1], "ts": l[2]} for l in logs],  # noqa: E741
        }

    def count_decision_dependencies(self, asset_id: str) -> int:
        """计算有多少决策引用了某资产"""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("SELECT assets_used FROM decisions").fetchall()
        conn.close()
        count = 0
        for (assets_str,) in rows:
            if assets_str and asset_id in assets_str:
                count += 1
        return count

    def close(self):
        pass  # SQLite auto-closes

    # ── V6#6 修复：元治理持久化 ──

    def save_governance_state(self, state: dict):
        """持久化元治理状态"""
        import json

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS governance_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        for k, v in state.items():
            conn.execute(
                "INSERT OR REPLACE INTO governance_state (key, value) VALUES (?,?)", (k, json.dumps(v, default=str))
            )
        conn.commit()
        conn.close()

    def get_governance_state(self) -> dict:
        """读取元治理持久化状态"""
        import json

        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("SELECT key, value FROM governance_state").fetchall()
        except Exception:  # defensive fallback  # noqa: BLE001
            rows = []
        conn.close()
        result = {}
        for k, v in rows:
            try:
                result[k] = json.loads(v)
            except Exception:  # defensive fallback  # noqa: BLE001
                result[k] = v
        return result
