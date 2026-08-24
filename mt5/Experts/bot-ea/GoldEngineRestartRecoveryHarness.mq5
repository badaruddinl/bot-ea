#property strict

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineExecutionBroker.mqh"
#include "../../Include/bot-ea/GoldEnginePositionPersistence.mqh"
#include "../../Include/bot-ea/GoldEngineInstanceLease.mqh"

ProfileConfig HarnessProfile;
CExecutionBroker HarnessBroker;
CPositionStateStore HarnessStore;
CEngineInstanceLease HarnessLease;
bool HarnessAttempted=false;
bool HarnessRecovered=false;

double RestartFloor(const double value,const double tick)
  {
   return MathFloor(value/tick+1.0e-9)*tick;
  }

double RestartCeil(const double value,const double tick)
  {
   return MathCeil(value/tick-1.0e-9)*tick;
  }

bool BuildRestartPlan(SignalPlan &plan,string &reason)
  {
   MqlTick tick;
   if(!SymbolInfoTick(HarnessProfile.symbol,tick))
     {
      reason="HARNESS_TICK_UNAVAILABLE";
      return false;
     }
   ZeroMemory(plan);
   plan.profile_id=HarnessProfile.profile_id;
   plan.profile_version=HarnessProfile.profile_version;
   plan.profile_fingerprint=HarnessProfile.profile_fingerprint;
   plan.strategy_version=HarnessProfile.strategy_version;
   plan.setup_id="G18|GOLDI|RESTART|SETUP";
   plan.signal_id="G18|GOLDI|RESTART|SIGNAL";
   plan.symbol=HarnessProfile.symbol;
   plan.side=ENGINE_SIDE_BUY;
   plan.account_login=AccountInfoInteger(ACCOUNT_LOGIN);
   plan.account_server=AccountInfoString(ACCOUNT_SERVER);
   plan.trade_mode=(ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   plan.terminal_identity=HarnessProfile.terminal_identity;
   plan.magic=HarnessProfile.magic;
   const datetime now=(datetime)(tick.time_msc/1000);
   plan.setup_created_at=now-1;
   plan.entry_ready_at=now;
   plan.valid_until=now+HarnessProfile.maximum_signal_age_seconds;
   plan.volume=0.01;
   plan.tick_size=HarnessProfile.tick_size;
   plan.minimum_executable_rr=1.0;
   plan.maximum_spread=HarnessProfile.maximum_spread;
   plan.planned_entry=RestartCeil(tick.ask,HarnessProfile.tick_size);
   plan.stop_loss=RestartFloor(tick.ask-3.0,HarnessProfile.tick_size);
   plan.take_profit=RestartCeil(tick.ask+5.0,HarnessProfile.tick_size);
   plan.invalidation=plan.stop_loss;
   plan.risk_price=plan.planned_entry-plan.stop_loss;
   plan.executable=true;
   reason="OK";
   return true;
  }

bool RecoverAndClose(const ManagedPosition &position,string &reason)
  {
   ExpectedPositionState expected;
   if(HarnessStore.Load(expected)!=POSITION_STATE_VALID || !expected.active)
     {
      reason="RESTART_STATE_MISSING";
      return false;
     }
   if(!PositionStateMatches(position,expected,HarnessProfile.tick_size,reason))
      return false;
   PositionActionReceipt closed;
   if(!HarnessBroker.CloseOwnedPosition(position.ticket,closed,reason))
      return false;
   if(!HarnessStore.Clear(expected))
     {
      reason="RESTART_STATE_CLEAR_FAILED";
      return false;
     }
   HarnessRecovered=true;
   Print("G18_RESTART_RECOVERY passed=true phase=RECOVER",
         " ticket=",position.ticket,
         " state_generation=",expected.generation,
         " positions_after=",PositionsTotal(),
         " close_retcode=",closed.retcode,
         " order_authority=DEMO_E2E_ONLY");
   return true;
  }

int OnInit(void)
  {
   LoadBuildProfile(HarnessProfile);
   string reason="";
   if(!ValidateObservedAccountBinding(
         HarnessProfile,108098316,"XMGlobal-MT5 5",
         AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER),
         (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE),reason))
      return INIT_FAILED;
   if(!HarnessLease.Acquire(HarnessProfile,AccountInfoInteger(ACCOUNT_LOGIN),reason))
      return INIT_FAILED;
   if(!HarnessBroker.Initialize(HarnessProfile,true,reason))
      return INIT_FAILED;
   HarnessStore.Initialize(HarnessProfile.profile_id,HarnessProfile.profile_fingerprint);
   ManagedPosition positions[];bool ownership_conflict=false;
   if(!HarnessBroker.DiscoverOwnedPositions(
         positions,ownership_conflict,reason) ||
      ownership_conflict || ArraySize(positions)>1)
      return INIT_FAILED;
   if(ArraySize(positions)==1)
     {
      if(!RecoverAndClose(positions[0],reason))
        {
         Print("G18_RESTART_RECOVERY passed=false phase=RECOVER reason=",reason);
         return INIT_FAILED;
        }
      EventSetTimer(1);
     }
   return INIT_SUCCEEDED;
  }

void OnTick(void)
  {
   if(HarnessAttempted || HarnessRecovered)
      return;
   MqlDateTime now;TimeToStruct(TimeCurrent(),now);
   if(now.hour<8 || now.hour>=23)
      return;
   HarnessAttempted=true;
   string reason="";SignalPlan plan;
   if(!BuildRestartPlan(plan,reason))
      return;
   ExecutionReceipt opened;
   if(!HarnessBroker.Submit(plan,opened,reason))
     {
      Print("G18_RESTART_RECOVERY passed=false phase=OPEN reason=",reason,
            " retcode=",opened.retcode);
      return;
     }
   ManagedPosition positions[];bool ownership_conflict=false;
   if(!HarnessBroker.DiscoverOwnedPositions(
         positions,ownership_conflict,reason) ||
      ownership_conflict || ArraySize(positions)!=1)
      return;
   const ManagedPosition position=positions[0];
   ExpectedPositionState expected;PositionStateReset(expected);
   expected.active=true;
   expected.ticket=position.ticket;
   expected.signal_id=plan.signal_id;
   expected.volume=position.volume;
   expected.entry_price=position.entry_price;
   expected.stop_loss=position.stop_loss;
   expected.take_profit=position.take_profit;
   if(!HarnessStore.Save(expected))
      return;
   Print("G18_RESTART_RECOVERY passed=true phase=OPEN",
         " ticket=",position.ticket,
         " state_generation=",expected.generation,
         " positions_before_restart=",PositionsTotal(),
         " open_retcode=",opened.retcode,
         " order_authority=DEMO_E2E_ONLY");
   if(!MQLInfoInteger(MQL_TESTER))
      TerminalClose(1801);
  }

void OnTimer(void)
  {
   if(HarnessRecovered && !MQLInfoInteger(MQL_TESTER))
      TerminalClose(0);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   HarnessLease.Release();
  }
