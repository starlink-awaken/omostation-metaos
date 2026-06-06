"""权限门控器——绿/黄/红灯判定（全部规则外部化）"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from metaos.core.types import DecisionLevel, Task  # type: ignore[import-not-found]

# 引擎根目录（相对于此文件的位置）
_ENGINE_DIR = Path(__file__).resolve().parent.parent


class DecisionGate:
    """基于红/黄/绿灯矩阵判定任务权限级别。

    所有规则从 JSON 配置文件加载，不包含硬编码常量。
    配置变更无需修改代码，JSON 文件支持热重载。
    """

    def __init__(self, config_path: str = "config/decision_matrix.json"):
        self.config_path = _ENGINE_DIR / config_path
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """从外部 JSON 加载全部规则。无内建默认值。"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"决策矩阵配置文件不存在: {self.config_path}\n请创建 config/decision_matrix.json")
        with open(self.config_path) as f:
            return json.load(f)

    def reload(self):
        """热重载配置——运行时调用，无需重启"""
        self.config = self._load_config()

    @property
    def red_keywords(self) -> list[str]:
        return self.config.get("red_keywords", [])

    @property
    def yellow_keywords(self) -> list[str]:
        return self.config.get("yellow_keywords", [])

    @property
    def yellow_deadline_hours(self) -> int:
        return self.config.get("yellow_deadline_hours", 24)

    def evaluate(self, task: Task) -> tuple[DecisionLevel, str, datetime]:
        """
        返回 (级别, 原因, 黄灯截止时间)
        规则：红灯 > 黄灯 > 绿灯
        TD-C01 修复：中英文都使用逐字精确匹配，\b 不适用于 CJK
        """
        input_lower = task.input.lower()

        for kw in self.red_keywords:
            # \b 不匹配 CJK 字符，使用逐字精确匹配替代
            if kw.lower() in input_lower:
                return (DecisionLevel.RED, f"触发了红线关键词: {kw}", None)

        for kw in self.yellow_keywords:
            if kw.lower() in input_lower:
                deadline = datetime.now() + timedelta(hours=self.yellow_deadline_hours)
                return (DecisionLevel.YELLOW, f"需事后确认: {kw}", deadline)

        return (DecisionLevel.GREEN, "default_green", None)

    def check_red_list_modification(self, operation: str) -> bool:
        """检查是否试图修改红灯区清单（只增不减）"""
        if not self.config.get("red_only_increase", True):
            return True
        if "remove" in operation.lower() or "delete" in operation.lower() or "减少" in operation:
            return False
        return True
