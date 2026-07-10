# 文本 7 类情绪（Plan A + 离线模型）

## Plan A：`sentiment_emotion_7`（与 PERCY 采集一致）

VADER 三分类 → `_SENTIMENT_TO_DIST` → argmax 得到 7 类：

| sentiment | 典型 text7 |
|-----------|------------|
| positive | happy |
| neutral | neutral |
| negative | sad（angry/disgust/fear 仅在分布中有权重，argmax 几乎总是 sad） |

采集时 `percy_affect.analyze_user_affect()` 现已写入：

- `sentiment_emotion_7`
- `sentiment_emotion_7_dist`

## 离线模型（批处理，不改历史 JSON 也可）

| 通道 | 脚本列名 | 依赖 |
|------|----------|------|
| vader7 | `text7_vader7` | 仅标准库 + 仓库 `percy_affect` |
| lexicon | `text7_lexicon` | 标准库词典基线 |
| hf | `text7_hf` | `requirements-analysis.txt` |

### 运行

```bash
cd /home/zhijinmeng/Research/paper_writing/Paper_writing/Claude_Writing/analysis

# Plan A + 词典（系统 python3，无需 venv）
python3 text_emotion_7.py --channels vader7,lexicon
python3 cross_modal_7x7.py --channels vader7,lexicon

# HuggingFace（推荐一键脚本；无需 sudo apt，用 --without-pip + get-pip.py）
bash setup_venv_hf.sh
source .venv-analysis/bin/activate
python3 text_emotion_7.py --channels vader7,lexicon,hf
python3 cross_modal_7x7.py --channels vader7,lexicon,hf
```

若坚持 `python3 -m venv`（无 `--without-pip`），需先：`sudo apt install python3.12-venv python3-pip`

### 输出

- `text_emotion_7_labels.csv` — 每 turn 各通道 7 类标签
- `cross_modal_7x7_text7_vader7.csv` — 7×7 列联表
- `cross_modal_7x7_text7_lexicon.csv`
- `cross_modal_7x7_text7_hf.csv`（若跑 hf）
- `cross_modal_7x7_summary.txt`

### Conflict 建议（7×7）

不要用「标签不等」当 conflict（开放域下 ~70%）。

推荐报告：

1. **exact match** — 视觉 7 类 = 文本 7 类（描述性）
2. **both_non_neutral_mismatch** — 两边都不是 neutral 且标签不同（与效价 conflict 同量级）

HF 通道与 vader7 对比可写进论文：离线模型是否比 VADER 展开更能对齐 FER。
