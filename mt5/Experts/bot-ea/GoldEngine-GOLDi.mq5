#property strict
#property version   "1.110"
#property description "Profile-locked GOLD.i native runtime skeleton"

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineRuntime.mqh"

input long   InpExpectedLogin=0;
input string InpExpectedServer="";
input bool   InpEnableOrderAuthority=false;

CGoldEngineRuntime Runtime;

int OnInit(void)
  {
   return Runtime.Initialize(
      InpExpectedLogin,InpExpectedServer,InpEnableOrderAuthority);
  }

void OnTick(void)
  {
   Runtime.OnTick();
  }

void OnTimer(void)
  {
   Runtime.OnTimer();
  }

void OnDeinit(const int reason)
  {
   Runtime.Deinitialize(reason);
  }

void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   Runtime.OnTradeTransaction(transaction,request,result);
  }
