# MERCI

Repository for the **MERCI** corpus (Multimodal dataset for Emotionally-aware peRsonalised Conversational Interactions) and related tooling.

| Resource | Link |
|----------|------|
| Dataset | https://huggingface.co/datasets/zhijin-meng/MERCI-plus |
| PERCY (dialogue stack) | https://github.com/zhijinMeng/PERCY |
| Paper | Extended CBMI 2025 → MTAP special issue |

## Analysis & benchmarks (`analysis/`)

Audit scripts, human conflict validation (§4.1), indexing benchmarks A/B/C, and cross-corpus transfer (§4.5) for the MTAP extended article.
Reproducibility specifications match **Appendix A** of the journal manuscript.

See [`analysis/README.md`](analysis/README.md) for setup (`NORMALIZED_MEDIA_ROOT`), hyperparameters, and full reproduction commands.

```bash
cd analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export NORMALIZED_MEDIA_ROOT=/path/to/normalized_media
python run_downstream_benchmarks.py          # Benchmarks A & B
python run_affect_retrieval_benchmark.py     # Benchmark C
python run_cross_corpus_merci_meld.py        # Table 6 (LogReg)
python run_cross_corpus_merci_meld_roberta.py
```

Figure 2 (dataset sample gallery): [`scripts/figures/build_fig_dataset_samples.sh`](scripts/figures/build_fig_dataset_samples.sh)

## Robot-side recording bundle (legacy layout)

This repo also contains a **PERCY reproducible** deployment bundle: timestamp-aligned A/V recording (`percy_ws`) and LLM dialogue stack (`PERCY/`).

### Layout

- `percy_ws/` — Catkin workspace with `percy` (stamp-aligned recorder, H.264 post-process)
- `PERCY/` — Catkin workspace with dialogue / GPT packages
- `docker/`, `docs/` — optional laptop + Docker workflow

### On the ARI robot (Ubuntu 20.04 + ROS Noetic)

```bash
git clone git@github.com:zhijinMeng/MERCI.git
cd MERCI

sudo apt-get update
sudo apt-get install -y ffmpeg ros-noetic-audio-common-msgs python3-pip python3-opencv

pip3 install openai pandas

cd percy_ws && catkin_make && source devel/setup.bash
cd ../PERCY && catkin_make && source devel/setup.bash

export PERCY_DATA_DIR=~/percy_data
mkdir -p "$PERCY_DATA_DIR"
export OPENAI_API_KEY="your-key"

roslaunch percy record_aligned.launch session_id:=0
roslaunch chatting_system start.launch id:=0
```

Use `ROS_MASTER_URI=http://localhost:11311` when running entirely on the robot. See `docs/DOCKER_ROS1.md` for laptop + Docker recording.

## Citation

If you use MERCI data, analysis code, or this collection bundle, please cite the MERCI CBMI 2025 paper and the extended journal version when available.
