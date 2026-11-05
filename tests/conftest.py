import importlib
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import llm as llm_mod  # noqa: E402
from app import session as store  # noqa: E402

# 各模块用 `from .llm import chat_json` 绑定了函数对象，只改 app.llm 不够，
# 必须连这些模块里的同名属性一起替换。
LLM_BINDING_MODULES = ("app.followup", "app.main", "app.extract", "app.needs")
LLM_FUNCS = ("chat", "chat_json", "chat_image")


def _no_llm(*args, **kwargs):
    """测试里绝不允许真的发网络请求：直接抛 LLMError，让上层走降级分支。"""
    raise llm_mod.LLMError("测试环境不调用真实模型")


@pytest.fixture(autouse=True)
def block_llm(monkeypatch):
    """全局兜底：任何用例误触模型调用都会立刻失败，而不是等 120s 超时。

    需要真实模型行为的用例，可在用例内部自行 monkeypatch 覆盖。
    """
    for name in LLM_FUNCS:
        if hasattr(llm_mod, name):
            monkeypatch.setattr(llm_mod, name, _no_llm)
    for mod_name in LLM_BINDING_MODULES:
        mod = importlib.import_module(mod_name)
        for name in LLM_FUNCS:
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, _no_llm)
    yield

CITY = json.load(open(os.path.join(ROOT, "data", "city", "hangzhou.json"), encoding="utf-8"))
TODAY = date(2026, 11, 4)


def needs(scope=None, retired="no", intern="no", legality="uncertain",
          resign="not_applicable", legality_reason="", resign_reason=""):
    return {
        "scope_issues": [{"key": k, "evidence": ""} for k in (scope or [])],
        "subject_flags": {
            "retired_or_reemployment": {"value": retired, "evidence": ""},
            "student_intern": {"value": intern, "evidence": ""},
        },
        "termination": {"legality": legality, "legality_reason": legality_reason,
                        "resign_ground": resign, "resign_ground_reason": resign_reason},
    }


@pytest.fixture
def city():
    return CITY


@pytest.fixture
def today():
    return TODAY


@pytest.fixture
def needs_factory():
    return needs


def make_session(slots, materials=None, suspect=None, story=None):
    s = store.create()
    for k, v in slots.items():
        src = "image_confirmed" if k in (suspect or {}) else "oral"
        s.set_slot(k, v, src, True)
    for m in materials or []:
        s.add_material(m)
    if story:
        s.story = list(story)
    return s
