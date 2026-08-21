#property strict
#property tester_everytick_calculate

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineInstanceLease.mqh"

bool HarnessPassed=false;

int OnInit(void)
  {
   ProfileConfig profile;LoadBuildProfile(profile);
   const long login=108098316;
   string first_reason="";string duplicate_reason="";string recovery_reason="";
   CEngineInstanceLease first;
   CEngineInstanceLease duplicate;
   const bool first_acquired=first.Acquire(profile,login,first_reason);
   const bool duplicate_refused=!duplicate.Acquire(profile,login,duplicate_reason) &&
      duplicate_reason=="DUPLICATE_EA_INSTANCE";
   first.Release();
   const bool recovery_acquired=duplicate.Acquire(profile,login,recovery_reason);
   duplicate.Release();
   HarnessPassed=first_acquired && duplicate_refused && recovery_acquired &&
      !first.Held() && !duplicate.Held();
   Print("G18_INSTANCE_LEASE passed=",HarnessPassed,
         " first=",first_acquired,
         " duplicate_refused=",duplicate_refused,
         " recovery=",recovery_acquired,
         " cross_terminal=FILE_COMMON_EXCLUSIVE",
         " order_authority=DISABLED");
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
