"""Small construction examples for documentation and tests."""

from .contracts import AgentSession, ExecutionMode, OperationalRisk, ProviderKind


def staged_code_change(description: str) -> AgentSession:
    return AgentSession(
        provider=ProviderKind.CODEX,
        description=description,
        risk=OperationalRisk.R2,
        mode=ExecutionMode.STAGE,
        scope=["repository working tree"],
        exclusions=["git commit", "git push", "network access"],
        success_criteria=["reviewable patch exists"],
        stop_conditions=["same approach fails twice without new evidence"],
        rollback_or_containment=["patch remains in staging until reviewed"],
    )
