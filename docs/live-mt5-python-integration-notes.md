# Live MT5 Python Integration Notes

Tanggal riset: 20 April 2026

## Tujuan

Dokumen ini merangkum implikasi resmi dari Python integration MetaTrader 5 untuk implementasi `bot-ea`.

Fokusnya bukan strategi, tetapi boundary teknis agar runtime live tetap aman dan testable.

## Ringkasan resmi yang paling relevan

### 1. Python terhubung ke terminal, bukan langsung ke broker

Package `MetaTrader5` membuka koneksi IPC ke terminal MT5 yang sedang berjalan.

Implikasi:

- runtime Python harus memperlakukan terminal sebagai dependency eksternal
- `initialize()` dan `shutdown()` harus diperlakukan sebagai lifecycle connection
- koneksi tidak boleh diasumsikan selalu tersedia walau terminal terpasang

### 2. `initialize()` dan `login()` punya peran berbeda

`initialize()` membuka koneksi ke terminal.

`login()` dipakai untuk otorisasi atau pindah akun setelah terminal siap.

Implikasi:

- adapter live sebaiknya default ke `initialize()` dulu
- kredensial hanya opsional
- runtime read-only tidak perlu memaksa `login()` bila terminal sudah terhubung ke akun target

### 3. `symbol_info()` adalah sumber utama symbol spec live

`symbol_info()` mengembalikan:

- `trade_mode`
- `trade_exemode`
- `filling_mode`
- `order_mode`
- `point`
- `trade_tick_size`
- `trade_tick_value`
- `trade_contract_size`
- `volume_min`
- `volume_max`
- `volume_step`
- `trade_stops_level`
- `trade_freeze_level`
- `margin_initial`
- harga `bid` dan `ask`

Implikasi:

- symbol spec broker harus dibaca live, bukan diasumsikan dari tabel statis
- enum integer dan bitmask harus di-map ke bentuk yang mudah dibaca codebase
- `margin_initial` tidak boleh diasumsikan universal sebagai margin rate

### 4. `symbol_select()` wajib diperlakukan sebagai precondition praktis

Contoh resmi MetaQuotes selalu mengecek visibility simbol dan memanggil `symbol_select(symbol, True)` bila perlu sebelum `order_check()` atau `order_send()`.

Implikasi:

- adapter live harus mencoba `symbol_select()` sebelum menyimpulkan simbol tidak siap
- kegagalan visibility harus diperlakukan sebagai error nyata, bukan warning kosmetik

### 5. `order_check()` adalah preflight, bukan jaminan eksekusi

`order_check()` mengembalikan hasil validasi server-side awal, termasuk `retcode`, `margin_free`, `margin_level`, dan request echo.

Implikasi:

- gunakan `order_check()` untuk broker-side validation
- jangan memperlakukan hasil sukses sebagai jaminan `order_send()` pasti lolos
- `order_send().retcode` tetap sumber kebenaran final saat execution path ditambahkan nanti

### 6. `order_calc_margin()` lebih tepat daripada inferensi dari `margin_initial`

MetaQuotes mendokumentasikan `order_calc_margin()` untuk estimasi margin berdasarkan account dan kondisi market saat ini.

Implikasi:

- estimasi margin live sebaiknya memakai `order_calc_margin()`
- fallback berbasis `margin_initial` hanya dipakai saat live broker-side data belum tersedia

### 7. Stops dan filling mode harus mengikuti spec broker live

Hal yang paling penting:

- `trade_stops_level` memberi batas minimum jarak stop
- `trade_freeze_level` memberi batas area freeze untuk modifikasi
- `ORDER_FILLING_RETURN` tidak selalu valid untuk semua execution mode

Implikasi:

- request template tidak boleh one-size-fits-all
- filling type perlu dipilih dari capability live simbol
- logic modifikasi order nanti harus memperhitungkan freeze level

## Implikasi desain untuk `bot-ea`

Urutan implementasi yang paling aman:

1. adapter live read-only
2. snapshot provider live
3. broker-side preflight dengan `order_check()`
4. baru kemudian execution runtime dengan `order_send()`

Alasan:

- repo sudah punya risk engine dan polling scaffold
- gap terbesar sebelumnya adalah tidak adanya jembatan ke terminal live
- `order_send()` terlalu dini sebelum quote, margin, stops, dan capability broker dapat dibaca dan diuji stabil

## Status implementasi repo setelah update ini

Repo sekarang sudah punya:

- `LiveMT5Adapter` untuk read-only access dan preflight
- `PriceTickSnapshot` untuk quote runtime
- `MT5SnapshotProvider` untuk membangun `RuntimeSnapshot` dari adapter MT5
- `MT5ExecutionRuntime` untuk broker preflight dan `order_send()` dengan default aman `dry-run`
- optional dependency `live` untuk package `MetaTrader5`

Yang belum ditambahkan:

- modify/close path
- freeze-level aware order modification
- live integration test automated terhadap terminal sungguhan

## Ringkasan operasional execution monitoring

Monitoring execution yang sudah selaras dengan codebase saat ini:

- runtime menyimpan `quoted_price`, `executed_price`, `slippage_points`, `fill_latency_ms`, `retcode`, `order_ticket`, dan `deal_ticket` ke `execution_events`
- posisi yang benar-benar terbuka juga bisa menyimpan `commission_cash` dan `swap_cash` ke `position_events`
- threshold eksplisit yang sudah ada di validation/promotion gate adalah `average entry spread <= 25.0 points`, `average slippage <= 5.0 points`, dan `reject_rate <= 10%`
- `fill_latency_ms` sudah direkam, tetapi belum dijadikan hard gate; saat ini fungsi utamanya adalah observability dan audit execution quality

Artinya, repo sudah siap untuk review operasional spread, slippage, reject-rate, dan latency dari artifact runtime, tetapi belum punya auto-halt khusus berbasis execution monitoring drift.

## Sumber resmi MT5 yang dipakai paling langsung

- Python integration index: gambaran lifecycle koneksi terminal dan daftar API Python MT5
  [https://www.mql5.com/en/docs/python_metatrader5](https://www.mql5.com/en/docs/python_metatrader5)
- `initialize()`: Python terhubung ke terminal MT5, dengan opsi autodiscovery atau path/account parameter
  [https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py)
- `symbol_info()`: sumber utama spec live simbol dan properti broker
  [https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py)
- `symbol_select()`: precondition praktis agar simbol tersedia di `MarketWatch`
  [https://www.mql5.com/en/docs/python_metatrader5/mt5symbolselect_py](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolselect_py)
- `order_check()`: preflight broker-side untuk validasi request dan estimasi dampak margin
  [https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py)
- `order_send()`: sumber final hasil eksekusi, termasuk `retcode`, `order`, `deal`, `bid`, `ask`, dan `request_id`
  [https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py)
- `order_calc_margin()`: estimasi margin live dalam account currency
  [https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py)
