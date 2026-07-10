# MERCI+ analysis & benchmarks

Scripts to reproduce the MTAP extended MERCI+ paper: cross-modal audit, human conflict validation (§4.1), indexing Benchmarks A/B/C, and cross-corpus transfer (§4.5).

- **Dataset:** [Hugging Face `zhijin-meng/MERCI-plus`](https://huggingface.co/datasets/zhijin-meng/MERCI-plus)
- **Paper appendix:** reproducibility specifications (Section A) match these scripts
- **Collection stack:** [PERCY](https://github.com/zhijinMeng/PERCY)

## Data layout

Point scripts at normalized session folders (`chat_history.json` per session):

```bash
export NORMALIZED_MEDIA_ROOT=/path/to/normalized_media
```

The audit session list is fixed in `cross_modal_per_session.csv` (41 sessions, 1,205 user turns). Regenerate with:

```bash
python cross_modal_consistency.py
python export_cross_modal_per_session.py
```

Turn-level exports on Hugging Face (`data/turns_user.jsonl`) mirror the same fields documented in Appendix A.2 of the paper.

## Setup

```bash
cd analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For Benchmark B multimodal (`Text + raw FER probs`), also run offline FER replay (Docker + PERCY emotion model):

```bash
./run_offline_fer_in_docker.sh   # writes offline_fer_probs.csv
```

## Reproduce main-text tables

| Paper table | Command | Output |
|-------------|---------|--------|
| Table 3 (Benchmark A) | `python run_downstream_benchmarks.py` | `benchmark_a_conflict_prediction.csv` |
| Table 4 (Benchmark B) | same | `benchmark_b_conflict_aware_emotion.csv` |
| Table 5 (Benchmark C) | `python run_affect_retrieval_benchmark.py` | `benchmark_c_affect_retrieval.csv` |
| Table 6 (cross-corpus) | see below | `benchmark_cross_corpus_merci_meld*.csv` |

### Benchmarks A & B

```bash
python run_downstream_benchmarks.py
```

Protocol (see paper Appendix A.4):
- 5-fold `GroupKFold` on `session_id`
- TF-IDF: `max_features=20000`, `ngram_range=(1,2)`, `min_df=1`
- LogReg: `max_iter=3000`, `class_weight=balanced`, seeds 11/22/33 (majority vote)
- Bootstrap CIs: B=2000, session-level resampling, percentile 2.5/97.5

### Benchmark C

```bash
python run_affect_retrieval_benchmark.py
```

Query definitions: `benchmark_c_queries.json` (12 queries; full list in paper Table A).

### Cross-corpus transfer (§4.5)

Download MELD `train/dev/test_sent_emo.csv` and IEMOCAP Session1–5 into `analysis/` (not redistributed):

```bash
python run_cross_corpus_merci_meld.py \
  --meld-train meld_train_sent_emo.csv \
  --meld-dev meld_dev_sent_emo.csv \
  --meld-test meld_test_sent_emo.csv \
  --iemocap-root iemocap_hf/data

python run_cross_corpus_merci_meld_roberta.py   # frozen distilroberta-base, max_len=128
```

### Human conflict validation (§4.1)

```bash
python run_human_conflict_validation.py colleague_ar.csv
```

Annotation guide: `HUMAN_CONFLICT_ANNOTATION_GUIDE.md`

## Audit / figures (optional)

```bash
python plot_merci_figures.py          # main-text figures
```

Figure 2 (dataset samples gallery): `../Figures/build_fig_dataset_samples.sh`

## Hyperparameters summary

All defaults are hard-coded in the runner scripts; the paper Appendix A.3 lists the exact values. Do not change them when reproducing reported numbers.
