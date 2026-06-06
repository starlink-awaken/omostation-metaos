"""路由决策器——任务→模型匹配（全部规则外部化）"""

import json
from pathlib import Path

from metaos.core.types import Task  # type: ignore[import-not-found]

# 引擎根目录（相对于此文件的位置）
_ENGINE_DIR = Path(__file__).resolve().parent.parent


class Router:
    """将任务按类型路由至合适的 M 模型。

    所有路由规则从外部 JSON 文件加载，无硬编码常量。
    """

    def __init__(self, config_path: str = "config/task_routes.json"):
        self.config_path = _ENGINE_DIR / config_path
        self.routes = self._load_config()

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            raise FileNotFoundError(f"路由配置文件不存在: {self.config_path}\n请创建 config/task_routes.json")
        with open(self.config_path) as f:
            return json.load(f)

    def reload(self):
        """热重载路由配置"""
        self.routes = self._load_config()

    def resolve(self, task: Task, healthy_models: list[str]) -> list[str]:
        """返回候选模型ID列表，已过滤不可用的"""
        candidates = self.routes.get(task.task_type, self.routes.get("default", []))
        return [mid for mid in candidates if mid in healthy_models]

    def apply_cost_optimization(self, model_ids: list[str]) -> list[str]:
        return model_ids
