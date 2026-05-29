# MERCI

Audit scripts, human conflict validation, and indexing benchmarks (A/B/C) for the **MERCI** corpus (Multimodal dataset for Emotionally-aware peRsonalised Conversational Interactions).

| Resource | Link |
|----------|------|
| Dataset | https://huggingface.co/datasets/zhijinRBS/MERCI |
| PERCY (collection) | https://github.com/zhijinMeng/PERCY |
| Paper | Extended CBMI 2025 → MTAP special issue |

## Quick start

See [`analysis/README.md`](analysis/README.md) for environment setup, data paths, and commands to reproduce tables in the article.

```bash
cd analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export NORMALIZED_MEDIA_ROOT=/path/to/normalized_media
python run_downstream_benchmarks.py
```

## Layout

```
analysis/          # Python scripts, query specs, published benchmark CSVs
  README.md
  requirements.txt
  run_*.py
  merci_*.py
  benchmark_c_queries.json
  cross_modal_per_session.csv
```

## Citation

If you use this code or the MERCI release, please cite the MERCI CBMI 2025 paper and the extended journal version when available.
