#property strict
#property tester_everytick_calculate

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineBrokerContext.mqh"

bool HarnessPassed=false;

double HarnessTickFloor(const double value,const double tick)
  {
   return MathFloor(value/tick+1.0e-9)*tick;
  }

double HarnessTickCeil(const double value,const double tick)
  {
   return MathCeil(value/tick-1.0e-9)*tick;
  }

bool BuildLivePlan(const ProfileConfig &profile,SignalPlan &plan,string &reason)
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
   plan.setup_id="g14-broker-setup";
   plan.signal_id="g14-broker-signal";
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
   plan.maximum_drift_r=profile.maximum_drift_r;
   plan.maximum_spread=profile.maximum_spread;
   plan.planned_entry=HarnessTickCeil(tick.ask,profile.tick_size);
   plan.stop_loss=HarnessTickFloor(tick.ask-2.0,profile.tick_size);
   plan.take_profit=HarnessTickCeil(tick.ask+3.0,profile.tick_size);
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
   if(!BuildLivePlan(profile,plan,reason))
     {
      Print("G14_BROKER_CONTEXT passed=false reason=",reason);
      return INIT_FAILED;
     }
   ExecutionContext context;BrokerPreflight preflight;
   const bool collected=ExecutionCollectBrokerContext(
      plan,profile,context,preflight,reason);
   ExecutionValidation validation;
   const bool validated=collected && ValidateExecution(plan,profile,context,validation);
   HarnessPassed=collected && validated && preflight.request_built &&
      preflight.check_called && validation.allowed &&
      preflight.request.magic==(ulong)profile.magic &&
      preflight.request.sl==plan.stop_loss &&
      preflight.request.tp==plan.take_profit;
   Print("G14_BROKER_CONTEXT passed=",HarnessPassed,
         " collected=",collected," validated=",validated,
         " order_check=",context.broker_check_allowed,
         " retcode=",context.broker_check_retcode,
         " filling=",EnumToString(preflight.request.type_filling),
         " margin=",DoubleToString(context.required_margin,2),
         " positions=",context.position_count,
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
