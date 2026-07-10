# percy_data 全量复算（30 sessions）

**数据根目录：** `Research/percy_data/`（`PERCY_DATA_ROOT`）

| 子集 | Sessions | User labelled | Conflict | Conflict % |
|------|----------|---------------|----------|------------|
| 时间戳命名（`fixed_data/Ari Robot/`） | 25 | 753 | 108 | **14.3%** |
| 编号 `100`–`104` | 5 | 165 | 7 | 4.2% |
| **合计（论文口径）** | **30** | **918** | **115** | **12.5%** |

**对话规模：** 919 user + 927 assistant = **1846** messages（≈ CBMI 1860 utterances）

**延迟（Δt）：** 866 scanned → 223 excluded → **643 clean**；median **3.31 s**，IQR **[1.75, 5.18] s**（29 sessions 至少 1 个 clean pair）

**复算命令：**

```bash
cd paper_writing/Paper_writing/Claude_Writing/analysis
python3 cross_modal_consistency.py
python3 response_latency.py
python3 turn_accounting.py
# 需 pandas/matplotlib：
python3 plot_merci_figures.py
```

`main.tex` 已按 **30 sessions** 更新。旧稿数字（753 / 14.3% / 479）仅覆盖 25 个时间戳 session，未含 `100`–`104`。
