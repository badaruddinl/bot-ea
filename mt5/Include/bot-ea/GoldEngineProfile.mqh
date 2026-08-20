#ifndef GOLD_ENGINE_PROFILE_MQH
#define GOLD_ENGINE_PROFILE_MQH

#include "GoldEngineTypes.mqh"

#ifdef BUILD_PROFILE_GOLDI
 #ifdef BUILD_PROFILE_GOLDM
  #error "Exactly one build profile must be defined"
 #endif
#else
 #ifndef BUILD_PROFILE_GOLDM
  #error "Exactly one build profile must be defined"
 #endif
#endif

void LoadBuildProfile(ProfileConfig &config)
  {
#ifdef BUILD_PROFILE_GOLDI
   config.profile_id="GOLDI";
   config.profile_version="1.0.0";
   config.profile_fingerprint="23598f01c472aebafd36cb15358178d40b76fab382cd0487ba3158c8421ead64";
   config.strategy_version="revised-bear-baseline-b042d51";
   config.symbol="GOLD.i#";
   config.terminal_identity="GOLDI_DEDICATED_TERMINAL";
   config.magic=26081911;
   config.expected_trade_mode=ACCOUNT_TRADE_MODE_DEMO;
   config.max_positions=2;
   config.max_total_lot=0.04;
#else
   config.profile_id="GOLDM";
   config.profile_version="1.0.0";
   config.profile_fingerprint="c2e513cb100da86c814d9d65566c835da96f3ea1fd79d35602f2c34fd7b6dac6";
   config.strategy_version="revised-bear-baseline-b042d51";
   config.symbol="GOLDm#";
   config.terminal_identity="GOLDM_DEDICATED_TERMINAL";
   config.magic=26081912;
   config.expected_trade_mode=ACCOUNT_TRADE_MODE_REAL;
   config.max_positions=2;
   config.max_total_lot=2.0;
#endif
   config.order_authority_default=false;
   config.deviation_points=30;
  }

bool ValidateBuildProfile(const ProfileConfig &config,
                          const long expected_login,
                          const string expected_server,
                          string &reason)
  {
   if(_Symbol!=config.symbol)
     {
      reason="WRONG_SYMBOL";
      return false;
     }
   if(StringLen(config.profile_fingerprint)!=64)
     {
      reason="INVALID_PROFILE_FINGERPRINT";
      return false;
     }
   if(config.order_authority_default)
     {
      reason="ORDER_AUTHORITY_NOT_DISABLED";
      return false;
     }

   const bool tester=(bool)MQLInfoInteger(MQL_TESTER);
   if(tester)
     {
      reason="OK_TESTER";
      return true;
     }
   if(expected_login<=0 || StringLen(expected_server)==0)
     {
      reason="ACCOUNT_BINDING_REQUIRED";
      return false;
     }
   if(AccountInfoInteger(ACCOUNT_LOGIN)!=expected_login)
     {
      reason="WRONG_ACCOUNT";
      return false;
     }
   if(AccountInfoString(ACCOUNT_SERVER)!=expected_server)
     {
      reason="WRONG_SERVER";
      return false;
     }
   if((ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE)!=
      config.expected_trade_mode)
     {
      reason="WRONG_TRADE_MODE";
      return false;
     }

   reason="OK";
   return true;
  }

#endif
