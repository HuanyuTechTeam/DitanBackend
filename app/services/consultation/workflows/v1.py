"""Coze v1 question order and applicability, independent of model output."""

from dataclasses import dataclass
from typing import Callable

from app.services.consultation.rendering import fixed_question

REPORT_GATE_TEXT = "感谢您的回答，正在为您分析身体情况，请点击下方按钮，获取报告"
REPORT_PROMPT = "L14"


@dataclass(frozen=True)
class WorkflowContext:
    sex: str | None
    age: int | None

    @property
    def is_female(self):
        return self.sex == "女"

    @property
    def is_child(self):
        return self.age is not None and self.age < 10

    @property
    def over_20(self):
        return self.age is not None and self.age >= 20


@dataclass(frozen=True)
class Ask:
    id: str
    prompt_id: str
    when: Callable[[WorkflowContext], bool] = lambda ctx: True

    @property
    def fixed_question(self):
        return fixed_question(self.prompt_id)


@dataclass(frozen=True)
class ReportGate:
    id: str = "report_gate"
    text: str = REPORT_GATE_TEXT


STEPS: tuple[Ask | ReportGate, ...] = (
    Ask("core_history", "L03"),
    Ask("family_health", "L04"),
    Ask("work_stress", "L05"),
    Ask("sleep_quality", "L07"),
    Ask("nocturia", "L11"),
    Ask("energy_mood", "L06"),
    Ask("diet_core", "L08"),
    Ask("diet_extra", "L09"),
    Ask("digestion", "L10"),
    Ask("exercise_habit", "L12"),
    Ask("exercise_tolerance", "L13"),
    Ask("children", "L15", lambda c: c.is_female and not c.is_child and c.over_20),
    Ask("menstruation", "L16", lambda c: c.is_female and not c.is_child),
    Ask("menstruation_detail", "L17", lambda c: c.is_female and not c.is_child),
    Ask("leukorrhea", "L18", lambda c: c.is_female and not c.is_child),
    ReportGate(),
)


def first_step(ctx: WorkflowContext) -> Ask | ReportGate:
    return next(
        step for step in STEPS if isinstance(step, ReportGate) or step.when(ctx)
    )


def next_step(current_step_id: str, ctx: WorkflowContext) -> Ask | ReportGate:
    index = next(
        (i for i, step in enumerate(STEPS) if step.id == current_step_id), None
    )
    if index is None:
        raise ValueError(f"Unknown step: {current_step_id}")
    for step in STEPS[index + 1 :]:
        if isinstance(step, ReportGate) or step.when(ctx):
            return step
    return STEPS[-1]
