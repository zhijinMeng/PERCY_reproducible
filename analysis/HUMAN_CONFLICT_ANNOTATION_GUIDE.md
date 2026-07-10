# MERCI 人工 Conflict 标注 — 操作说明与 To-Do

**项目：** MTAP 期刊扩展稿（CBMI 2025 MERCI）  
**论文章节：** §4.1 *Human Validation of the Conflict Rule*（`main.tex`）  
**负责人：** [填写你的名字]  
**对接人：** Zhijin Meng — [填写邮箱/微信]

---

## 1. 你要做什么（一句话）

判断：**在这一轮用户说话时刻**，机器人摄像头里看到的**面部表情**和用户**说的话**所表达的情绪/语气，是否让普通人感觉**互相矛盾**。

输出：每个 turn 一个二值标签 `human_conflict`（是/否），以及汇总统计填进论文 Table 3–4。

**你不负责：** 跨库 benchmark、改 §3 的图、全文 Related Work。

**你负责（建议交付）：**

| 交付物 | 说明 |
|--------|------|
| `human_conflict_annotations.csv` | 主标注结果（见 §6 格式） |
| `human_conflict_protocol.pdf` 或 `.md` | 给标注员的简短说明（可从本文 §3 改） |
| `human_conflict_results.md` | κ、P/R/F1、混淆矩阵数字 + 2–3 段英文草稿（§4.1 用） |
| （可选）帮填 `main.tex` 里 Table 3–4 的 Result 列 | 与 Zhijin 对齐后合稿 |

---

## 2. 背景（读 5 分钟即可）

- **MERCI：** 30 名参与者与 ARI 社交机器人（PERCY）真实对话；每轮用户 turn 记录了视觉 FER 表情 + VADER 文本情感。
- **自动 conflict 规则（论文 §3）：** 价态相反才算 conflict，例如：
  - 脸偏 **开心**，文本 **负面**；或
  - 脸偏 **悲伤/愤怒/厌恶/恐惧**，文本 **正面**。
  - 任一侧为 **neutral** → **不算** 自动 conflict。
- **为什么要人工标：** 审稿人会问「自动标的 conflict，人是否也觉得很拧巴？」—— 你的标注就是回答这个问题。

**关键原则：标注时不要看自动 conflict 标签。** 材料里可以事后用 `auto_conflict` 列对齐，但标注界面不要显示「系统已判 conflict」。

---

## 3. 标注任务定义

### 3.1 问题（每个 turn 只答这一个）

> **At this user turn, do the facial expression (in the clip/frame) and what the user said feel emotionally contradictory?**

中文理解：**这一瞬间，脸和话在情绪上是否「拧巴」？**

- **Yes → `human_conflict = 1`**
- **No → `human_conflict = 0`**

### 3.2 看什么

| 材料 | 用途 |
|------|------|
| **用户转写文本** | 理解语义与语气（讽刺、抱怨、开玩笑等） |
| **短视频或关键帧** | 看机器人头摄/外摄里用户面部（与采集一致即可） |
| **时间对齐** | 用 `t_start_sec` / `t_end_sec` 截取该 user turn 附近 2–5 秒 |

**不需要：** 看机器人回复、融合标签 `affect_fused`、VADER 分数、自动 conflict 字段。

### 3.3 判定提示（减少歧义）

**标 Yes（conflict）的典型情况：**

- 笑着说难过的事，或面无表情/悲伤脸说明显开心、兴奋的话（**脸与话语情绪方向相反**）。
- 脸与**话语内容**明显不一致（不限于 Ekman 七类名是否相同）。

**标 No（not conflict）的典型情况：**

- 脸和话情绪方向一致（都偏正、都偏负、都中性）。
- 一侧很弱/看不清脸 → 若**无法判断脸**，标 No，并在 notes 写 `face_unclear`。
- 纯中性闲聊、信息问答、无明显情绪 → 一般标 No。
- **讽刺/玩笑**但脸和话「配套」（例如笑着开玩笑）→ 通常标 **No**；若脸开心但话在认真表达痛苦 → 标 **Yes**。

**不要做的事：**

- 不要因为 VADER 标了 negative 就标 Yes —— 以**你读到的语气**为准。
- 不要数 Ekman 类名是否一致（那是 §3 另一套规则）。
- 不要标「机器人表情是否合适」—— 只标**用户**脸 vs **用户**话。

### 3.4 与自动规则的关系（标注后才会用到）

自动规则见 `export_cross_modal_per_session.py` 里 `valence_conflict()`，或论文 §3 `sec:cross-modal-defs`。

