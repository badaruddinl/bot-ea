#property strict
#property version   "1.110"
#property description "Profile-locked GOLD.i native runtime skeleton"

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineRuntime.mqh"

input long   InpExpectedLogin=0;
input string InpExpectedServer="";

CGoldEngineRuntime Runtime;

int OnInit(void)
  {
   return Runtime.Initialize(InpExpectedLogin,InpExpectedServer);
  }

void OnTick(void)
  {
   Runtime.OnTick();
  }

void OnDeinit(const int reason)
  {
   Runtime.Deinitialize(reason);
  }
