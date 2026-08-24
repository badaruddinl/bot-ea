#property strict
#property tester_everytick_calculate

#include "../../Include/bot-ea/GoldEngineExecutionGuard.mqh"

bool HarnessPassed=false;

void BuildHarnessProfile(const string profile_id,ProfileConfig &profile)
  {
   ZeroMemory(profile);
   profile.profile_id=profile_id;
   profile.profile_version="1.1.0";
   profile.profile_fingerprint=(profile_id=="GOLDI" ?
      "7af1d75e1be54ba4505b32cedcf53f4317dea0a90a2a0636510884d0d408c5b5" :
      "704b383f959298c8a1b1dd5c21665ffb7a022dc9831c7498e68cc37f607d4c24");
   profile.strategy_version="revised-bear-baseline-b042d51";
   profile.symbol=(profile_id=="GOLDI" ? "GOLD.i#" : "GOLDm#");
   profile.terminal_identity=(profile_id=="GOLDI" ?
      "GOLDI_DEDICATED_TERMINAL" : "GOLDM_DEDICATED_TERMINAL");
   profile.magic=(profile_id=="GOLDI" ? 26081911 : 26081912);
   profile.expected_trade_mode=(profile_id=="GOLDI" ?
      ACCOUNT_TRADE_MODE_DEMO : ACCOUNT_TRADE_MODE_REAL);
   profile.order_authority_default=false;
   profile.max_positions=2;
   profile.max_total_lot=(profile_id=="GOLDI" ? 4.0 : 200.0);
   profile.deviation_points=30;
   profile.tick_size=0.01;
   profile.maximum_drift_r=0.15;
   profile.maximum_spread=(profile_id=="GOLDI" ? 0.60 : 0.72);
   profile.maximum_signal_age_seconds=60;
  }

void BuildHarnessPlan(const ProfileConfig &profile,
                      const EngineSide side,
                      SignalPlan &plan)
  {
   ZeroMemory(plan);
   plan.profile_id=profile.profile_id;
   plan.profile_version=profile.profile_version;
   plan.profile_fingerprint=profile.profile_fingerprint;
   plan.strategy_version=profile.strategy_version;
   plan.setup_id="setup-1";
   plan.signal_id="signal-1";
   plan.symbol=profile.symbol;
   plan.side=side;
   plan.account_login=1001;
   plan.account_server=(profile.profile_id=="GOLDI" ? "Demo-Server" : "Real-Server");
   plan.trade_mode=profile.expected_trade_mode;
   plan.terminal_identity=profile.terminal_identity;
   plan.magic=profile.magic;
   plan.setup_created_at=D'2026.08.18 11:59:00';
   plan.entry_ready_at=D'2026.08.18 12:00:00';
   plan.valid_until=D'2026.08.18 12:01:00';
   plan.volume=(profile.profile_id=="GOLDI" ? 0.02 : 2.0);
   plan.tick_size=profile.tick_size;
   plan.maximum_drift_r=profile.maximum_drift_r;
   plan.maximum_spread=profile.maximum_spread;
   plan.planned_entry=(side==ENGINE_SIDE_BUY ? 100.10 : 100.20);
   plan.stop_loss=(side==ENGINE_SIDE_BUY ? 99.00 : 101.50);
   plan.take_profit=(side==ENGINE_SIDE_BUY ? 102.00 : 98.00);
   plan.invalidation=(side==ENGINE_SIDE_BUY ? 98.50 : 102.00);
   plan.risk_price=1.0;
   plan.executable=true;
  }

void BuildHarnessContext(const ProfileConfig &profile,
                         const SignalPlan &plan,
                         ExecutionContext &context)
  {
   ZeroMemory(context);
   context.quote.time_msc=((long)D'2026.08.18 12:00:30')*1000;
   context.quote.bid=100.10;
   context.quote.ask=100.20;
   context.quote.last=100.15;
   context.account_login=plan.account_login;
   context.account_server=plan.account_server;
   context.trade_mode=plan.trade_mode;
   context.terminal_identity=plan.terminal_identity;
   context.free_margin=10000.0;
   context.symbol=plan.symbol;
   context.tick_size=profile.tick_size;
   context.point=0.01;
   context.volume_minimum=(profile.profile_id=="GOLDI" ? 0.01 : 0.1);
   context.volume_maximum=(profile.profile_id=="GOLDI" ? 50.0 : 100.0);
   context.volume_step=context.volume_minimum;
   context.stops_level_points=0;
   context.freeze_level_points=0;
   context.trade_enabled=true;
   context.position_count=0;
   context.total_volume=0.0;
   context.duplicate_signal=false;
   context.required_margin=10.0;
   context.broker_check_allowed=true;
   context.broker_check_retcode=0;
  }

