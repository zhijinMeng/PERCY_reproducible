# PERCY 本地问卷（替代 Qualtrics）

两个问卷对应 MERCI 原版流程：

| 问卷 | Qualtrics 参考 | 时机 | 产出 |
|------|----------------|------|------|
| **Pre-session** | [SV_9WDNkmzmKyAs1My](https://utsau.au1.qualtrics.com/jfe/form/SV_9WDNkmzmKyAs1My) | 对话**前** | `pre_survey.json` + `profile.json` |
| **Post-session** | [SV_b8cici0YuPnFLuu](https://utsau.au1.qualtrics.com/jfe/form/SV_b8cici0YuPnFLuu) | 对话**后** | `post_survey.json` |

`profile.json` 由 `live_dialogue.py` 读入（persona + 每 3 轮换话题）。

**完整操作说明见**：[`experience/PERCY实时对话与Benchmark采集说明.md`](../experience/PERCY实时对话与Benchmark采集说明.md) 第 3 节。

---

## 推荐：一条命令（宿主机）

```bash
cd ~/Research
# 首次若问卷写不进去：
# sudo chown -R "$(whoami):$(whoami)" ~/Research/percy_data

./run_merci_session.sh 28 audio_gain:=1.2 end_silence_sec:=1.0 vad_mode:=2
```

1. 浏览器：**事前问卷** → Submit  
2. 按终端提示在 **Docker** 里跑 `./record_dialogue_session.sh 28 ...`  
3. 对话结束后回到宿主机终端 → **Enter** → **事后问卷**

选项：`--skip-pre` `--skip-post` `--force-pre`

---

## 分步（等价）

```bash
./run_pre_survey.sh 28          # 事前
# Docker:
./record_dialogue_session.sh 28 audio_gain:=1.2 end_silence_sec:=1.0 vad_mode:=2
./run_post_survey.sh 28         # 事后
```

---

## 产出目录

```
percy_data/<id>/
  pre_survey.json
  profile.json
  post_survey.json
  chat_history.json
  audio.wav
  whole_video.mp4
  ...
```

---

## 修改题目

- `schemas/pre_session.json` — 事前 profile  
- `schemas/post_session.json` — 事后评价（Likert 模板，可按 Qualtrics 改）

`"profile_topic": true` → 进 `profile.json`；`"meta": true` → 仅 `participant_meta`。

---

## 手动起问卷 server

```bash
export PERCY_DATA_DIR=~/Research/percy_data
python3 percy_surveys/survey_server.py --session 28 --mode both
# http://127.0.0.1:8765/?session=28
```
