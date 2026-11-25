# scholarly-paper-translator · 科研文献翻译 Skill

面向「阅读03｜文献翻译」：把一篇（或一个页码/段落区间的）科研文献翻译成**可核验的双语对照结果**。译文由模型完成，
凡是「必须确定、可以复核」的事情都交给脚本：分段与稳定段号、哪些块**不译**、术语锁定与逐处核对、数字/单位/引用/图表公式编号/
标识符/否定与限定词是否保留、分批续译与上下文携带、预算内的批次规划、双语对照与人工复核清单。

> 文中的数字都来自我的开发自测（虚构示例 + 一篇公开论文的 35 个真实段落，由开发者本人通过本工具翻译），**不是平台成绩**，
> 也没有与「不加载 Skill 的模型」做过对照，因此不宣称相对基线的提升。

## 对应题面的四个问题
| 题面问题 | 做法 | 自查手段 |
|---|---|---|
| 术语稳 | 术语表（题面提供 + 译前一次性决定 + 译中新增的临时术语）全部锁定；每个批次卡只带本批出现的术语；逐段核对锁定译名与 `avoid` 禁用译法；`check` 用**最终**术语表回头复核全文 | 术语一致率（`check_report.json`）、`review_checklist.md` 术语表 |
| 段落全 | 稳定段号 `S001…`；批次规划；可续跑状态；段落通过检查才算完成；漏译/重复/失败段逐条列出；未全部完成时结果只能是 `partial` | `check`：missing / duplicates / sentence_alignment |
| 关系准 | 公式、参考文献条目、页眉页脚由工具原样复制或剔除，不交给模型；数字、单位、引文、图表公式章节编号、标识符、URL、数学符号必须原样出现；否定、让步、因果、上下限等线索逐项对照 | 即时 ERROR/WARN；植入错误评测 |
| 可核验 | 每段带段号、页码、bbox、解析块 id；`[n]` 句级对齐；`note:` / `flag=uncertain` 通道标注译不准处；每行 `basis`；人工复核清单 | `bilingual.md/html`、`alignment.json` |

## 目录
```
SKILL.md                         Agent 入口：何时用、步骤、块格式、译法规则、异常处理
README.md                        本文件
scripts/tr.py                    命令行：prepare / glossary / next / ingest / check / assemble / status
scripts/tlib.py                  句子切分、不变量提取、术语匹配、线索规则（纯标准库）
scripts/parse_pdf.py             PDF 解析（来自 scholarly-pdf-parser v1.0.0，含 OCR 接入与一处重复片段修复）
references/checks.md             每项检查的规则、严重度、实测检出率与盲区
references/glossary-format.md    术语表格式与匹配规则
references/output-schema.md      工作目录与输出文件字段、result.json 推导规则
references/failure-modes.md      故障现象 → 处置
references/method-notes.md       设计依据、预算模型、已知限制
examples/                        虚构示例论文、术语表、示例译文（块格式）、最小调用示例、虚构契约
GITHUB_URL.txt                   作品的 GitHub 公开链接
```

## 依赖与安装
- Python 3.8+，翻译流程只用标准库。
- PDF 输入使用自带的 `scripts/parse_pdf.py`，需要 `pymupdf`（可回退 `pdfplumber` / `pypdf`）；扫描件需要 OCR：
  `pip install rapidocr`（模型已打包，运行时不联网，中英文）或 `tesseract` 命令行。
- `.docx`（段落、标题、简单表格、公式占位）、`.md` / `.txt` / `.tex` / `.json` 无需额外依赖。
- 版本与来源：均为 PyPI 官方包；开发环境 Python 3.11、pymupdf 2.1、rapidocr 3.10。

## 使用步骤
```bash
python3 scripts/tr.py prepare paper.pdf --work W [--case /input/case.json] [--glossary g.tsv] [--tgt zh] [--pages 3-5]
python3 scripts/tr.py glossary W --add "attention head => 注意力头"       # 译前一次性定术语
python3 scripts/tr.py next W                                              # 取下一批卡片
python3 scripts/tr.py ingest W < translation_block.txt                    # 提交该批译文，立即校验（也可用 heredoc）
python3 scripts/tr.py next W --fix                                        # 只看出错的段落
python3 scripts/tr.py check W                                             # 全文复核
python3 scripts/tr.py assemble W --out out --case /input/case.json        # 双语对照 + 清单 + result.json
```
译文提交格式（块格式，无需 JSON 转义）：
```
=== S012
[1] 第一句译文
[2] 第二句译文
note: 对某处译法不确定的说明（可选）
terms: 新术语 => 译名（可选，之后全文锁定）
```
完整示例（真实运行输出）见 `examples/minimal-example.md`。

## 输出
`translation.md`（译文全文，未译段落明确标 `[[NOT TRANSLATED]]`）· `bilingual.md` / `bilingual.html`（段落与句子对照）·
`alignment.json`（段号、页码、bbox、原文、译文、句级对齐、状态、依据）· `glossary.json` · `review_checklist.md` ·
`check_report.json` · `result.json`（契约字段 + `case_id` + `status` + `sources` + `uncertainty` + `change_records`；
推导不出的字段置 `null` 并列出，不编造）。

## 实测（开发自测，非平台成绩）
对正确译文**逐个植入一种错误**，用 `ingest` 同一套校验检测（`dev/seeded_errors_eval.py`；虚构论文 23 段 / 真实论文 35 段）：

| 植入的错误 | 检出（任一提示）虚构 / 真实 | 错误级检出 虚构 / 真实 |
|---|---|---|
| 删数字 / 改数字 | 100 % / 100 % | 88 % / 96 % |
| 删引文 | 100 % / 100 % | 100 % / 100 % |
| 术语换成别的译法 | 100 % / 83 % | 100 % / 61 % |
| 删图表/章节引用 | 100 % / 100 % | 100 % / 100 % |
| 删模型名/标识符 | 100 % / 85 % | 100 % / 85 % |
| 删 URL/DOI | 100 % / 100 % | 100 % / 100 % |
| 删否定词 | 100 % / 67 % | 0 %（设计为警告） |
| 删限定/上下限 | 60 % / 75 % | 0 %（设计为警告） |
| 整段未翻译 | 92 % / 100 % | 92 % / 100 % |
| 漏最后一句（有 `[n]`） | 100 % / 100 % | 100 % / 100 % |
| **意思反转（降低→升高）** | 0 % / 50 % | 0 % / 0 % |

对正确译文：错误级误报 0；每次运行有 1–2 条合理警告。意思反转是规则检查的**盲区**（见 `references/checks.md`）。

## 已知限制
- 检查是规则式的：看不到「意思被反转」「指代对象错」「因果方向反」，也看不到术语表之外的不一致译法。
- 否定/限定线索检查只覆盖英→中；其他语言对只做与语言无关的检查。
- 未在评测模型（DeepSeek）和真实预算下实跑；未测英中之外的语言、超过 30 页的长文全流程、含图片/文本框的 Word。
- PDF 质量决定上限：扫描件依赖 OCR；图片形式的公式/表格不在文本层中；复杂表格为启发式重建。
- 速度/批次估计是假设值（40 tokens/s、每批 20 s 开销），不是实测。

## 版本与维护
`tr.py` 1.0.0 · 问题与改进请在 GitHub 仓库提 issue。


## 示例文件的后缀
平台只接受部分文件类型作为 Skill 资源，所以示例里这些文件的名字后面加了 `.txt`：`examples/glossary.tsv`。去掉 `.txt` 就是脚本实际读写的文件名；脚本本身的输出文件名没有变。
