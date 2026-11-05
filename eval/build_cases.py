"""生成 45 条金标准评测集（eval/cases.jsonl）。

金标准来源：法条规则 + 五城 2026 口径（京/沪/广/深/杭，口径文件 data/city/*.json，
今天 2026-11-04）。deadline 由"终止日 + 1 年"算出，不引用被测代码。
"""
import json
import os
from datetime import date, timedelta

TODAY = date(2026, 11, 4)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.jsonl")

BASE = {
    "employer_name": "杭州云帆科技有限公司", "employer_city": "杭州市",
    "start_date": "2023-11-01", "end_date": "2026-09-15", "avg_wage": 8600,
    "dispute_types": ["termination"], "still_employed": "no",
    "prior_proceeding": "none", "termination_by": "employer",
    "termination_reason": "", "contract_state": "one",
    "claims": ["compensation_2n"], "company_status": "normal",
}


def N(scope=None, retired="no", intern="no", legality="likely_illegal",
      resign="not_applicable", lr="", rr=""):
    return {"scope_issues": [{"key": k, "evidence": ""} for k in (scope or [])],
            "subject_flags": {"retired_or_reemployment": {"value": retired, "evidence": ""},
                              "student_intern": {"value": intern, "evidence": ""}},
            "termination": {"legality": legality, "legality_reason": lr,
                            "resign_ground": resign, "resign_ground_reason": rr}}


def deadline_of(end):
    if not end:
        return None, None
    d = date.fromisoformat(end) + timedelta(days=365)
    return d.isoformat(), (d - TODAY).days


def case(cid, story, slots, needs, scope, qual, decision, materials, articles, why,
         end_override=None):
    merged = {**BASE, **slots}
    end = end_override if end_override is not None else merged.get("end_date")
    dl, days = deadline_of(end if merged.get("still_employed") != "yes" else None)
    if merged.get("still_employed") == "yes" and set(merged.get("dispute_types") or []) & {"unpaid_wage", "overtime"}:
        why += "（在职主张劳动报酬，时效不受一年限制）"
    return {"id": cid, "story": story, "slots": merged, "needs": needs,
            "gold": {"scope": scope, "qual": qual, "decision": decision,
                     "deadline": dl, "days": days, "materials": materials,
                     "articles": articles, "why": why}}


C = []

# ---------- 受案范围（7） ----------
C.append(case("E01", "公司三年没给我交社保，我要它补缴。",
    {"dispute_types": ["social_insurance"], "claims": ["unsure"]}, N(scope=["social_insurance_backpay"]),
    "out_of_scope", "pass", "cannot", ["id_card"], ["shebaofa:63"],
    "补缴社保属行政征缴，指路社保稽核/12333"))
C.append(case("E02", "公司一直没给我交公积金，能要回来吗？",
    {"dispute_types": ["other"], "claims": ["unsure"]}, N(scope=["housing_fund"]),
    "out_of_scope", "pass", "cannot", [], [], "公积金归公积金中心，12329"))
C.append(case("E03", "我在工地摔了，想直接仲裁要工伤赔偿。",
    {"dispute_types": ["other"], "claims": ["unsure"]}, N(scope=["work_injury_recognization"]),
    "out_of_scope", "pass", "cannot", [], [], "工伤认定是行政前置程序"))
C.append(case("E04", "我是事业单位在编的，单位把我辞了。",
    {"dispute_types": ["termination"]}, N(scope=["personnel_dispute"]),
    "out_of_scope", "pass", "cannot", [], [], "在编人员走人事争议仲裁"))
C.append(case("E05", "老板欠我五万工资，我要让他坐牢。",
    {"dispute_types": ["unpaid_wage"], "claims": ["wage"]}, N(scope=["criminal"]),
    "out_of_scope", "pass", "cannot", [], [], "刑事责任由司法机关认定，不作定性"))
C.append(case("E06", "我们天天996，我要举报公司超时加班，自己没别的诉求。",
    {"dispute_types": ["overtime"], "claims": ["unsure"]}, N(scope=["supervision_only"]),
    "out_of_scope", "pass", "cannot", [], ["jiancha:9"], "单纯违法用工举报走监察"))
C.append(case("E07", "公司只给我交了工伤险，我自己垫了公司该交的社保费，我要它赔。",
    {"dispute_types": ["social_insurance"], "claims": ["wage"]}, N(),
    "pass", "pass", "recommend", ["si_record"], ["shebaofa:63"],
    "垫付的单位应缴社保费属可主张损失，按缴费凭证金额算"))

