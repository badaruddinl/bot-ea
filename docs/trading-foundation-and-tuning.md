# Trading Foundation And Tuning

Tanggal riset: 20 April 2026

## Tujuan

Dokumen ini memperkuat pondasi keputusan dan tuning `bot-ea` agar perubahan parameter tetap disiplin dan dapat diaudit.

## Lima pilar

### 1. Decision quality harus dinilai setelah biaya

Hit-rate mentah tidak cukup.

Yang harus dicatat per trade:

- signal timestamp
- quoted spread
- realized fill
- slippage
- commission
- swap
- stop distance
- holding time
- net PnL

Implikasi repo:

- validation harness harus bergerak ke `expected value after costs`
- deployment gate harus memakai drawdown, expectancy, dan stability lintas symbol/session

### 2. Overfitting control harus eksplisit

Minimum yang perlu dipertahankan:

- walk-forward evaluation
- final untouched holdout
- pemisahan tegas antara riset dan promotion gate

Jika banyak varian parameter dicoba, bias data-mining harus diasumsikan ada.

Teknik riset lanjutan yang relevan:

- PBO / CSCV
- Deflated Sharpe Ratio
- SPA / Reality Check

### 3. Cost realism harus berbasis broker nyata

Kalibrasi biaya dari live log broker:

- spread
- slippage
- commission
- swap
- reject / retry cost

Implikasi repo:

- margin live memakai `order_calc_margin()`
- `margin_initial` hanya fallback
- backtest harus membebankan biaya konservatif, bukan biaya optimistis

### 4. Execution quality adalah metrik inti

Sebelum `order_send()`:

- cek symbol visibility
- cek trade mode
- cek order mode
- cek filling mode
- cek stops level
- cek freeze level
- jalankan `order_check()`

Metrik yang perlu dipantau:

- fill latency
- slippage by side
- reject code distribution
- invalid stops
- no money
- price changed / no quotes

### 5. Continuous tuning harus champion/challenger

Jangan auto-retune karena drawdown jangka pendek.

Lebih defensible:

- champion tetap aktif
- challenger diuji pada fresh out-of-sample
- promotion hanya jika challenger tetap menang setelah biaya dan guard yang sama

Monitor drift yang penting:

- realized spread vs model spread
- realized slippage vs expected
- expectancy per symbol
- expectancy per session
- reject-rate drift

## Checklist implementasi repo

1. Simpan slippage, commission, swap, dan fill latency di artifact runtime/live.
2. Tambahkan promotion gate berbasis OOS, cost-aware expectancy, dan drawdown.
3. Tambahkan drift monitor untuk spread, slippage, reject-rate, dan session expectancy.
4. Pisahkan parameter riset dari parameter live aktif.
5. Simpan log keputusan tuning: window data, kandidat parameter, benchmark, dan alasan promosi/penolakan.

## Promotion policy

Champion/challenger harus diperlakukan sebagai policy, bukan prinsip abstrak.

Minimum policy:

- challenger harus lolos gate absolut OOS
- challenger harus mengalahkan champion pada expectancy jika `require_expectancy_beat` aktif
- challenger harus mengalahkan champion pada pnl jika `require_pnl_beat` aktif
- holdout wajib jika `require_holdout_pass` aktif
- beberapa OOS window harus lolos menurut `min_window_pass_ratio`

Artifact minimum:

- `oos_windows.json`
- `promotion_decision.json`
- `promotion_report.md`

Warning-only checks boleh ada, tetapi approval final tidak boleh diberikan jika relative gate yang diwajibkan gagal.

## Monitoring thresholds

Angka di bawah ini adalah runbook operasional yang selaras dengan repo saat ini.

Yang sudah menjadi gate eksplisit di codebase sekarang adalah:

- `average entry spread <= 25.0 points`
- `average slippage <= 5.0 points`
- `reject rate <= 10%`

Ketiganya sudah tercermin di `PromotionGateThresholds`, sehingga aman dipakai sebagai baseline monitoring lintas riset dan live review.

Ringkasan operasional:

- `spread`
  - warning jika rolling average live mulai menembus baseline broker dan perlu investigasi manual
  - gate eksplisit promotion: challenger gagal jika `average_entry_spread_points > 25.0`
- `slippage`
  - warning jika rolling average live `> 5.0 points`
  - escalation jika drift menetap per symbol/session karena angka ini juga dipakai sebagai gate promotion
- `reject-rate`
  - warning dan review retcode jika reject-rate rolling `> 10%`
  - threshold ini sudah eksplisit di validation gate, jadi pelanggaran live sebaiknya dianggap incompatibility broker/runtime, bukan noise biasa
- `fill latency`
  - wajib dipantau per order karena runtime sudah menyimpan `fill_latency_ms`
  - saat ini belum ada hard cutoff otomatis di runtime atau promotion gate; latency diperlakukan sebagai metrik observability dan warning kualitas data bila hilang atau nol

Artifact operasional yang sudah tersedia di repo:

- `execution_events` menyimpan `quoted_price`, `executed_price`, `slippage_points`, `fill_latency_ms`, `retcode`, `order_ticket`, dan `deal_ticket`
- `position_events` menyimpan `commission_cash` dan `swap_cash` saat posisi berhasil dibuka

Implikasinya: threshold spread, slippage, dan reject-rate sudah siap dipakai untuk review periodik; threshold fill latency masih perlu difinalkan saat auto-halt atau stop policy untuk execution monitoring ditambahkan.

## Sumber resmi MT5 yang paling relevan

Untuk monitoring execution, sumber resmi MetaQuotes yang paling langsung dipakai adalah:

- `symbol_info()` untuk spec live broker seperti `trade_mode`, `filling_mode`, `trade_stops_level`, dan `trade_freeze_level`
- `symbol_select()` untuk memastikan simbol memang tersedia di `MarketWatch` sebelum preflight atau send
- `order_check()` untuk preflight broker-side dan membaca `retcode`, `margin_free`, serta `margin_level`
- `order_send()` untuk hasil final eksekusi termasuk `retcode`, `order`, `deal`, `bid`, `ask`, dan `request_id`
- `order_calc_margin()` untuk estimasi margin live yang lebih tepat daripada inferensi statis

## Sumber

1. MetaQuotes `order_calc_margin`:
   [https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py)
2. MetaQuotes `order_send`:
   [https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py)
3. MetaQuotes `symbol_info`:
   [https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py)
4. Bailey et al., *The Probability of Backtest Overfitting*:
   [https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
5. Bailey and Lopez de Prado, *The Deflated Sharpe Ratio*:
   [https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
6. Hansen, *A Test for Superior Predictive Ability*:
   [https://www.tandfonline.com/doi/abs/10.1198/073500105000000063](https://www.tandfonline.com/doi/abs/10.1198/073500105000000063)
7. White, *A Reality Check for Data Snooping*:
   [https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/White.pdf](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/White.pdf)
8. FINRA best execution overview:
   [https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/best-execution](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/best-execution)
