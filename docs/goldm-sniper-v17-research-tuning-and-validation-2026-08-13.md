# GOLD.i# Sniper v1.7: riset, tuning, validation, dan keputusan final

Tanggal audit: 13 Agustus 2026
Instrumen: `GOLD.i#`
Timeframe: M15 setup/risk, M5 konfirmasi, M1 refinement dan close
Status: signal-only; tidak mengirim market order

## Keputusan

Kandidat paling worth dari rangkaian ini adalah `D7_Channel12Broad` dan sudah dipasang sebagai preset default `GoldMSniperParity_GOLD_i.set`.

Ini bukan klaim bahwa strategi siap live. Empat tahun sebelum karantina positif dan validation segmented menguat, tetapi OOS setelah 1 Juli 2026 baru berisi enam trade dan negatif. Status yang tepat adalah **kandidat riset terbaik, layak paper/forward observation, belum layak auto-live**.

## Protokol anti-overfit

- Development: 28 Februari 2022 sampai 28 Februari 2024, enam blok empat bulanan.
- Validation beku: 28 Februari 2024 sampai 28 Februari 2026, enam blok empat bulanan.
- Karantina: 28 Februari 2026 sampai 1 Juli 2026 tidak diuji, tidak dipakai OOS, dan tidak dipakai untuk tuning.
- OOS final: 1 Juli 2026 sampai data terakhir yang tersedia pada tester (11 Agustus 2026).
- Semua test menggunakan MT5 real ticks, `GOLD.i#`, M15 host, execution delay 100 ms, leverage tester 1:1000, dan hasil dinilai dalam R agar leverage tidak memperbesar statistik edge.
- Kandidat tidak diubah selama validation. Setelah OOS dibuka, algoritme tidak dituning lagi.

## Baseline internet dan jurnal

1. Time-series momentum/continuation. Dataset paper asli Moskowitz, Ooi, dan Pedersen menunjukkan return masa lalu dapat memprediksi return berikutnya pada futures lintas aset, termasuk komoditas. Ini menjadi dasar keluarga breakout/channel continuation: <https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data>
2. Reaksi berita makro. Christie-David, Chaudhry, dan Koch menemukan harga emas sensitif terhadap CPI, unemployment, GDP/PPI dan volatilitas meningkat setelah rilis: <https://www.sciencedirect.com/science/article/pii/S0148619500000291>
3. Intraday price discovery emas berbeda menurut sesi dan state/news: <https://www.sciencedirect.com/science/article/pii/S1057521921002209>
4. Metal futures bereaksi cepat dan asimetris terhadap pengumuman makro, dengan NFP dan durable goods termasuk yang terbesar: <https://www.sciencedirect.com/science/article/pii/S0378426611001968>
5. Respons FOMC terlihat dalam horizon 5–10 menit dan adjustment jangka pendek bertahan: <https://www.sciencedirect.com/science/article/pii/S1057521924004186>
6. CME menjelaskan London, New York, dan Shanghai sebagai tiga pusat utama perdagangan emas; ini mendukung pengujian berbasis sesi: <https://www.cmegroup.com/education/articles-and-reports/trading-comex-gold-and-silver>
7. Baseline VWAP + EMA regime/pullback juga diuji sebagai keluarga tersendiri. Sumbernya preprint 2026 dan karena belum peer-reviewed diperlakukan hanya sebagai hipotesis, bukan bukti final: <https://papers.ssrn.com/sol3/Delivery.cfm/6650958.pdf?abstractid=6650958&mirid=1&type=2>

## Keluarga kandidat yang diuji

- `C1–C5`: continuation sesi, decorrelated confluence, strict HTF trend, VWAP.
- `C6–C14`: defensive M1 exit, Fibonacci vote versus projection-only, broad confluence.
- `R1–R3`: M15 Bollinger reversal dengan RSI(14), Stochastic(14,3,3), dan morning/evening doji star.
- `P1–P3`, `T1–T3`, `S1–S3`: EMA50/EMA200 + VWAP pullback, trend-strength regime, dan scale-out.
- `D1–D9`: Donchian-style M15 channel breakout, retest, M5/M1 confirmation, sesi dan context broadening, serta plateau lookback.

