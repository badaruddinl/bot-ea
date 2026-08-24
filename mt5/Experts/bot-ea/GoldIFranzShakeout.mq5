#property strict
#property version   "1.000"
#property description "Standalone tester-only GOLDI_FRANZ_SHAKEOUT v0.1.0"

#include "../../Include/bot-ea/GoldIFranzRuntime.mqh"

input bool InpEnableTesterOrders=true;
input bool InpUseRSI=true;
input bool InpUseStochasticReinforcement=true;
input bool InpUseFibonacciEntryGate=true;
input string InpRunId="FULL";

CGoldIFranzRuntime Runtime;

int OnInit(void)
  {
   return Runtime.Initialize(
      InpEnableTesterOrders,
      InpUseRSI,
      InpUseStochasticReinforcement,
      InpUseFibonacciEntryGate,
      InpRunId);
  }

void OnTick(void)
  {
   Runtime.OnTick();
  }

void OnTimer(void)
  {
   Runtime.OnTimer();
  }

void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   Runtime.OnTradeTransaction(transaction);
  }

void OnDeinit(const int reason)
  {
   Runtime.Deinitialize(reason);
  }