论文 Table 3 行 = 自动规则，列 = 你的人工金标：

|  | Human: No | Human: Yes |
|--|-----------|------------|
| Auto: conflict | FP | **TP** |
| Auto: not conflict | **TN** | **FN** |

---

## 4. 抽样方案（与论文一致）

**目标总量：** **150–200** 个 user turns（论文 Planned 列）。

**推荐分层：**

| 层 | 数量 | 来源 |
|----|------|------|
| **A. 自动 conflict** | **全部 115** 或随机 **80–100** | `analysis/cross_modal_conflict_turns.csv` |
| **B. 对照 non-conflict** | 与 A **1:1** | 同 session 的 user turns，且 `auto_conflict = 0`，有 FER+VADER |
| **合计** | **150–200** | |

**对照抽样注意：**

- 尽量覆盖多个 `session_id`，不要只标 1–2 个 session。
- 排除 user turn 缺 `emotion_visual` 或 `sentiment` 的条目。
- 可优先选「非 neutral 脸 + 非 neutral 文本」的对照（更难、更有判别力），但不必 100% 如此。

**双人标注：**

- 至少 **20%** 样本（≥30 条）由 **两名标注员独立** 标。
- 报告 **Cohen’s κ**（或 Fleiss κ，若 3 人）。
- 不一致项由 **第三人裁决**（或两人讨论后定 gold），`adjudicated = 1`。

---

## 5. 推荐工作流程

### Phase 0 — 准备（Zhijin 提供）

- [ ] 数据路径：`percy_data/`（含 `fixed_data/`、`100`–`104` 等 session 文件夹）
- [ ] 每 session 的 `chat_history.json` + 对齐视频（头摄或外摄，约定一条）
- [ ] 本仓库 `analysis/cross_modal_conflict_turns.csv`（115 条 conflict 清单）

### Phase 1 — 建标注包

- [ ] 运行抽样脚本（默认排除无 mp4 的 2 个 session）：

```bash
export PERCY_DATA_ROOT=/home/zhijinmeng/Research/HF_Data/percy_data
cd analysis
python3 build_human_conflict_sample.py --n-total 180 --seed 42
python3 build_human_conflict_sample.py --extract-clips --clips-dir human_conflict_clips/
```

  产出：`human_conflict_sample.csv`（含 `turn_id`, `transcript`, `video_path`, `clip_*_sec`；**勿**把 `emotion_visual`/`sentiment` 给标注员）

- [ ] **隐藏** `auto_rule_pred`、FER、VADER（标注界面只显示 `turn_id` + 转写 + clip）
- [ ] 选工具：**Label Studio** / Google Sheet + 本地视频 / 简单 HTML 翻页（三选一即可）

### Phase 2 — 试点

- [ ] 先标 **10 条**（5 conflict + 5 control），与 Zhijin 对一下标准
- [ ] 更新 `human_conflict_protocol` 里的 2–3 个边界案例

### Phase 3 — 正式标注

- [ ] 完成 150–200 条单人标注
- [ ] 完成 ≥20% 双人标注 + 裁决
- [ ] 每条记录 `annotator_id`、`annotation_time`（可选）

### Phase 4 — 统计与写 §4.1 草稿

- [ ] 合并为 adjudicated gold（一人标完的用该人；双人冲突用裁决结果）
- [ ] 运行汇总：

```bash
python3 summarize_human_conflict.py human_conflict_annotations.csv -o human_conflict_results.md
```

- [ ] 把 `human_conflict_results.md` 里的数字填入 Table 3–4
- [ ] 写 **英文** 2–3 段：样本量、κ、P/R/F1、规则偏保守还是偏松（见 §7 模板）

---

## 6. 输出 CSV 格式（必须遵守）

**文件名：** `analysis/human_conflict_annotations.csv`

| 列名 | 类型 | 说明 |
|------|------|------|
| `session_id` | str | 如 `00_00_00_04_07_00_00` |
| `turn_index` | int | user turn 编号（与 `chat_history.json` 一致） |
| `auto_conflict` | 0/1 | 自动规则（**事后填入**，标注时不可见） |
| `human_conflict` | 0/1 | 人工金标（裁决后） |
| `annotator_id` | str | 如 `A`, `B`, `adjudicated` |
| `adjudicated` | 0/1 | 1 = 最终 gold |
| `notes` | str | 可选：`face_unclear`, `sarcasm`, `asr_bad` 等 |

**双人标注时：** 可另存 `human_conflict_annotations_raw.csv`（每人一行），再汇总到上表。

---

## 7. 统计公式（填表用）

在 **分层抽样** 的 150–200 条上（不是全语料 918 条）：

