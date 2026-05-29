# MERCI analysis & benchmarks

Scripts to reproduce the MTAP extended MERCI paper: cross-modal audit, human conflict validation (§4.1), and indexing benchmarks A/B/C.

- **Dataset:** [Hugging Face `zhijinRBS/MERCI`](https://huggingface.co/datasets/zhijinRBS/MERCI)
- **Collection stack:** [PERCY](https://github.com/zhijinMeng/PERCY)

## Data layout

Point scripts at normalized session folders (`chat_history.json` per session):

```bash
export NORMALIZED_MEDIA_ROOT=/path/to/normalized_media   # 30-session audit snapshot
# optional legacy layout:
export PERCY_DATA_ROOT=/path/to/percy_data
```

Or symlink:

```bash
mkdir -p ../data
ln -s /path/to/HF_export/normalized_media ../data/normalized_media
```

`cross_modal_per_session.csv` locks the 30 sessions used in the paper tables.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd analysis   # if you cloned repo root; scripts assume cwd = analysis/
```

## Reproduce paper benchmarks

```bash
# Offline FER 7-dim probabilities (Docker; see run_offline_fer_in_docker.sh)
./run_offline_fer_in_docker.sh

# Benchmarks A & B (+ bootstrap CIs)
python run_downstream_benchmarks.py

# Benchmark C (12 queries in benchmark_c_queries.json)
python run_affect_retrieval_benchmark.py

# §4.1 human vs deployment rule (annotation CSV)
python run_human_conflict_validation.py colleague_ar.csv

# Cross-corpus transfer (download MELD/IEMOCAP CSVs into analysis/ first)
python run_cross_corpus_merci_meld.py --meld-train meld_train_sent_emo.csv ...
python run_cross_corpus_merci_meld_roberta.py   # slower; needs GPU optional
```

## Audit / figures (optional)

```bash
python export_cross_modal_per_session.py
python cross_modal_consistency.py
python plot_merci_figures.py
```

## Outputs

Precomputed CSV/JSON in this folder match the paper tables where noted (`benchmark_*.csv`, `human_conflict_validation_*.json`). Re-run scripts after changing data or protocol.
