#property strict
#property tester_everytick_calculate

#define BUILD_PROFILE_GOLDM
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineExecutionBroker.mqh"

bool HarnessPassed=false;

int OnInit(void)
  {
   ProfileConfig profile;LoadBuildProfile(profile);
   const long expected_login=391425346;
   const string expected_server="XMGlobal-MT5 14";
   string reason="";
   const bool correct=ValidateObservedAccountBinding(
      profile,expected_login,expected_server,expected_login,expected_server,
      ACCOUNT_TRADE_MODE_REAL,reason);
   const bool wrong_account=!ValidateObservedAccountBinding(
      profile,expected_login,expected_server,expected_login+1,expected_server,
      ACCOUNT_TRADE_MODE_REAL,reason) && reason=="WRONG_ACCOUNT";
   const bool wrong_server=!ValidateObservedAccountBinding(
      profile,expected_login,expected_server,expected_login,"XMGlobal-MT5 5",
      ACCOUNT_TRADE_MODE_REAL,reason) && reason=="WRONG_SERVER";
   const bool demo_refused=!ValidateObservedAccountBinding(
      profile,expected_login,expected_server,expected_login,expected_server,
      ACCOUNT_TRADE_MODE_DEMO,reason) && reason=="WRONG_TRADE_MODE";
   CExecutionBroker broker;
   const bool initialized_disabled=broker.Initialize(profile,false,reason) &&
      !broker.AuthorityEnabled();
   HarnessPassed=correct && wrong_account && wrong_server && demo_refused &&
      initialized_disabled && profile.magic==26081912 &&
      profile.profile_id=="GOLDM" && !profile.order_authority_default;
   Print("G17_GOLDM_REFUSAL passed=",HarnessPassed,
         " exact_profile=",profile.profile_id=="GOLDM",
         " wrong_account=",wrong_account,
         " wrong_server=",wrong_server,
         " demo_refused=",demo_refused,
         " magic=",profile.magic,
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
