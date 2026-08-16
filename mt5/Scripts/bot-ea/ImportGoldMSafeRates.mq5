#property strict
#property script_show_inputs

input string InpSourceSymbol = "GOLD.i#";
input string InpCustomSymbol = "GOLD_i_DEV_SAFE";
input string InpCustomGroup = "bot-ea\\research-safe";
input string InpRatesFile = "goldm_safe_rates.csv";
input datetime InpFromInclusive = D'2021.01.01 00:00:00';
input datetime InpToExclusive = D'2023.03.28 00:00:00';

const datetime GOLDM_DEVELOPMENT_END_EXCLUSIVE = D'2024.02.28 00:00:00';

void Fail(const string reason)
{
   PrintFormat("GOLDM_SAFE_RATES_IMPORT status=FAILED reason=%s", reason);
}

void OnStart()
{
   if((bool)MQLInfoInteger(MQL_TESTER))
   {
      Fail("IMPORTER_MUST_NOT_RUN_IN_TESTER");
      return;
   }
   if((bool)TerminalInfoInteger(TERMINAL_CONNECTED))
   {
      Fail("TERMINAL_MUST_BE_OFFLINE");
      return;
   }
   if(TerminalInfoString(TERMINAL_PATH) != TerminalInfoString(TERMINAL_DATA_PATH))
   {
      Fail("TERMINAL_MUST_BE_PORTABLE");
      return;
   }
   if(InpSourceSymbol == InpCustomSymbol || StringLen(InpCustomSymbol) == 0)
   {
      Fail("CUSTOM_SYMBOL_IDENTITY_INVALID");
      return;
   }
   if(InpFromInclusive >= InpToExclusive ||
      InpToExclusive > GOLDM_DEVELOPMENT_END_EXCLUSIVE)
   {
      Fail("RANGE_OUTSIDE_REGISTERED_DEVELOPMENT");
      return;
   }
   if(!SymbolSelect(InpSourceSymbol, true))
   {
      Fail("SOURCE_SYMBOL_UNAVAILABLE");
      return;
   }
   bool isCustom = false;
   if(SymbolExist(InpCustomSymbol, isCustom))
   {
      Fail("CUSTOM_SYMBOL_ALREADY_EXISTS");
      return;
   }
   if(!CustomSymbolCreate(InpCustomSymbol, InpCustomGroup, InpSourceSymbol))
   {
      PrintFormat(
         "GOLDM_SAFE_RATES_IMPORT status=FAILED reason=CUSTOM_SYMBOL_CREATE error=%d",
         GetLastError()
      );
      return;
   }

   const int handle = FileOpen(
      InpRatesFile,
      FILE_READ | FILE_CSV | FILE_ANSI,
      ','
   );
   if(handle == INVALID_HANDLE)
   {
      const int error = GetLastError();
      CustomSymbolDelete(InpCustomSymbol);
      PrintFormat(
         "GOLDM_SAFE_RATES_IMPORT status=FAILED reason=RATES_FILE_OPEN error=%d",
         error
      );
      return;
   }
   const string h0 = FileReadString(handle);
   const string h1 = FileReadString(handle);
   const string h2 = FileReadString(handle);
   const string h3 = FileReadString(handle);
   const string h4 = FileReadString(handle);
   const string h5 = FileReadString(handle);
   const string h6 = FileReadString(handle);
   if(h0 != "time" || h1 != "open" || h2 != "high" || h3 != "low" ||
      h4 != "close" || h5 != "tick_volume" || h6 != "spread")
   {
      FileClose(handle);
      CustomSymbolDelete(InpCustomSymbol);
      Fail("RATES_FILE_HEADER_INVALID");
      return;
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = 0;
   int capacity = 0;
   datetime previous = 0;
   while(!FileIsEnding(handle))
   {
      if(copied >= capacity)
      {
         capacity += 65536;
         if(ArrayResize(rates, capacity) != capacity)
         {
            FileClose(handle);
            CustomSymbolDelete(InpCustomSymbol);
            Fail("RATES_ARRAY_RESIZE_FAILED");
            return;
         }
      }
      MqlRates row;
      ZeroMemory(row);
      row.time = (datetime)(long)FileReadNumber(handle);
      row.open = FileReadNumber(handle);
      row.high = FileReadNumber(handle);
      row.low = FileReadNumber(handle);
      row.close = FileReadNumber(handle);
      row.tick_volume = (long)FileReadNumber(handle);
      row.spread = (int)FileReadNumber(handle);
      if(row.time < InpFromInclusive || row.time >= InpToExclusive ||
         (previous > 0 && row.time <= previous) || row.low > row.high ||
         row.open < row.low || row.open > row.high || row.close < row.low ||
         row.close > row.high)
      {
         FileClose(handle);
         CustomSymbolDelete(InpCustomSymbol);
         Fail("RATES_ROW_INVALID_OR_OUT_OF_RANGE");
         return;
      }
      rates[copied] = row;
      previous = row.time;
      copied++;
   }
   FileClose(handle);
   if(copied <= 0 || ArrayResize(rates, copied) != copied)
   {
      CustomSymbolDelete(InpCustomSymbol);
      Fail("RATES_FILE_EMPTY_OR_FINAL_RESIZE_FAILED");
      return;
   }
   if(rates[0].time < InpFromInclusive ||
      rates[copied - 1].time >= InpToExclusive)
   {
      CustomSymbolDelete(InpCustomSymbol);
      Fail("COPIED_RANGE_ESCAPES_REGISTERED_BOUNDS");
      return;
   }

   ResetLastError();
   const int replaced = CustomRatesReplace(
      InpCustomSymbol,
      InpFromInclusive,
      InpToExclusive - 1,
      rates
   );
   if(replaced != copied)
   {
      const int error = GetLastError();
      CustomSymbolDelete(InpCustomSymbol);
      PrintFormat(
         "GOLDM_SAFE_RATES_IMPORT status=FAILED reason=CUSTOM_RATES_REPLACE copied=%d replaced=%d error=%d",
         copied,
         replaced,
         error
      );
      return;
   }
   if(!SymbolSelect(InpCustomSymbol, true))
   {
      CustomSymbolDelete(InpCustomSymbol);
      Fail("CUSTOM_SYMBOL_SELECT_FAILED");
      return;
   }

   PrintFormat(
      "GOLDM_SAFE_RATES_IMPORT status=IMPORTED model=BAR_M1 source=%s custom=%s rows=%d first=%s last=%s fromInclusive=%s toExclusive=%s",
      InpSourceSymbol,
      InpCustomSymbol,
      copied,
      TimeToString(rates[0].time, TIME_DATE | TIME_MINUTES),
      TimeToString(rates[copied - 1].time, TIME_DATE | TIME_MINUTES),
      TimeToString(InpFromInclusive, TIME_DATE | TIME_MINUTES),
      TimeToString(InpToExclusive, TIME_DATE | TIME_MINUTES)
   );
}
