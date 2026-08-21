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
   config.profile_version="1.1.0";
   config.profile_fingerprint="7af1d75e1be54ba4505b32cedcf53f4317dea0a90a2a0636510884d0d408c5b5";
   config.strategy_version="revised-bear-baseline-b042d51";
   config.symbol="GOLD.i#";
   config.terminal_identity="GOLDI_DEDICATED_TERMINAL";
   config.magic=26081911;
   config.expected_trade_mode=ACCOUNT_TRADE_MODE_DEMO;
   config.sizing_tier_count=7;
   config.sizing_minimum_balance[0]=0.0;
   config.sizing_lot[0]=0.01;
   config.sizing_minimum_balance[1]=100.0;
   config.sizing_lot[1]=0.02;
   config.sizing_minimum_balance[2]=200.0;
   config.sizing_lot[2]=0.05;
   config.sizing_minimum_balance[3]=1000.0;
   config.sizing_lot[3]=0.1;
   config.sizing_minimum_balance[4]=2000.0;
   config.sizing_lot[4]=0.2;
   config.sizing_minimum_balance[5]=10000.0;
   config.sizing_lot[5]=1.0;
   config.sizing_minimum_balance[6]=20000.0;
   config.sizing_lot[6]=2.0;
   config.max_positions=2;
   config.max_total_lot=4.0;
#else
   config.profile_id="GOLDM";
   config.profile_version="1.1.0";
   config.profile_fingerprint="704b383f959298c8a1b1dd5c21665ffb7a022dc9831c7498e68cc37f607d4c24";
   config.strategy_version="revised-bear-baseline-b042d51";
   config.symbol="GOLDm#";
   config.terminal_identity="GOLDM_DEDICATED_TERMINAL";
   config.magic=26081912;
   config.expected_trade_mode=ACCOUNT_TRADE_MODE_REAL;
   config.sizing_tier_count=9;
   config.sizing_minimum_balance[0]=0.0;
   config.sizing_lot[0]=0.1;
   config.sizing_minimum_balance[1]=10.0;
   config.sizing_lot[1]=0.2;
   config.sizing_minimum_balance[2]=30.0;
   config.sizing_lot[2]=0.5;
   config.sizing_minimum_balance[3]=50.0;
   config.sizing_lot[3]=1.0;
   config.sizing_minimum_balance[4]=100.0;
   config.sizing_lot[4]=2.0;
   config.sizing_minimum_balance[5]=200.0;
   config.sizing_lot[5]=5.0;
   config.sizing_minimum_balance[6]=1000.0;
   config.sizing_lot[6]=10.0;
   config.sizing_minimum_balance[7]=2000.0;
   config.sizing_lot[7]=20.0;
   config.sizing_minimum_balance[8]=10000.0;
   config.sizing_lot[8]=100.0;
   config.max_positions=2;
   config.max_total_lot=200.0;
#endif
   config.order_authority_default=false;
   config.deviation_points=30;
   config.tick_size=0.01;
   config.maximum_drift_r=0.15;
#ifdef BUILD_PROFILE_GOLDI
   config.maximum_spread=0.60;
#else
   config.maximum_spread=0.72;
#endif
   config.maximum_signal_age_seconds=60;
  }

double ResolveProfileLot(const ProfileConfig &config,const double balance)
  {
   if(config.sizing_tier_count<=0 || balance<0.0)
      return 0.0;
   double selected=config.sizing_lot[0];
   for(int index=1;index<config.sizing_tier_count;index++)
     {
      if(balance<config.sizing_minimum_balance[index])
         break;
      selected=config.sizing_lot[index];
     }
   return selected;
  }

bool ValidateObservedAccountBinding(const ProfileConfig &config,
                                    const long expected_login,
                                    const string expected_server,
                                    const long observed_login,
                                    const string observed_server,
                                    const ENUM_ACCOUNT_TRADE_MODE observed_mode,
                                    string &reason)
  {
   if(expected_login<=0 || StringLen(expected_server)==0)
     {
      reason="ACCOUNT_BINDING_REQUIRED";
      return false;
     }
   if(observed_login!=expected_login)
     {
      reason="WRONG_ACCOUNT";
      return false;
     }
   if(observed_server!=expected_server)
     {
      reason="WRONG_SERVER";
      return false;
     }
   if(observed_mode!=config.expected_trade_mode)
     {
      reason="WRONG_TRADE_MODE";
      return false;
     }
   reason="OK";
   return true;
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
   return ValidateObservedAccountBinding(
      config,expected_login,expected_server,
      AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER),
      (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE),reason);
  }

#endif