bool AssertRejected(const SignalPlan &plan,
                    const ProfileConfig &profile,
                    const ExecutionContext &context,
                    const ExecutionRejectFlag expected)
  {
   ExecutionValidation result;
   const bool allowed=ValidateExecution(plan,profile,context,result);
   return !allowed && !result.allowed &&
          ExecutionHasReject(result.reject_mask,expected);
  }

bool TestProfile(const string profile_id)
  {
   ProfileConfig profile;BuildHarnessProfile(profile_id,profile);
   SignalPlan buy;BuildHarnessPlan(profile,ENGINE_SIDE_BUY,buy);
   ExecutionContext context;BuildHarnessContext(profile,buy,context);
   ExecutionValidation result;
   if(!ValidateExecution(buy,profile,context,result) || !result.allowed)
      return false;
   if(result.order.price!=context.quote.ask ||
      result.order.stop_loss!=buy.stop_loss ||
      result.order.take_profit!=buy.take_profit ||
      result.order.magic!=profile.magic)
      return false;
   ExecutionContext spread_only=context;
   spread_only.quote.ask=100.30;
   if(profile_id=="GOLDI")
     {
      if(!ValidateExecution(buy,profile,spread_only,result) ||
         !result.allowed || result.drift_r!=0.0)
         return false;
     }
   else if(!AssertRejected(
              buy,profile,spread_only,EXECUTION_REJECT_DRIFT))
      return false;

   SignalPlan sell;BuildHarnessPlan(profile,ENGINE_SIDE_SELL,sell);
   BuildHarnessContext(profile,sell,context);
   if(!ValidateExecution(sell,profile,context,result) ||
      result.order.price!=context.quote.bid)
      return false;

   SignalPlan changed=buy;
   BuildHarnessContext(profile,buy,context);
   changed.profile_fingerprint="wrong";
   if(!AssertRejected(changed,profile,context,EXECUTION_REJECT_PROFILE)) return false;
   changed=buy;changed.maximum_spread+=0.01;
   if(!AssertRejected(changed,profile,context,EXECUTION_REJECT_POLICY)) return false;
   changed=buy;changed.valid_until=D'2026.08.18 12:00:20';
   if(!AssertRejected(changed,profile,context,EXECUTION_REJECT_AGE)) return false;
   ExecutionContext mutated=context;
   mutated.quote.bid=(profile_id=="GOLDI" ? 100.30 : 100.20);
   mutated.quote.ask=mutated.quote.bid+0.10;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_DRIFT)) return false;
   mutated=context;mutated.quote.ask=context.quote.bid+profile.maximum_spread+0.01;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_SPREAD)) return false;
   changed=buy;changed.invalidation=100.20;
   if(!AssertRejected(changed,profile,context,EXECUTION_REJECT_INVALIDATION)) return false;
   mutated=context;mutated.account_login++;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_ACCOUNT)) return false;
   mutated=context;mutated.account_server="wrong";
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_SERVER_MODE)) return false;
   mutated=context;mutated.terminal_identity="wrong";
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_TERMINAL)) return false;
   mutated=context;mutated.symbol="wrong";
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_SYMBOL)) return false;
   changed=buy;changed.magic++;
   if(!AssertRejected(changed,profile,context,EXECUTION_REJECT_MAGIC)) return false;
   mutated=context;mutated.position_count=profile.max_positions;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_POSITION_COUNT)) return false;
   mutated=context;mutated.total_volume=profile.max_total_lot;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_TOTAL_VOLUME)) return false;
   mutated=context;mutated.free_margin=0.0;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_FREE_MARGIN)) return false;
   mutated=context;mutated.duplicate_signal=true;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_DUPLICATE)) return false;
   mutated=context;mutated.trade_enabled=false;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_BROKER_CONSTRAINT)) return false;
   changed=buy;changed.stop_loss=101.00;
   if(!AssertRejected(changed,profile,context,EXECUTION_REJECT_GEOMETRY)) return false;
   mutated=context;mutated.broker_check_allowed=false;
   if(!AssertRejected(buy,profile,mutated,EXECUTION_REJECT_BROKER_CHECK)) return false;
   return true;
  }

int OnInit(void)
  {
   const bool goldi=TestProfile("GOLDI");
   const bool goldm=TestProfile("GOLDM");
   HarnessPassed=goldi && goldm;
   Print("G14_EXECUTION_GUARD passed=",HarnessPassed,
         " goldi=",goldi," goldm=",goldm,
         " structural_geometry=true spread_reference=true reasons=18 "
         "order_authority=DISABLED");
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
