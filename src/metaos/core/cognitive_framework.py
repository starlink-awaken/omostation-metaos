"""动态加载 M1 CognitiveFramework — 无 monorepo 硬路径 (ADR-0181).

解析顺序:
1. env METAOS_COGNITIVE_FRAMEWORK_DIR
2. METAOS_PREFER_BUNDLED=1 → package resources (MANIFEST 同步镜像)
3. env ECOS_MOF_M1_DIR / cognitive_framework
4. env ECOS_ROOT / src/ecos/ssot/mof/m1/cognitive_framework
5. 自本文件向上 walk，发现 projects/ecos/.../cognitive_framework
6. 包内 resources/cognitive_framework（离线 fallback）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger("metaos.cognitive")

_MOF_REL = Path("src/ecos/ssot/mof/m1/cognitive_framework")
_PROJECTS_REL = Path("projects/ecos") / _MOF_REL


def _bundled_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "resources" / "cognitive_framework"


def resolve_cognitive_framework_dir() -> Path | None:
    """Resolve directory containing CognitiveFramework YAML files."""
    env_dir = os.environ.get("METAOS_COGNITIVE_FRAMEWORK_DIR", "").strip()
    if env_dir:
        p = Path(env_dir).expanduser().resolve()
        if p.is_dir():
            return p
        logger.warning("METAOS_COGNITIVE_FRAMEWORK_DIR set but not a directory: %s", p)

    if os.environ.get("METAOS_PREFER_BUNDLED", "0").strip() == "1":
        bundled = _bundled_dir()
        if bundled.is_dir() and any(bundled.glob("*.yaml")):
            return bundled

    m1 = os.environ.get("ECOS_MOF_M1_DIR", "").strip()
    if m1:
        p = Path(m1).expanduser().resolve() / "cognitive_framework"
        if p.is_dir():
            return p

    ecos_root = os.environ.get("ECOS_ROOT", "").strip()
    if ecos_root:
        p = Path(ecos_root).expanduser().resolve() / _MOF_REL
        if p.is_dir():
            return p

    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / _PROJECTS_REL
        if candidate.is_dir():
            return candidate
        candidate2 = parent / _MOF_REL
        if candidate2.is_dir() and (parent / "src" / "ecos").is_dir():
            return candidate2

    bundled = _bundled_dir()
    if bundled.is_dir() and any(bundled.glob("*.yaml")):
        return bundled
    return None


def _is_cognitive_framework(doc: dict) -> bool:
    return doc.get("m1_type") == "CognitiveFramework" or doc.get("type") == "CognitiveFramework"


class CognitiveFrameworkLoader:
    """动态加载和匹配 M1 层定义的思维框架 (CognitiveFramework)。"""

    def __init__(self, m1_dir: Path | str | None = None):
        if m1_dir is not None:
            self.m1_dir: Path | None = Path(m1_dir)
        else:
            self.m1_dir = resolve_cognitive_framework_dir()
        self.frameworks: list[dict] = []
        self._load_all()

    def _load_all(self) -> None:
        if not self.m1_dir or not self.m1_dir.exists():
            logger.debug("cognitive_framework_dir_unavailable path=%s", self.m1_dir)
            return
        for filepath in sorted(self.m1_dir.glob("*.yaml")):
            try:
                with open(filepath, encoding="utf-8") as f:
                    fw = yaml.safe_load(f)
                    if fw and _is_cognitive_framework(fw):
                        self.frameworks.append(fw)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load cognitive framework %s: %s", filepath, e)

    def get_applicable_frameworks(self, task_context: str) -> list[dict]:
        matched = []
        for fw in self.frameworks:
            props = fw.get("properties", {})
            triggers = props.get("trigger_conditions", [])
            if any(keyword.lower() in task_context.lower() for keyword in triggers) or any(
                keyword in task_context for keyword in ["架构", "决策", "设计", "重构", "复杂"]
            ):
                matched.append(fw)
        return matched

    def build_cognitive_prompt(self, task_context: str) -> str:
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
                prompt += (
                    f"- {p.get('icon', '')} {p.get('role', p.get('name', 'Unknown'))}: "
                    f"{p.get('focus', p.get('mindset', ''))}\n"
                )
        return prompt
