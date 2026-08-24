#property strict
#property tester_everytick_calculate

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineExecutionBroker.mqh"

bool HarnessPassed=false;

int OnInit(void)
  {
   ProfileConfig profile;LoadBuildProfile(profile);
   const bool owned=ClassifyPositionIdentity(
      profile,profile.symbol,profile.magic,"GE|GOLDI|signal") ==
      POSITION_IDENTITY_OWNED;
   const bool other_symbol=ClassifyPositionIdentity(
      profile,"GOLDm#",profile.magic,"GE|GOLDI|signal") ==
      POSITION_IDENTITY_OTHER_SYMBOL;
   const bool foreign_magic=ClassifyPositionIdentity(
      profile,profile.symbol,profile.magic+1,"GE|GOLDI|signal") ==
      POSITION_IDENTITY_FOREIGN_MAGIC;
   const bool magic_collision=ClassifyPositionIdentity(
      profile,profile.symbol,profile.magic,"manual-or-foreign-ea") ==
      POSITION_IDENTITY_MANUAL_COMMENT;
   HarnessPassed=owned && other_symbol && foreign_magic && magic_collision;
   Print("G18_OWNERSHIP_FAILURE passed=",HarnessPassed,
         " owned=",owned,
         " other_symbol=",other_symbol,
         " foreign_magic=",foreign_magic,
         " magic_collision=",magic_collision,
         " cross_profile_management=false order_authority=DISABLED");
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