# ---------- 资格（8） ----------
C.append(case("E08", "去年三月公司把我开了，我一直没管，现在还能仲裁吗？",
    {"end_date": "2025-03-01"}, N(),
    "pass", "fail", "cannot", [], ["tiaojiezhongcai:27"], "超过一年时效"))
C.append(case("E09", "同一件事我仲裁过，裁决书都下来了，我不服。",
    {"prior_proceeding": "arbitration_done"}, N(),
    "pass", "fail", "cannot", [], ["sfjs1:6"], "一事不再理"))
C.append(case("E10", "上次调解签了协议，公司没给钱，我还能再仲裁吗？",
    {"prior_proceeding": "settled"}, N(),
    "pass", "warn", "recommend", ["termination_notice"], ["laodonghetongfa:87"],
    "协议原则上不再受理，但可主张撤销，仍可申请"))
C.append(case("E11", "我在上海上班，公司也在上海，上个月把我开了，什么理由都没给。",
    {"employer_city": "上海市"}, N(),
    "pass", "pass", "not_recommended", [], ["laodonghetongfa:87"],
    "上海在五城覆盖内，按上海口径算，不套杭州数字；暂无书证，先补材料再提交"))
C.append(case("E12", "我已经退休了，又被公司返聘，现在把我辞了。",
    {"start_date": "2025-01-01"}, N(retired="yes"),
    "pass", "warn", "not_recommended", [], [], "退休返聘通常按劳务关系"))
C.append(case("E13", "我还是在校学生，出来实习被辞了。",
    {"start_date": "2026-06-01", "end_date": "2026-10-01"}, N(intern="yes"),
    "pass", "warn", "not_recommended", [], [], "在校实习一般不认定劳动关系"))
C.append(case("E14", "我在公司干了八年，去年被开，中间一直发微信催老板给钱。",
    {"start_date": "2018-01-01", "end_date": "2025-06-01", "last_claim_date": "2026-08-01"}, N(),
    "pass", "pass", "recommend", ["termination_notice"], ["tiaojiezhongcai:27"],
    "主张权利导致时效中断，从 2026-08-01 重算", end_override="2026-08-01"))
C.append(case("E15", "公司说我年龄大了不适合，让我别来了。",
    {"start_date": "2024-06-01", "end_date": "2026-10-01", "avg_wage": 7000}, N(),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:87"],
    "无合法事由解除，2N"))