CSV hasil lengkap berada di `data/backtests/goldm_sniper_signal_v1/candidate-matrix/`.

Temuan utama:

- Baseline v1.6 pada development: 563 trade, -52.118R, expectancy -0.0926R; hanya 1/6 blok positif.
- Reversal RSI/Stochastic/Bollinger gagal: kandidat terbaik `R2` -0.0834R/trade.
- EMA/VWAP pullback hampir netral, tetapi tidak stabil; scale-out sebelum 1R memperburuk hasil.
- Fibonacci-aligned entry pada kandidat C11: 25 trade, -5.785R, -0.231R/trade; non-aligned: 169 trade, +11.070R, +0.066R/trade. Karena itu Fibonacci tidak lagi menjadi vote/score/delay entry, tetapi tetap dipakai untuk swing extension, target projection, dan close reaction.
- Channel 12 bar dipilih karena memberi sampel lebih besar dan validation lebih kuat daripada channel 16, walau development channel 16 lebih tinggi.

## Algoritme final D7

1. Hanya mencari setup antara menit server 900–1259 (15:00–20:59).
2. M15 harus menembus channel high/low 12 candle sebelumnya dengan body, wick, displacement, spread, ATR regime, dan relative tick-volume yang sehat.
3. Minimal satu dari konteks D1/H4/H1 harus searah. Harga breakout juga harus berada pada sisi VWAP intraday yang searah.
4. Menunggu retest M15 pada level channel.
5. M5 memakai validasi luas: price action/doji star, RSI(14), Stochastic(14,3,3), dan Bollinger Bands. Diperlukan 2–4 evidence; banyak vote tidak otomatis berarti kualitas lebih tinggi.
6. M1 menguatkan timing dengan candle arah, micro-break, dan RSI(7). Jika dua candle M1 berlawanan dan posisi sudah <= -0.25R sebelum mencapai 1R, sinyal ditutup defensif.
7. Stop bersifat struktural M15. Target objektif mengambil level terdekat yang memenuhi minimum 1.5R, termasuk Fibonacci extension 127.2%, 161.8%, dan 200%.
8. Setelah 1R/2R, stop dikunci; M1 juga boleh menutup saat struktur mikro berbalik, terutama setelah mencapai Fibonacci reaction.

## Hasil D7 segmented

| Blok | Periode | Trade | Total R | Expectancy R |
|---|---|---:|---:|---:|
| p1 | 2022-02-28–2022-06-28 | 20 | +0.44566 | +0.02228 |
| p2 | 2022-06-28–2022-10-28 | 18 | +2.41670 | +0.13426 |
| p3 | 2022-10-28–2023-02-28 | 16 | +0.84081 | +0.05255 |
| p4 | 2023-02-28–2023-06-28 | 15 | -0.35061 | -0.02337 |
| p5 | 2023-06-28–2023-10-28 | 15 | +5.73903 | +0.38260 |
| p6 | 2023-10-28–2024-02-28 | 17 | -6.25308 | -0.36783 |
| v1 | 2024-02-28–2024-06-28 | 14 | +3.05903 | +0.21850 |
| v2 | 2024-06-28–2024-10-28 | 10 | +1.78129 | +0.17813 |
| v3 | 2024-10-28–2025-02-28 | 19 | -2.57263 | -0.13540 |
| v4 | 2025-02-28–2025-06-28 | 16 | +0.46326 | +0.02895 |
| v5 | 2025-06-28–2025-10-28 | 17 | +3.04485 | +0.17911 |
| v6 | 2025-10-28–2026-02-28 | 19 | +4.52639 | +0.23823 |

