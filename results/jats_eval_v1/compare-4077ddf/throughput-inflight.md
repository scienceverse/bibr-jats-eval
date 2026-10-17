# Papers in flight: throughput_bs120 (120 jats_bs_v1 born-digital PDFs, 1,890 pages), bibr 4077ddf, 2026-10-15

Same PDFs, bibr code, GPU venv, server arguments (except where noted) and env as ../throughput-bs120-4077ddf-4b-gpulayout.
Speed only; nothing scored. Servers warm (load excluded), caches cold, 4B prefix-cache hit rate 0.0% in every config.

| config | bibr procs | batch | env | Paddle util | wall s | papers/h | pages/h | validity | outputs vs 591 run* |
|---|---|---|---|---|---|---|---|---|---|
| speed run (baseline) | 1 | 8 | - | 0.34 | 731 | 591 | 9,308 | VALID | - |
| c1-bs120 | 1 | 120 | - | 0.34 | 647 | 668 | 10,516 | VALID | 119/120 |
| c2-bs120-w8 | 1 | 120 | OCR_MAX_CONCURRENT_FILES=8, PIPELINE_MAX_CONCURRENT_POST_PARSE=8 | 0.34 | 507 | 852 | 13,420 | VALID | 119/120 |
| c3-2proc | 2 x 60 | 60 | as c2 | 0.22 | 411 | 1,051 | 16,555 | INVALID by the rule (18 log lines: 17 layout OOMs, all retried as 4+4 by bibr); 120/120 ok | 120/120 |

\* identical title, reference count and author count. The one c1/c2 difference is 10.2196_91462: 9 vs 8 authors.

Server load (vLLM log samples during the timed run):

| config | 4B running mean/max | 4B waiting max | 4B KV max | Paddle running mean/max | Paddle waiting mean/max | Paddle idle |
|---|---|---|---|---|---|---|
| speed run | 2.2 / 13 | 0 | 29% | 3.3 / 12 | 1.0 / 4 | 43/68 |
| c1 | 3.0 / 11 | 0 | 26% | 5.2 / 12 | 1.6 / 4 | 29/63 |
| c2 | 5.1 / 19 | 0 | 47% | 4.0 / 12 | 1.3 / 4 | 27/46 |
| c3 | 8.2 / 24 (= max-num-seqs) | 16 | 62% | 6.3 / 12 (= max-num-seqs) | 10.8 / 20 | 15/35 |

RAM: swap-in mean 12 (speed run), 15 (c1), 23 (c2), 36 MB/s (c3); RAM used ~29-30 of 30.5 GB in c3.
One bibr process uses only about 2 CPU cores.

## Raising the server caps, 11:38-11:57Z

Servers: 4B util 0.42 max-num-seqs 48 (was 24); Paddle util 0.22 max-num-seqs 24 (was 12), max-num-batched-tokens 32768.
bibr: 2 processes x 60, batch 60, c2 env + OCR_MAX_CONCURRENT_REGIONS=24 + LAYOUT_BATCH_SIZE=4.

| config | extra | wall s | papers/h | pages/h | validity | outputs vs 591 run |
|---|---|---|---|---|---|---|
| p1-2proc | - | 392 | 1,102 | 17,357 | VALID (0 layout OOM), 120/120 ok, card peak 28.1 GB | 119/120 |
| p2-2proc-w12 | OCR_MAX_CONCURRENT_FILES=12, PIPELINE_MAX_CONCURRENT_POST_PARSE=12 | 374 | 1,155 | 18,193 | VALID, 120/120 ok, card peak 28.2 GB | 120/120 |

| config | 4B running mean/max | 4B waiting max | 4B KV max | Paddle running mean/max | Paddle waiting mean/max | swap-in MB/s |
|---|---|---|---|---|---|---|
| p1 | 9.0 / 32 | 8 | 99.5% | 11.1 / 24 | 7.0 / 16 | 52 |
| p2 | 11.5 / 32 | 17 | 99.5% | 11.5 / 24 | 4.1 / 16 | 76 |

Binding limits now: the 4B's KV cache at util 0.42 (full; 32 of 48 slots max), and the workstation's RAM (swap-in 52-76 MB/s).
