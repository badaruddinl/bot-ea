#property strict
#property tester_everytick_calculate

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineInstanceLease.mqh"

bool HarnessPassed=false;

int OnInit(void)
  {
   ProfileConfig profile;LoadBuildProfile(profile);
   ProfileConfig goldm=profile;
   goldm.profile_id="GOLDM";
   goldm.profile_fingerprint=
      "704b383f959298c8a1b1dd5c21665ffb7a022dc9831c7498e68cc37f607d4c24";
   goldm.symbol="GOLDm#";
   goldm.magic=26081912;
   const long login=108098316;
   string first_reason="";string duplicate_reason="";string recovery_reason="";
   CEngineInstanceLease first;
   CEngineInstanceLease duplicate;
   CEngineInstanceLease other_profile;
   const bool first_acquired=first.Acquire(profile,login,first_reason);
   const bool duplicate_refused=!duplicate.Acquire(profile,login,duplicate_reason) &&
      duplicate_reason=="DUPLICATE_EA_INSTANCE";
   string other_reason="";
   const bool other_profile_alive=other_profile.Acquire(goldm,391425346,other_reason);
   first.Release();
   const bool recovery_acquired=duplicate.Acquire(profile,login,recovery_reason);
   const bool other_remained_alive=other_profile.Held();
   duplicate.Release();
   other_profile.Release();
   HarnessPassed=first_acquired && duplicate_refused && recovery_acquired &&
      other_profile_alive && other_remained_alive &&
      !first.Held() && !duplicate.Held() && !other_profile.Held();
   Print("G18_INSTANCE_LEASE passed=",HarnessPassed,
         " first=",first_acquired,
         " duplicate_refused=",duplicate_refused,
         " recovery=",recovery_acquired,
         " dual_profile=",other_profile_alive,
         " one_profile_restart=",recovery_acquired,
         " other_remained_alive=",other_remained_alive,
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
