# 贡献指南

感谢你愿意参与。这个项目的目标是**把劳动仲裁前半段（要不要去仲裁、带什么材料、去哪提交、依据哪几条法）做成可审计、可复现的确定性流程**，所以对"结论从哪来"的要求比一般项目严格。

## 开发环境

要求 Python ≥ 3.11（开发机实测 3.14.7）。

```bash
git clone https://github.com/awaw49/labor-aid.git
cd labor-aid
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

语音功能另需系统 `ffmpeg` 与本地模型权重（约 500MB，不入库，见 README）。不装不影响文字 / 图片链路，也不影响测试。

## 提交前必须跑的三条命令

```bash
.venv/bin/python -m ruff check .          # 静态检查
.venv/bin/python -m pytest tests -q       # 90 条单元 / 接口测试
.venv/bin/python eval/run_eval.py         # 45 条金标准评测，指标不得下降
```

CI 会跑同样三步。**评测指标下降的 PR 不予合并**，除非在描述里说明理由并同步更新 `eval/REPORT.md`。

改动如果涉及前端交互，请按 `测试样例.md` 手动走一遍对应用例，并在 PR 里写明走了哪几条。

## 什么改动受欢迎

- 新增法条（`data/laws/`）、新增城市口径（`data/city/`）、新增类案（`data/cases/`）
- 补测试：优先补 `app/kernel/` 的边界条件与 `app/main.py` 的接口分支
- 修 bug、改善错误提示、补充文档

## 数据类改动的硬要求

这是本项目最容易出错、也最需要把关的部分。

1. **必须给出官方来源**：法条只能来自国家法律法规数据库（flk.npc.gov.cn）等官方渠道，`source` 字段填可点击的原始链接。
2. **必须写核验日**：城市口径（最低工资、社平工资、社保上下限、一裁终局线、仲裁院地址）随时会变，新增或修改时在文件里写 `verified_on`（YYYY-MM-DD）。
3. **不得引入未脱敏的真实案情**：类案只收公开典型案例与已脱敏裁判文书，不得出现真实姓名、身份证号、手机号、公司完整工商信息之外的隐私字段。
4. **优先用脚本生成，而非手抄**：法条走 `tools/flk_fetch.mjs` → `tools/dl_docx.py` → `tools/build_laws.py`，改完跑 `tools/verify_laws.py` 校验条号连续性。
5. **数值不得跨城市混用**：五城各算各的，缺数据就只指路、不给结论。

## 代码约定

- 风格由 `ruff` 统一（配置在 `pyproject.toml`），提交前跑 `ruff format`。
- 注释与文档字符串用中文，与现有代码保持一致；变量名、函数名用英文。
- `app/kernel/` 只做确定性计算，**不得引入网络调用或 LLM**；语义判断留给 `app/needs.py`。
- 新增结论性输出必须有可校验的法条引用，走 `app/report.py` 的校验路径，不允许硬编码结论。

## 提交信息与 PR

提交信息用 `type: 简述` 前缀，例如 `feat: 新增成都社保基数`、`fix: 二倍工资跨月计算`、`docs: 补充 ffmpeg 安装说明`。

PR 描述请包含：改了什么、为什么、如何验证（贴命令与输出）、是否影响评测指标。涉及数据改动时附来源链接。

## 行为准则

参与本项目即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 安全问题

请勿在 issue 中披露漏洞细节，按 [SECURITY.md](SECURITY.md) 的方式私下上报。
