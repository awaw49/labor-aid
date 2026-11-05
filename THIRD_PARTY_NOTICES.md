# 第三方组件与数据来源声明

本项目自身以 MIT 许可发布（见 [LICENSE](LICENSE)）。以下是随仓库分发或运行时依赖的第三方内容，各自保留其原始许可。

## 前端随仓库分发的库（`static/vendor/`）

| 组件 | 版本 | 许可 | 用途 |
|---|---|---|---|
| [html2canvas](https://html2canvas.hertzen.com/) | 1.4.1 | MIT | 报告导出为长图 |
| [jsPDF](https://github.com/parallax/jsPDF) | 2.x | MIT | 报告导出为 PDF |

两者均为 MIT 许可，允许随本项目分发，其许可证文本保留在各自压缩包内的头部注释中。若你要再分发本项目，请一并保留这些声明。

## 运行时依赖（Python，不随仓库分发）

见 `requirements.txt`。主要组件及其许可：

| 组件 | 许可 |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| HTTPX | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| faster-whisper | MIT |
| CTranslate2 | MIT |
| PyAV | BSD-3-Clause |

## 语音模型权重

`faster-whisper` 的 `small` 模型权重来自 [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)，
基于 OpenAI Whisper，MIT 许可。**权重不随仓库分发**（约 500MB），需自行下载到 `models/faster-whisper-small/`。

## 法律数据来源

| 数据 | 来源 | 说明 |
|---|---|---|
| 法条原文（12 部、716 条） | [国家法律法规数据库](https://flk.npc.gov.cn/) 公开 docx | 法律法规文本本身不受著作权保护（《著作权法》第五条），随仓库分发仅用于技术演示；每条均保留 `source` 官方链接 |
| 类案（13 份） | 人力资源社会保障部与最高人民法院联合发布的典型案例（人社部函〔2025〕28 号）、公开裁判文书（已脱敏） | 典型案例为官方公开发布；裁判文书已去除当事人身份信息 |
| 五城口径 | 各市人社局、统计局、仲裁院公开信息 | 见 `data/city/*.json` 的 `source` 与 `verified_on` 字段 |
| 演示材料图 | 本项目自制（`tools/make_materials.mjs`） | 人物、公司、金额均为虚构，不含真实个人信息 |

## 免责

本项目不是律师事务所，不提供法律意见，不代理案件。数据可能滞后于最新法规与地方口径，
使用前请以官方发布为准。详见 README「免责声明」一节。
