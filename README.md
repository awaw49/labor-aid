# 劳动仲裁初步咨询（京沪广深杭 · 响应式 Web）

[![CI](https://github.com/awaw49/labor-aid/actions/workflows/ci.yml/badge.svg)](https://github.com/awaw49/labor-aid/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-90%20passed-brightgreen.svg)](tests/)

一个只做「劳动仲裁前半段」的初次咨询网页：用户打字、说话、拍照描述案情，系统反向追问补全事实，
最后像接待律师一样给出书面意见——**该不该去仲裁、带什么材料、去哪个窗口/网站提交、依据哪几条法、参考哪几份类案。**

不做代理、不写诉状、不预测胜诉率。

> **它不是律师，输出不是法律意见。** 详见[免责声明](#免责声明)。

```
用户输入（文字 / 语音转写 / 材料照片）
        ↓
事实抽取（LLM，带原文证据） → 用户确认（图片读数必须点头）
        ↓
语义理解层 needs.py（LLM：受案范围问题、身份情形、解除合法性、被迫解除事由）
        ↓
确定性内核（纯 Python，可单测）
  gates.py 三层闸门 · deadline.py 时效 · calc.py 金额 · worth.py 六维值得性
  evidence.py 证据强度 · materials.py 材料清单 · venue.py 立案路径
        ↓
RAG 引用（716 条官方条文 + 13 份类案，条号精确匹配 + BM25，校验不过即降级）
        ↓
四块报告：结论卡 / 材料清单 / 立案路径 / 依据（+ 免责声明）
```

## 为什么值得看

多数法律类 AI 项目的做法是「把法条塞进提示词，让模型自由发挥」。这个项目的取舍相反：

- **能算的不用模型算**。金额、时效、材料清单、立案路径全部落在 `app/kernel/` 的纯函数里，输入输出可枚举、可单测、可复算。
- **模型只做语义判断，且必须给证据**。事实抽取输出原文 quote，图片读数要用户点「对」才进计算。
- **引用只能来自库**。`report._validate_citations` 逐条校验 `law_id:条号`，不存在的直接丢弃；某条结论无有效引用就降级为「需人工咨询」。评测集上幻觉引用率为 0。

## 环境要求

| 项 | 要求 |
|---|---|
| Python | **≥ 3.11**（开发环境 3.14.7，CI 覆盖 3.11 / 3.13） |
| 操作系统 | macOS / Linux 均可；语音功能在 macOS 上另可用系统 Vision OCR |
| ffmpeg | **可选**，仅语音转写需要（`brew install ffmpeg` / `apt install ffmpeg`） |
| 模型权重 | **可选**，约 500MB，不入库，见[语音转写](#语音转写) |
| 模型 API | 需要一个 OpenAI 兼容的 `/v1` 接口；没有也能用 `manual` 模式演示 |

## 快速开始

```bash
git clone https://github.com/awaw49/labor-aid.git
cd labor-aid
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip install -r requirements.txt
./run.sh                                       # 或 .venv/bin/python -m uvicorn app.main:app --port 8787
```

打开 http://127.0.0.1:8787 ，手机同网段可用脚本打印的局域网地址访问。
接口文档在 http://127.0.0.1:8787/docs （FastAPI 自动生成）。

`run.sh` 会自动选 `.venv/bin/python`，没有就用系统 `python3`，并适配 macOS / Linux 的取 IP 方式。

### 配置模型 API

**密钥不进代码，仓库里也不带默认端点**——首次启动 `base_url` 为空，必须自己填。

三种方式，任选其一：

1. 页面右上角「设置」里粘贴 `base_url` / `api_key` / 模型名，保存立即生效，不用重启（存 `data/settings.json`，该文件已列入 `.gitignore`）。
2. 环境变量：`export LABOR_AID_API_KEY=sk-...`
3. 复制 `.env.example` 为 `.env` 并填写，启动时自动读取。

`base_url` 要填 OpenAI 兼容的 `/v1` 地址（形如 `https://your-host/v1`）。模型名默认 `deepseek-flash` / `deepseek-v4.1-flash`，可在设置页改成你用的模型。

### 没有可用 key 时：manual 模式

设置页把 `mode` 切到 `manual`，程序不调远端，而是把完整请求写到 `data/manual_llm/req_*.json`；
你（或另一个模型）把答复写成同名的 `resp_*.txt`，链路继续。用于演示「语义理解层到底收到了什么、答了什么」，
也用于在没有密钥的环境里跑通全流程。图片在应答写回后立即删除。

## 使用示例

**输入**（底部输入框 / 🎤 语音 / ＋ 拍照或相册）：

> 我 2025 年 6 月 1 日入职，做运营，月工资 8600。今年 3 月 14 日 HR 微信说业务调整岗位取消，明天不用来了。没签合同，也没提前通知。

**系统会做的事**：抽取事实 → 对不上号的地方追问（一次只问一件）→ 图片读数要你确认 → 算时效与金额 → 给四块报告。

**输出**：结论卡（建议去仲裁 / 先协商 / 不建议，附理由与可信度）、材料清单（按优先级，标明有/缺）、
立案路径（哪个仲裁院、地址电话、线上入口）、依据（法条原文摘录 + 类案要点 + 可比/不可比点）。

`data/materials/` 里有 4 张虚构的演示材料（录用通知、工资条、HR 微信、银行流水），可直接上传体验
「图片读数 → 用户确认 → 进计算」的完整链路。截图见 `docs/screenshots/`。

## 数据来源（可回溯）

| 数据 | 来源 | 规模 |
|---|---|---|
| 法条原文 | 国家法律法规数据库 flk.npc.gov.cn 官方 docx（抓取脚本 `tools/flk_fetch.mjs`） | 12 部、**716 条**，含条号/章/施行日期/官方链接 |
| 类案 | 人社部+最高法第四批典型案例（人社部函〔2025〕28号）、2025 年公开裁判文书（脱敏） | 13 份，带争议焦点/要旨/可比点/不可比点 |
| 五城口径（京/沪/广/深/杭） | 各城市 2026 年最低工资、社平工资、社保基数上下限、一裁终局线、仲裁院地址电话 | `data/city/*.json`（5 份，各城市各算各的），核验日 2026-11-04 |

其中《最高人民法院关于审理劳动争议案件适用法律问题的解释（二）》（2025-09-01 施行）已入库，
二倍工资按月计算、竞业限制主体、混同用工、时效抗辩等新规则都在内核里用上了。

法条原文抓取：`node tools/flk_fetch.mjs tools/lawlist.json data/raw/flk_meta.json`，
再 `python3 tools/dl_docx.py && python3 tools/build_laws.py` 重新生成 `data/laws/*.json`，
用 `python3 tools/verify_laws.py` 校验条号连续性。

授权与第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 三个硬规则（不是提示词，是代码）

1. **图片读数未经确认不进计算**：视觉模型输出 `suspects`，Python 逐项回查本机 OCR 原文（`verify_structured`），
   对不上就丢；剩下的以「疑似值」进 `session.suspect`，用户点「对」才写入槽位并标记 `image_confirmed`。
2. **口述与图片冲突必须回问**：`main.py` 检测同槽位不同值 → 返回 conflict 消息，不擅自择一；用户选完才更新。
3. **引用只能来自库**：`report._validate_citations` 校验每个 `law_id:条号`，不存在的丢弃；若某条结论无有效引用，
   结论自动降级为「需人工咨询」。

## 测试与评测

```bash
.venv/bin/pip install -r requirements-dev.txt   # 含 pytest / pytest-cov / ruff
.venv/bin/python -m ruff check .                # 静态检查
.venv/bin/python -m pytest tests -q             # 90 条单元 / 接口测试
.venv/bin/python eval/run_eval.py               # 45 条金标准评测（不需要 LLM）
```

**90 条测试全部通过，耗时 <1 秒**。`tests/conftest.py` 有一层全局兜底：任何用例误触模型调用都会立刻抛
`LLMError` 走降级分支，而不是等 120 秒网络超时——所以 CI 不需要任何 API key。

行覆盖率（`pytest --cov=app`）：**整体 66%**。确定性内核是重点：

| 模块 | 覆盖率 |
|---|---|
| `kernel/materials.py` 材料清单 | 100% |
| `kernel/gates.py` 三层闸门 | 99% |
| `kernel/evidence.py` 证据强度 | 97% |
| `kernel/venue.py` 立案路径 | 96% |
| `kernel/deadline.py` 时效 | 94% |
| `kernel/worth.py` 值得性 | 88% |
| `kernel/calc.py` 金额 | 87% |
| `report.py` 报告与引用校验 | 96% |

`extract.py`（24%）、`needs.py`（23%）、`asr.py`（32%）、`ocr.py`（35%）偏低，因为它们的主体是提示词与
外部调用，测试里被替换掉了；这部分靠 `manual` 模式 + 真实模型人工验证。

金标准评测集 45 条第一人称口语故事，每条都写了「为什么」（`eval/cases.jsonl` 的 `gold.why`）：

| 指标 | 结果 | 目标 |
|---|---|---|
| 受案范围 / 资格 / 两层全对 | 100% / 100% / 100% | >90% |
| 结论三选一 | 100% | >85% |
| 时效起算 + 剩余天数 | 100% | — |
| 材料清单召回 | 97.1% | >85% |
| 立案路径 | 100% | >90% |
| 法条引用召回 / 精确 | 100% / 100% | >80% / >85% |
| 幻觉引用率 | **0** | 0 |
| 未确认字段拦截 | **100%**（探针：未确认 999999 不进计算，确认后生效） | 100% |

完整报告见 `eval/REPORT.md`，可用 `eval/build_cases.py` 重新生成评测集。

## 验收样例

`测试样例.md` 是给验收/答辩用的操作手册：9 条主用例 + 4 条交互专项，每条都写了可以直接复制的原话、
要上传哪张图、点哪个按钮、应该看到什么结论与金额，以及常见偏差怎么处理。

```bash
./run.sh     # 先起服务，再照着文档点
```

`演示脚本.md` 是同一套用例的口播版，适合现场演示。

## 文件地图

```
app/
  main.py        HTTP 接口（会话/文字/语音/图片/确认/报告/抗辩预演/法条/设置）
  extract.py     文字与图片抽取、年份补全、原文核对、规则兜底解析
  needs.py       语义理解层（受案范围问题 / 身份情形 / 解除合法性 / 38 条事由）
  followup.py    追问策略（一次一条、每槽最多 2 次、跳过机制、话术）
  report.py      四块报告组装 + 引用校验 + 可信度
  kernel/        gates / deadline / calc / worth / evidence / materials / venue
  rag/           法条与类案检索、条号精确匹配、按争议类型选条文
  asr.py         faster-whisper 本地转写（ffmpeg 解码，临时文件即删）
  ocr.py         macOS Vision 离线 OCR（视觉模型不可用时兜底，也用于核对 quote）
data/
  laws/          716 条官方条文（12 部，每部一个 json）
  cases/         13 份类案
  city/          五城口径（京 / 沪 / 广 / 深 / 杭，各城市各算各的）
  slots.json     槽位表（前后端共用）
  materials/     演示用模拟材料（录用通知 / 工资条 / 聊天记录 / 银行流水）
eval/            45 条评测集 + runner + 报告
static/          移动端单页（首页 / 对话 / 报告 / 法条库 / 设置，PDF 与长图导出，PWA）
tests/           90 条测试
tools/           flk 抓取/解析/校验、材料生成、Vision OCR 源码
docs/            截图
```

## 语音转写

用本地 faster-whisper `small` 模型，离线，2–4 秒/10 秒音频。权重不入库：

```bash
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='models/faster-whisper-small')"
```

也可以从 Hugging Face 手动下载后解压到 `models/faster-whisper-small/`。没装模型不影响文字/图片链路，
点语音时页面会明确报错，而不是假装成功。系统需有 `ffmpeg`。

## 隐私与边界

- 图片与录音只在内存/临时文件里，处理完即删；会话结束不留原图原音；导出报告只含已确认事实。
- 不存储、不用于训练；`data/manual_llm/` 里的图片在应答写回后立即 `unlink`。
- 金额口径覆盖北京、上海、广州、深圳、杭州五城，各城市按自己的口径算；五城之外只指路不给结论，
  不冒用任何城市的数字。社保补缴、公积金、工伤认定、在编人事争议、刑事问题一律指路，
  不给结论、不作定性。
- 页面常驻「不是律师意见」+ 12348。
- **本项目默认按「本机 / 可信内网演示」设计**：`run.sh` 监听 `0.0.0.0` 且**无身份认证与限流**。
  要部署到公网，请自行在前面加认证、限流与 HTTPS，参见 [SECURITY.md](SECURITY.md)。

## 已知限制

- 金额（N/2N/二倍工资/加班费/年假）只作「标的额」与值得性参考，不是"能拿多少"的承诺。
- 二倍工资按「按月计算时效」处理（与 2025 年司法解释（二）后的主流裁判一致），但各地口径仍有差异，报告中已标注。
- 视觉模型对模糊照片会明确说读不清并要求补拍；识别方式（视觉模型 / 本机 OCR + 规则）会显示在对话里。
- 评测的「结论三选一」是确定性内核在金标准事实上的表现；口述→槽位抽取质量需要真实模型，
  接口测试用固定返回替换了模型，真实抽取效果请在页面上用真实 key 验证。
- 请求体里带了 `thinking: {"type": "disabled"}` 这一非标准参数（用于关闭部分推理模型的思考过程）。
  若接的是严格校验的 OpenAI 端点，可能返回 400，此时把 `app/llm.py` 里该字段删掉即可。
- 城市数据核验日为 2026-11-04，最低工资与社保基数每年调整，长期使用请重新核验。

## 参与贡献

欢迎补法条、补城市口径、补测试。动手前请读 [CONTRIBUTING.md](CONTRIBUTING.md)，
参与即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下上报。

## 许可证

本项目以 [MIT 许可证](LICENSE) 发布，可自由使用、修改、分发，包括商业用途，需保留版权与许可声明。

随仓库分发的第三方前端库（html2canvas、jsPDF）同为 MIT；法条来自官方公开文本，类案为公开典型案例与脱敏裁判文书。
逐项说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 免责声明

本项目是技术演示，**不是律师事务所，不提供法律意见，不构成委托关系**。

- 输出内容仅供参考，不能替代执业律师针对具体案情出具的意见。
- 法条与地方口径可能滞后于最新规定，使用前请以官方发布为准。
- 金额为标的额估算，不代表实际可得金额，也不预测裁判结果。
- 因使用本项目产生的任何后果，作者不承担责任。

需要正式法律帮助，请拨打 **12348** 法律援助热线，或咨询当地劳动人事争议仲裁委员会。

## 致谢

- 法条文本来自[国家法律法规数据库](https://flk.npc.gov.cn/)
- 类案来自人力资源社会保障部与最高人民法院发布的典型案例
- 语音识别基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 与 OpenAI Whisper
- Web 框架为 [FastAPI](https://fastapi.tiangolo.com/)