- **Precision** = TP / (TP + FP)  
- **Recall** = TP / (TP + FN)  
- **F1** = 2PR / (P + R)  
- **Human-positive rate** = (TP + FN) / n  

**κ：** 仅在双人子集上，比较两名标注员 **裁决前** 的 `human_conflict`。

**解读（写进 §4.1）：**

- Precision > Recall → 自动规则偏**保守**（报的 conflict 里人多认同，但漏了一些人觉得 conflict 的）。
- Recall > Precision → 自动规则偏**松**（报得太多）。
- κ 0.4–0.6 = moderate；≥0.6 = substantial（按 Landis & Koch 常用分界，文中可一句带过）。

---

## 8. §4.1 英文草稿模板（你填 [括号]）

**Paragraph 1 — Design**  
We stratified-sampled [N] user turns from MERCI: [n_c] from the automatic valence-conflict stratum and [n_nc] matched controls. Annotators saw the user transcript and a short aligned video clip and judged binary `human_conflict` without access to channel labels. At least 20% ([n_double]) received double annotation; disagreements were adjudicated by [method].

**Paragraph 2 — Agreement**  
Cohen’s κ on the double-annotated subset was [κ] ([CI optional]), indicating [moderate/substantial/...] agreement on perceived face–text contradiction.

**Paragraph 3 — Rule vs human**  
Against adjudicated human gold, the deployed valence-conflict rule achieved precision [P], recall [R], and F1 [F1] (Table [X]). The human-positive rate in this sample was [rate]. [One sentence: conservative vs liberal vs weak alignment.]

---

## 9. To-Do 清单（可打印勾选）

### 必须完成（投 MTAP 最低线）

- [ ] 与 Zhijin 确认数据与视频路径、伦理/隐私要求（仅组内标注）
- [ ] 构建 150–200 条标注任务包（含 conflict + 对照）
- [ ] 撰写 1 页 Annotator Instructions（英或中英）
- [ ] 10 条试点 + 标准对齐
- [ ] 完成全部单人/双人标注与裁决
- [ ] 导出 `human_conflict_annotations.csv`
- [ ] 计算 κ、TP/FP/FN/TN、P/R/F1、human-positive rate
- [ ] 把数字发给 Zhijin 填 Table 3–4，或自行改 `main.tex` 对应表
- [ ] 提交 §4.1 英文草稿（§8 模板）

### 建议完成（加分）

- [ ] 记录平均标注时长、剔除标准（脸看不清比例）
- [ ] 2–3 个 illustrative examples（可放 appendix 或回复审稿人）
- [ ] 简单脚本 `analysis/summarize_human_conflict.py` 从 CSV 生成 LaTeX 表行

### 不要做

- [ ] 不要在标注界面显示自动 FER/VADER/conflict
- [ ] 不要改 §3 的 conflict 定义（有意见先和 Zhijin 讨论）
- [ ] 不要承诺扩到 40 人新采集（那是 Future work）

---

## 10. 参考文件路径

| 文件 | 路径 |
|------|------|
| 论文主稿 | `paper_writing/Paper_writing/Claude_Writing/main.tex`（§4.1, Table 3–4） |
| 115 条自动 conflict 列表 | `analysis/cross_modal_conflict_turns.csv` |
| 4.1 抽样清单 | `analysis/human_conflict_sample.csv`（`build_human_conflict_sample.py`） |
| 4.1 汇总填表 | `analysis/summarize_human_conflict.py` → `human_conflict_results.md` |
| 自动规则代码 | `analysis/merci_valence_rules.py`（与 `export_cross_modal_per_session.py` 一致） |
| 投稿清单 | `MTAP_REVISION.md` §「人工 conflict」 |
| 产物说明 | `analysis/PLACEHOLDER_README.md` |

**数据根目录（示例）：** `/home/zhijinmeng/Research/percy_data/`

---

## 11. 时间建议（与 Zhijin 可改）

| 阶段 | 建议时长 |
|------|----------|
| 准备 + 试点 | 2–3 天 |
| 正式标注（150–200 条） | 3–5 天（视视频加载与人数） |
| 统计 + §4.1 草稿 | 1–2 天 |
| **合计** | **约 1–2 周**（兼职） |

---

## 12. 有问题找谁

- **抽样、视频、字段含义：** Zhijin  
- **论文叙事、Table 编号：** Zhijin / Mohammed（Intro/Related）  
- **伦理：** 论文写明 iRECS4630；标注数据勿外传公网

---

*文档版本：2026-05-26 — 与 `main.tex` §4.1 同步*
