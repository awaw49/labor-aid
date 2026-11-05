"""法条与类案的混合检索：条号精确匹配 + BM25（中文字符二元组）。"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def _bigrams(text: str) -> list[str]:
    t = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", text)
    grams = [t[i:i + 2] for i in range(max(0, len(t) - 1))]
    grams += re.findall(r"[A-Za-z0-9]+", text)
    return grams


class LawCorpus:
    def __init__(self, data_dir: str = os.path.join(DATA, "laws")):
        self.laws: dict[str, dict] = {}
        self.articles: list[dict] = []
        for fn in sorted(os.listdir(data_dir)):
            if not fn.endswith(".json") or fn == "index.json":
                continue
            law = json.load(open(os.path.join(data_dir, fn), encoding="utf-8"))
            self.laws[law["id"]] = law
            for a in law["articles"]:
                self.articles.append({
                    "id": f"{law['id']}:{a['no']}",
                    "law_id": law["id"], "law": law["title"], "no": a["no"],
                    "no_cn": a["no_cn"], "text": a["text"],
                    "chapter": a.get("chapter", ""), "section": a.get("section", ""),
                    "effective": law.get("effective") or law.get("promulgated"),
                    "source": law["source"],
                    "tokens": Counter(_bigrams(a["text"] + law["title"])),
                })
        self._build_idf()

    def _build_idf(self):
        df = Counter()
        for a in self.articles:
            for t in a["tokens"]:
                df[t] += 1
        n = len(self.articles)
        self.idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1) for t, c in df.items()}
        self.avg_len = sum(sum(a["tokens"].values()) for a in self.articles) / max(1, n)

    def get(self, citation_id: str) -> dict | None:
        law_id, _, no = citation_id.partition(":")
        if not no.isdigit():
            return None
        for a in self.articles:
            if a["law_id"] == law_id and a["no"] == int(no):
                return a
        return None

    def search(self, query: str, limit: int = 5) -> list[dict]:
        q = Counter(_bigrams(query))
        if not q:
            return []
        scored = []
        for a in self.articles:
            s = 0.0
            dl = sum(a["tokens"].values())
            for t, qf in q.items():
                tf = a["tokens"].get(t)
                if not tf:
                    continue
                idf = self.idf.get(t, 0.0)
                s += qf * idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * dl / self.avg_len))
            if s > 0:
                scored.append((s, a))
        scored.sort(key=lambda x: -x[0])
        return [{"score": round(s, 3), **{k: v for k, v in a.items() if k != "tokens"}}
                for s, a in scored[:limit]]

    def by_ids(self, ids: list[str]) -> tuple[list[dict], list[str]]:
        good, bad = [], []
        for i in ids:
            a = self.get(i)
            (good.append({k: v for k, v in a.items() if k != "tokens"}) if a else bad.append(i))
        return good, bad


class CaseCorpus:
    TAG_MAP = {
        "termination": ["解除", "违法解除", "经济补偿", "赔偿金", "继续履行"],
        "no_contract": ["未签合同", "二倍工资", "计算口径"],
        "unpaid_wage": ["工资", "劳动报酬", "欠薪"],
        "overtime": ["加班费", "工时"],
        "annual_leave": ["年休假"],
        "social_insurance": ["社会保险", "社保", "待遇损失"],
        "noncompete": ["竞业限制"],
        "confirm_relation": ["劳动关系确认", "混同用工"],
    }

    def __init__(self, path: str = os.path.join(DATA, "cases", "cases.json")):
        d = json.load(open(path, encoding="utf-8"))
        self.cases = d["cases"]

    def match(self, types: set[str], text: str = "", limit: int = 3) -> list[dict]:
        wanted = set()
        for t in types:
            wanted.update(self.TAG_MAP.get(t, []))
        scored = []
        for c in self.cases:
            s = 0
            for tag in c["tags"]:
                if tag in wanted:
                    s += 3
            for w in wanted:
                if w in c["holding"] or w in c["title"]:
                    s += 1
            if s:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return [{k: v for k, v in c.items()} for _, c in scored[:limit]]