Development: 101 trade, +2.83851R, +0.02810R/trade, 4/6 blok positif.
Validation: 95 trade, +10.30219R, +0.10844R/trade, 5/6 blok positif.
Gabungan/full: 196 trade, +13.14070R, +0.06704R/trade, 9/12 blok positif.

Full-test diagnostics: 120 BUY / 76 SELL, P(>=1R) 37.24%, P(>=2R) 5.10%, P(>=3R) 0.51%, average MFE 0.789R, average MAE -0.489R.

## OOS setelah karantina

Periode yang diminta: 1 Juli–13 Agustus 2026. Data tester berakhir 11 Agustus 2026.

- 6 trade
- -1.33201R
- -0.22200R/trade
- 2/6 mencapai 1R
- 0/6 mencapai 2R

Sampel enam trade terlalu kecil untuk confidence interval yang berguna. Hasilnya tidak boleh disembunyikan: OOS awal negatif. Kandidat tidak dituning setelah hasil ini. Keputusan operasional: paper/forward observation sampai minimal sekitar 50 OOS trade atau horizon 6–12 bulan; jangan aktifkan auto-order hanya dari hasil riset ini.

## Early candidate alert v1.71

Early candidate merupakan watchlist, bukan entry dan bukan probabilitas terkalibrasi. Confidence 0–100 adalah skor deterministik dari informasi yang sudah tersedia sebelum entry: context D1/H4/H1, kualitas breakout M15, relative volume, kedalaman retest, evidence M5, dan candle pattern.

- Alert dikirim hanya ketika `confidence > 60`.
- Event: `SNIPER_EARLY_CANDIDATE`, `status=WATCH_ONLY`, `autoEntry=false`.
- Promosi: `SNIPER_EARLY_PROMOTED`, kemudian sinyal final `SNIPER_SIGNAL status=ENTRY_READY`.
- Pembatalan: `SNIPER_EARLY_CANCELLED` dengan alasan deterministik.
- Auto-entry consumer hanya boleh membaca `SNIPER_SIGNAL status=ENTRY_READY`; event early tidak boleh menjadi trigger order.
- Setup ID yang sama dipakai dari watchlist sampai promosi/pembatalan untuk mencegah notifikasi ganda.

Replay full 2022–28 Februari 2026:

- 543 early candidate; confidence minimum 63, rata-rata 79.69, maksimum 96.
- 193 dipromosikan menjadi entry-ready.
- 350 dibatalkan: 330 karena entry distance dan 20 karena konfirmasi M1 kedaluwarsa.
- 196 entry final tetap identik dengan v1.70. Tiga entry final tidak mempunyai early alert karena preliminary score belum di atas 60 sebelum M1/final-risk information tersedia.
- Distribusi early confidence: 43 pada 61–69, 222 pada 70–79, 236 pada 80–89, dan 42 pada 90–100.

Replay OOS 1 Juli–12 Agustus 2026:

- 16 early candidate, 6 dipromosikan, 10 dibatalkan.
- 6 entry dan hasil -1.33201R tetap identik; fitur alert tidak mengubah algoritme entry maupun outcome.

## Reproducibility

- EA v1.71 SHA-256: `EB1C164D32BD2A10E091459AC6BC2DDCFF52343B0D64A8C2EFC1D58F4BBC2920`.
- Preset final v1.71 SHA-256: `7C10563AB18A4F3D64BC817C89D96DADFA1D2A4A5949B1139CF182BA8BCB2337`.
- Hash v1.70 tetap tercatat pada riwayat hasil riset. Perubahan v1.71 hanya menambah lifecycle/telemetry early candidate; entry dan outcome replay identik.
- Compile: 0 errors, 0 warnings.
- Python tests: 174 passed, 1 skipped.
- Runner utama: `scripts/run-mt5-goldm-sniper-backtests.ps1`.
- Matrix runner dengan guard karantina: `scripts/run-mt5-goldm-candidate-development.ps1`.
