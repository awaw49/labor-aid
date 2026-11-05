"""材料清单：按案由生成 + 举证责任分配 + 获取途径 + 拍照上传入口。纯规则库。"""
from __future__ import annotations

BASE = [
    {"key": "application", "name": "劳动人事争议仲裁申请书", "purpose": "立案必备",
     "burden": "申请人", "how": "按被申请人人数 +1 份准备；可现场手抄或打印",
     "required": True},
    {"key": "id_card", "name": "身份证复印件", "purpose": "主体资格",
     "burden": "申请人", "how": "正反面复印 1 份，现场核原件", "required": True},
    {"key": "company_registry", "name": "用人单位工商登记信息", "purpose": "明确被申请人全称与存续状态",
     "burden": "申请人", "how": "用「电子营业执照」小程序，或到仲裁窗口请工作人员查企业登记信息（窗口可现场打印）",
     "required": True, "material_type": "company_registry"},
    {"key": "relation", "name": "劳动关系证明（合同/工资流水/社保记录/考勤/工牌/工作群）",
     "purpose": "证明“我在这家公司上过班”", "burden": "申请人初步举证",
     "how": "银行 App 导出工资流水、浙里办查社保缴纳记录、企业微信导出工作群记录",
     "required": True, "material_type": "contract"},
]

BY_TYPE = {
    "termination": [
        {"key": "termination_notice", "name": "解除通知 / 离职证明 / 辞退聊天记录",
         "purpose": "解除事实、解除主体、解除日期与理由（决定 N / 2N / 0）",
         "burden": "申请人举证解除事实；单位解除的，由单位举证解除合法性",
         "how": "书面通知原件、邮件、HR 微信/钉钉截图；口头辞退可录自己参与的谈话",
         "required": True, "material_type": "termination_notice"},
        {"key": "wage_standard", "name": "工资标准证据（工资条/银行流水/个税记录）",
         "purpose": "计算 N / 2N 的基数", "burden": "申请人；工资台账在单位",
         "how": "个人所得税 App → 收入纳税明细；银行流水标注“工资”的入账",
         "required": True, "material_type": "payslip"},
    ],
    "no_contract": [
        {"key": "no_contract_proof", "name": "未签合同的佐证（入职登记、工牌、工作群、工资流水）",
         "purpose": "证明用工事实且无书面合同", "burden": "申请人初步举证；单位应提供合同文本",
         "how": "入职通知、排班表、工作群公告、社保参保记录", "required": True,
         "material_type": "badge"},
    ],
    "unpaid_wage": [
        {"key": "wage_owed", "name": "欠薪证据（工资条、流水、催讨记录、考勤）",
         "purpose": "欠付金额与欠付期间", "burden": "申请人；工资支付记录由单位保管",
         "how": "近 12 个月工资条 + 银行流水 + 催讨聊天记录", "required": True,
         "material_type": "bank_flow"},
    ],
    "overtime": [
        {"key": "overtime_proof", "name": "加班证据（打卡记录、排班表、加班审批、工作群安排）",
         "purpose": "加班事实与时长", "burden": "申请人初步举证；考勤由单位掌握管理的，单位举证",
         "how": "钉钉/企业微信考勤导出、排班表、领导安排加班的聊天记录",
         "required": True, "material_type": "attendance"},
    ],
    "annual_leave": [
        {"key": "leave_record", "name": "年休假记录（请假单、考勤、工资条年假折算）",
         "purpose": "应休天数与已休天数", "burden": "申请人；休假台账在单位",
         "how": "OA 请假记录截图、考勤系统年假余额", "required": True,
         "material_type": "attendance"},
    ],
    "social_insurance": [
        {"key": "si_record", "name": "社保缴纳记录 / 断缴截图",
         "purpose": "未缴、断缴事实与损失金额", "burden": "申请人；缴费记录在社保经办机构",
         "how": "浙里办 → 社保查询 → 参保缴费明细；或社保经办窗口打印",
         "required": True, "material_type": "social_record"},
    ],
    "noncompete": [
        {"key": "noncompete_agreement", "name": "竞业限制协议 / 条款 + 岗位说明",
         "purpose": "是否存在有效竞业限制义务", "burden": "单位主张违约的，由单位举证",
         "how": "劳动合同附件、保密协议、岗位职责说明", "required": True,
         "material_type": "contract"},
    ],
}


def build_materials(types: set[str], has_materials: set[str] | None = None) -> list[dict]:
    has = has_materials or set()
    items = [dict(x) for x in BASE]
    for t in types:
        for x in BY_TYPE.get(t, []):
            if x["key"] not in {i["key"] for i in items}:
                items.append(dict(x))
    for it in items:
        mt = it.get("material_type")
        it["have"] = bool(mt and mt in has)
        if it["key"] == "application":
            it["how"] = "按被申请人人数 +1 份；可现场手抄或打印"
    return items
