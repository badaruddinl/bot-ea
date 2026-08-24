#property strict
#property tester_everytick_calculate

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineExecutionBroker.mqh"

bool HarnessPassed=false;

double DisabledHarnessFloor(const double value,const double tick)
  {
   return MathFloor(value/tick+1.0e-9)*tick;
  }

double DisabledHarnessCeil(const double value,const double tick)
  {
   return MathCeil(value/tick-1.0e-9)*tick;
  }

bool BuildDisabledHarnessPlan(const ProfileConfig &profile,
                              SignalPlan &plan,
                              string &reason)
  {
   MqlTick tick;
   if(!SymbolInfoTick(profile.symbol,tick))
     {
      reason="HARNESS_TICK_UNAVAILABLE";
      return false;
     }
   ZeroMemory(plan);
   plan.profile_id=profile.profile_id;
   plan.profile_version=profile.profile_version;
   plan.profile_fingerprint=profile.profile_fingerprint;
   plan.strategy_version=profile.strategy_version;
   plan.setup_id="g14-disabled-setup";
   plan.signal_id="g14-disabled-signal";
   plan.symbol=profile.symbol;
   plan.side=ENGINE_SIDE_BUY;
   plan.account_login=AccountInfoInteger(ACCOUNT_LOGIN);
   plan.account_server=AccountInfoString(ACCOUNT_SERVER);
   plan.trade_mode=(ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   plan.terminal_identity=profile.terminal_identity;
   plan.magic=profile.magic;
   const datetime now=(datetime)(tick.time_msc/1000);
   plan.setup_created_at=now-1;
   plan.entry_ready_at=now;
   plan.valid_until=now+profile.maximum_signal_age_seconds;
   plan.volume=ResolveProfileLot(profile,AccountInfoDouble(ACCOUNT_BALANCE));
   plan.tick_size=profile.tick_size;
   plan.minimum_executable_rr=1.0;
   plan.maximum_spread=profile.maximum_spread;
   plan.planned_entry=DisabledHarnessCeil(tick.ask,profile.tick_size);
   plan.stop_loss=DisabledHarnessFloor(tick.ask-2.0,profile.tick_size);
   plan.take_profit=DisabledHarnessCeil(tick.ask+3.0,profile.tick_size);
   plan.invalidation=plan.stop_loss;
   plan.risk_price=plan.planned_entry-plan.stop_loss;
   plan.executable=true;
   reason="OK";
   return true;
  }

int OnInit(void)
  {
   ProfileConfig profile;LoadBuildProfile(profile);
   SignalPlan plan;string reason="";
   if(!BuildDisabledHarnessPlan(profile,plan,reason))
      return INIT_FAILED;
   const int before=PositionsTotal();
   CExecutionBroker broker;
   const bool initialized=broker.Initialize(profile,false,reason);
   ExecutionReceipt receipt;
   const bool submitted=initialized && broker.Submit(plan,receipt,reason);
   const int after=PositionsTotal();
   HarnessPassed=initialized && !submitted && !broker.AuthorityEnabled() &&
      receipt.state==EXECUTION_SUBMIT_DISABLED &&
      receipt.validation_allowed && !receipt.sent &&
      receipt.reason=="ORDER_AUTHORITY_DISABLED" && before==after;
   Print("G14_EXECUTION_DISABLED passed=",HarnessPassed,
         " initialized=",initialized," submitted=",submitted,
         " validation=",receipt.validation_allowed,
         " positions_before=",before," positions_after=",after,
         " retcode=",receipt.retcode,
         " order_authority=DISABLED reason=",reason);
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
