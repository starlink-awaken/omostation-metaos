import os
import yaml
from pathlib import Path
import logging

logger = logging.getLogger("metaos.cognitive")

class CognitiveFrameworkLoader:
    """
    动态加载和匹配 M1 层定义的思维框架 (CognitiveFramework)
    """
    def __init__(self):
        # 寻找 ecos 项目中的 m1 cognitive_framework 目录
        self.m1_dir = Path(__file__).resolve().parents[4] / "ecos" / "src" / "ecos" / "ssot" / "mof" / "m1" / "cognitive_framework"
        self.frameworks = []
        self._load_all()

    def _load_all(self):
        if not self.m1_dir.exists():
            return
            
        for filepath in self.m1_dir.glob("*.yaml"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    fw = yaml.safe_load(f)
                    if fw and fw.get("m1_type") == "CognitiveFramework":
                        self.frameworks.append(fw)
            except Exception as e:
                logger.warning(f"Failed to load cognitive framework {filepath}: {e}")

    def get_applicable_frameworks(self, task_context: str) -> list[dict]:
        """
        根据任务上下文，自动匹配最合适的思维框架
        """
        matched = []
        for fw in self.frameworks:
            props = fw.get("properties", {})
            triggers = props.get("trigger_conditions", [])
            # 简单的关键词命中测试 (未来可以接入小模型进行向量匹配)
            if any(keyword.lower() in task_context.lower() for keyword in triggers) or \
               any(keyword in task_context for keyword in ["架构", "决策", "设计", "重构", "复杂"]):
                matched.append(fw)
        return matched

    def build_cognitive_prompt(self, task_context: str) -> str:
        """
        构建用于附加到系统 Prompt 之后的思维框架声明
        """
        applicable = self.get_applicable_frameworks(task_context)
        if not applicable:
            return ""
            
        prompt = "\n\n# 【强制约束】当前任务已触发动态加载的思维框架：\n"
        for fw in applicable:
            props = fw.get("properties", {})
            prompt += f"\n## 框架：{props.get('framework_name', fw.get('name'))}\n"
            prompt += f"核心目的：{props.get('core_purpose', '')}\n"
            prompt += f"交互模式：{props.get('interaction_mode', 'sequential')}\n"
            prompt += "你必须依次运用以下角色视角进行系统性思考与方案验证：\n"
            for p in props.get("personas", []):
                prompt += f"- {p.get('icon', '')} {p.get('role', 'Unknown')}: {p.get('focus', '')}\n"
                
        return prompt
