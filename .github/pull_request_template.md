## 改了什么

<!-- 一句话概括；关联 issue 请写 Closes #123 -->

## 为什么

## 如何验证

<!-- 贴命令与关键输出 -->

```bash
ruff check .
pytest tests -q
python eval/run_eval.py
```

## 检查清单

- [ ] 三条命令本地全部通过
- [ ] 评测指标未下降（若下降，已在下方说明理由并更新 `eval/REPORT.md`）
- [ ] 涉及前端交互时，已按 `测试样例.md` 手动走过对应用例
- [ ] 涉及数据（法条 / 城市 / 类案）时，已附官方来源链接与核验日期
- [ ] 未提交任何 API key、`data/settings.json`、模型权重、真实案情材料
- [ ] 新增或修改的行为已同步到 README / CHANGELOG