# ---------- 解除（8） ----------
C.append(case("E16", "老板口头让我别来了，什么理由都没说。",
    {"termination_reason": ""}, N(legality="likely_illegal", lr="无任何解除依据"),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:87"], "无理由解除 → 2N"))
C.append(case("E17", "公司说经营困难裁员，开了二十多个人。",
    {"termination_reason": "经济性裁员"}, N(legality="likely_legal", lr="经济性裁员属法定情形"),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:46"], "合法裁员的 N"))
C.append(case("E18", "我自己写的辞职信，说家里有事。",
    {"termination_by": "employee", "termination_reason": "家里有事",
     "claims": ["compensation_n"]}, N(legality="not_applicable", resign="personal"),
    "pass", "pass", "not_recommended", ["id_card"], ["laodonghetongfa:37"], "个人原因辞职无补偿"))
C.append(case("E19", "公司三年没交社保，我以此为由辞职了，能要补偿吗？",
    {"termination_by": "employee", "termination_reason": "公司没交社保",
     "dispute_types": ["termination", "social_insurance"], "claims": ["compensation_n"]},
    N(legality="not_applicable", resign="article38", rr="未依法缴纳社保属第38条事由"),
    "pass", "pass", "recommend", ["si_record"], ["laodonghetongfa:38", "laodonghetongfa:46"],
    "被迫解除仍可主张 N"))
C.append(case("E20", "试用期早就过了，公司还拿试用期不合格辞我。",
    {"start_date": "2024-06-01", "end_date": "2026-09-15", "termination_reason": "试用期不合格"},
    N(legality="likely_illegal", lr="试用期已过，理由不成立"),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:87"], "试用期已过 → 2N"))
C.append(case("E21", "我怀孕了，公司把我降到前台还降了工资，后来直接辞退。",
    {"start_date": "2024-03-01", "end_date": "2026-08-01", "termination_reason": "三期不能胜任",
     "special_status": ["pregnancy"],
     "dispute_types": ["termination", "unpaid_wage"], "claims": ["compensation_2n", "wage"]},
    N(legality="likely_illegal", lr="孕期解除受限"),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:42", "laodonghetongfa:87"],
    "三期解除受限，违法解除 2N"))
C.append(case("E22", "我连着旷工十天，公司按严重违纪把我开了。",
    {"termination_reason": "连续旷工十天"}, N(legality="likely_legal", lr="严重违纪属实"),
    "pass", "pass", "not_recommended", [], ["laodonghetongfa:39"], "严重违纪解除合法，无补偿"))
C.append(case("E23", "公司跟我谈好了，给我 N 我就走，签了协议。",
    {"termination_reason": "协商一致", "termination_by": "mutual", "claims": ["compensation_n"]},
    N(legality="not_applicable"),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:36", "laodonghetongfa:46"],
    "协商一致由单位提出的 N"))

# ---------- 未签合同（4） ----------
C.append(case("E24", "入职八个月一直没签合同，现在被辞了。",
    {"start_date": "2026-03-01", "end_date": "2026-10-01", "contract_state": "none",
     "dispute_types": ["termination", "no_contract"], "claims": ["compensation_2n", "double_wage"]},
    N(),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:82"], "未签合同二倍工资"))
C.append(case("E25", "干了一年半都没签合同，能要多少二倍工资？",
    {"start_date": "2025-01-01", "end_date": "2026-06-01", "contract_state": "none",
     "dispute_types": ["no_contract"], "claims": ["double_wage"]}, N(),
    "pass", "pass", "recommend", ["badge"], ["laodonghetongfa:82", "sfjs2:6"], "二倍工资最多 11 个月"))
C.append(case("E26", "签过一次合同到期了，公司不续签也没给钱。",
    {"contract_state": "one", "end_date": "2026-08-31", "claims": ["compensation_n"]}, N(legality="likely_legal"),
    "pass", "pass", "recommend", ["relation"], ["laodonghetongfa:46"], "合同到期不续签的 N"))
C.append(case("E27", "我已经签过两次固定期限合同，公司还是不给无固定期限。",
    {"contract_state": "two_plus", "dispute_types": ["no_contract"],
     "claims": ["double_wage"]}, N(),
    "pass", "pass", "recommend", ["relation"], ["laodonghetongfa:14"],
    "两次固定期限后可要求无固定期限，属于可主张事项；金额随补签后的工资确定"))

# ---------- 工资/加班/年假（5） ----------
C.append(case("E28", "公司拖了我三个月工资，我还在上班。",
    {"still_employed": "yes", "end_date": None, "dispute_types": ["unpaid_wage"],
     "unpaid_amount": 18000, "claims": ["wage"]}, N(),
    "pass", "pass", "recommend", ["bank_flow"], ["laodonghetongfa:50"],
    "在职欠薪不受一年时效限制"))
C.append(case("E29", "离职后还欠我六千工资，公司还在正常开门。",
    {"dispute_types": ["unpaid_wage"], "unpaid_amount": 6000, "claims": ["wage"]}, N(),
    "pass", "pass", "better_alternative", ["bank_flow"], ["laodonghetongfa:50"],
    "小额欠薪、单位在经营 → 监察更快"))
C.append(case("E30", "我天天加班到十点，但什么记录都没有。",
    {"dispute_types": ["overtime"], "claims": ["wage"]}, N(),
    "pass", "pass", "not_recommended", ["attendance"], ["laodongfa:44"], "加班无证据，先补证"))
C.append(case("E31", "我有钉钉考勤导出，加班三百多个小时。",
    {"dispute_types": ["overtime"], "claims": ["wage"], "overtime_hours": 300}, N(),
    "pass", "pass", "recommend", ["attendance"], ["laodongfa:44"], "有考勤，加班费可算"))
C.append(case("E32", "两年没休年假，能折算钱吗？",
    {"dispute_types": ["annual_leave"], "unused_leave_days": 10,
     "claims": ["annual_leave_pay"]}, N(),
    "pass", "pass", "recommend", ["leave_record"], ["nianxiujia:5"], "未休年假 200%"))

# ---------- 社保/竞业（4） ----------
C.append(case("E33", "公司没给我交社保，我自己去看病全自费。",
    {"dispute_types": ["social_insurance"], "claims": ["wage"]}, N(),
    "pass", "pass", "recommend", ["si_record"], ["shebaofa:63"],
    "社保待遇损失可主张赔偿；医疗费金额按票据确定"))
C.append(case("E34", "我离职后公司说我违反竞业限制，要我赔二十万，可我就是个保安。",
    {"dispute_types": ["noncompete"], "claims": ["unsure"]}, N(legality="not_applicable"),
    "pass", "pass", "not_recommended", ["noncompete_agreement"], ["laodonghetongfa:24"],
    "条款大概率无效：不必主动仲裁，等公司索赔时抗辩即可"))
C.append(case("E35", "我是技术总监，签了竞业协议拿了补偿，现在去了对手公司。",
    {"dispute_types": ["noncompete"], "claims": ["unsure"]}, N(legality="not_applicable"),
    "pass", "pass", "not_recommended", ["noncompete_agreement"], ["laodonghetongfa:23"],
    "高管竞业条款有效，违约风险高"))
C.append(case("E36", "公司用我个人账户发工资，也没交社保，我被辞了。",
    {"dispute_types": ["termination", "social_insurance"], "avg_wage": 12000,
     "wage_payment_form": "personal", "claims": ["compensation_2n"]}, N(),
    "pass", "pass", "recommend", ["bank_flow"], ["laodonghetongfa:87"], "个人账户发放不影响劳动关系"))

# ---------- 综合（4） ----------
C.append(case("E37", "欠我两个月工资，还把我辞了，也没签合同。",
    {"dispute_types": ["unpaid_wage", "termination", "no_contract"], "unpaid_amount": 17200,
     "contract_state": "none", "claims": ["compensation_2n", "double_wage", "wage"]}, N(),
    "pass", "pass", "recommend", ["termination_notice", "bank_flow"],
    ["laodonghetongfa:87", "laodonghetongfa:82"], "多项诉求合并主张"))
C.append(case("E38", "没签合同，还天天加班，工资也拖着。",
    {"dispute_types": ["no_contract", "overtime", "unpaid_wage"], "contract_state": "none",
     "unpaid_amount": 8600, "claims": ["double_wage", "wage"]}, N(),
    "pass", "pass", "recommend", ["attendance", "bank_flow"],
    ["laodonghetongfa:82", "laodongfa:44"], "未签+加班+欠薪"))
C.append(case("E39", "我在一家小餐馆干了两年，没合同没社保，现在不让我干了。",
    {"employer_name": "杭州市西湖区某某餐饮店", "start_date": "2024-09-01",
     "end_date": "2026-10-20", "contract_state": "none", "avg_wage": 5500,
     "dispute_types": ["termination", "no_contract"], "claims": ["compensation_2n", "double_wage"]}, N(),
    "pass", "pass", "recommend", ["badge"], ["laodonghetongfa:87"], "个体户同样适用劳动合同法"))
C.append(case("E40", "公司已经注销了，老板电话也不接，还欠我工资。",
    {"company_status": "abnormal", "dispute_types": ["unpaid_wage"], "unpaid_amount": 20000,
     "claims": ["wage"]}, N(),
    "pass", "pass", "not_recommended", ["company_registry"], ["laodonghetongfa:50"],
    "单位注销，执行不到钱，先查主体与财产线索"))

# ---------- 时效/城市（5） ----------
C.append(case("E41", "公司上个月把我开了，我还没去仲裁。",
    {"end_date": "2026-10-05"}, N(),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:87"],
    "时效剩不多，优先级最高"))
C.append(case("E42", "今年一月被辞退，一直拖着没处理。",
    {"end_date": "2026-01-20"}, N(),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:87"], "时效剩 200 多天"))
C.append(case("E43", "我还在职，公司把我调岗降薪了，每月少发两千。",
    {"still_employed": "yes", "end_date": None, "dispute_types": ["unpaid_wage"],
     "termination_reason": "调岗降薪", "unpaid_amount": 12000, "claims": ["wage"]}, N(legality="not_applicable"),
    "pass", "pass", "recommend", ["relation"], ["laodonghetongfa:35", "laodonghetongfa:50"],
    "在职被降薪，可主张差额；在职欠薪不受一年时效限制"))
C.append(case("E44", "昨天最后一天上班，今天开始不上班了。",
    {"start_date": "2025-06-01", "end_date": "2026-11-03"}, N(),
    "pass", "pass", "recommend", ["termination_notice"], ["laodonghetongfa:87"], "刚离职，时效充裕"))
C.append(case("E45", "公司在南京，我人也在南京，欠我三个月工资。",
    {"employer_city": "南京市", "dispute_types": ["unpaid_wage"], "unpaid_amount": 24000,
     "claims": ["wage"]}, N(),
    "pass", "out_of_scope", "cannot", [], [], "跨城市只指路"))

with open(OUT, "w", encoding="utf-8") as f:
    for c in C:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")
print("wrote", len(C), "cases ->", OUT)
