#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineExecutionBroker.mqh"
#include "../../Include/bot-ea/GoldEngineOutbox.mqh"

bool HarnessPassed=false;
bool HarnessAttempted=false;
ProfileConfig HarnessProfile;
CExecutionBroker HarnessBroker;
ulong HarnessActiveTicket=0;
CEngineOutbox HarnessOutbox;
string HarnessChainId="";
int HarnessEventCount=0;

bool EmitHarnessEvent(const string event_type,
                      const string reason,
                      const string setup_id="",
                      const string signal_id="",
                      const string order_id="",
                      const string position_id="",
                      const string payload="{}")
  {
   EngineEvent event;
   event.type=ENGINE_EVENT_NONE;
   event.profile_id=HarnessProfile.profile_id;
   event.event_id=HarnessChainId+"|"+event_type;
   event.server_time=TimeCurrent();
   event.reason=reason;
   const bool written=HarnessOutbox.Emit(
      event_type,event,setup_id,signal_id,order_id,position_id,payload);
   if(written)
      HarnessEventCount++;
   return written;
  }

double LifecycleFloor(const double value,const double tick)
  {
   return MathFloor(value/tick+1.0e-9)*tick;
  }

double LifecycleCeil(const double value,const double tick)
  {
   return MathCeil(value/tick-1.0e-9)*tick;
  }

bool BuildLifecyclePlan(const ProfileConfig &profile,
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
   plan.setup_id="g14-lifecycle-setup";
   plan.signal_id="g14-lifecycle-signal";
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
   plan.planned_entry=LifecycleCeil(tick.ask,profile.tick_size);
   plan.stop_loss=LifecycleFloor(tick.ask-3.0,profile.tick_size);
   plan.take_profit=LifecycleCeil(tick.ask+5.0,profile.tick_size);
   plan.invalidation=plan.stop_loss;
   plan.risk_price=plan.planned_entry-plan.stop_loss;
   plan.executable=true;
#ifdef BUILD_PROFILE_GOLDM
   plan.engineering_tester=true;
#endif
   reason="OK";
   return true;
  }

void RunLifecycle(void)
  {
   string reason="";SignalPlan plan;
   if(!BuildLifecyclePlan(HarnessProfile,plan,reason))
     {
      Print("G14_EXECUTION_LIFECYCLE passed=false reason=",reason);
      return;
     }
   const string setup_id=HarnessChainId+"|SETUP";
   const string signal_id=HarnessChainId+"|SIGNAL";
   plan.setup_id=setup_id;
   plan.signal_id=signal_id;
   const string planned_payload=StringFormat(
      "{\"entry\":%.8f,\"stop_loss\":%.8f,\"take_profit\":%.8f,"
      "\"volume\":%.8f}",plan.planned_entry,plan.stop_loss,
      plan.take_profit,plan.volume);
   const bool setup_emitted=EmitHarnessEvent(
      "SETUP_CREATED","G17_E2E_SETUP",setup_id,"","","",planned_payload);
   const bool ready_emitted=EmitHarnessEvent(
      "ENTRY_READY","G17_E2E_CONFIRMATION",setup_id,signal_id,"","",planned_payload);
   const int before=PositionsTotal();
   ExecutionReceipt opened;
   const bool submitted=HarnessBroker.Submit(plan,opened,reason);
   const string submit_reason=opened.reason;
   ManagedPosition discovered[];bool foreign=false;bool manual=false;
   const bool found=submitted && HarnessBroker.DiscoverOwnedPositions(
      discovered,foreign,manual,reason) && ArraySize(discovered)==1;
   ulong ticket=(found ? discovered[0].ticket : 0);
   HarnessActiveTicket=ticket;
   const string order_id=IntegerToString((long)opened.order_ticket);
   const string position_id=IntegerToString((long)ticket);
   const bool order_emitted=submitted && EmitHarnessEvent(
      "ORDER_SUBMITTED","ORDER_SENT",setup_id,signal_id,order_id,position_id,
      planned_payload);
   const bool opened_emitted=found && EmitHarnessEvent(
      "POSITION_OPENED","POSITION_OPENED",setup_id,signal_id,order_id,
      position_id,planned_payload);
   MqlTick tick;SymbolInfoTick(HarnessProfile.symbol,tick);
   const double modified_stop=LifecycleFloor(tick.bid-2.0,HarnessProfile.tick_size);
   PositionActionReceipt modified;
   const bool changed=found && HarnessBroker.ModifyOwnedPosition(
      ticket,modified_stop,plan.take_profit,modified,reason);
   const bool modified_emitted=changed && EmitHarnessEvent(
      "POSITION_MODIFIED","POSITION_MODIFIED",setup_id,signal_id,order_id,
      position_id,StringFormat(
         "{\"stop_loss\":%.8f,\"take_profit\":%.8f}",
         modified_stop,plan.take_profit));

   CExecutionBroker restarted;
   const bool restarted_ok=restarted.Initialize(HarnessProfile,true,reason);
   ManagedPosition recovered[];bool recovered_foreign=false;bool recovered_manual=false;
   const bool recovered_ok=restarted_ok && restarted.DiscoverOwnedPositions(
      recovered,recovered_foreign,recovered_manual,reason) &&
      ArraySize(recovered)==1 && recovered[0].ticket==ticket &&
      MathAbs(recovered[0].stop_loss-modified_stop)<=HarnessProfile.tick_size;
   PositionActionReceipt closed;
   const bool closed_ok=recovered_ok && restarted.CloseOwnedPosition(ticket,closed,reason);
   const bool closed_emitted=closed_ok && EmitHarnessEvent(
      "POSITION_CLOSED","POSITION_CLOSED",setup_id,signal_id,order_id,
      position_id,"{}");
   const int after=PositionsTotal();
   HarnessPassed=setup_emitted && ready_emitted && submitted &&
      opened.state==EXECUTION_SUBMIT_SENT && order_emitted && opened_emitted &&
      found && !foreign && !manual && changed &&
      modified.state==POSITION_ACTION_DONE && modified_emitted && recovered_ok &&
      !recovered_foreign && !recovered_manual && closed_ok &&
      closed.state==POSITION_ACTION_DONE && closed_emitted && after==before &&
      HarnessEventCount==6;

   if(!HarnessPassed && ticket>0 && PositionSelectByTicket(ticket))
     {
      PositionActionReceipt cleanup;
      restarted.CloseOwnedPosition(ticket,cleanup,reason);
     }
   Print("G14_EXECUTION_LIFECYCLE passed=",HarnessPassed,
         " initialized=true opened=",submitted,
         " discovered=",found," modified=",changed,
         " restarted=",recovered_ok," closed=",closed_ok,
         " positions_before=",before," positions_after=",after,
         " open_retcode=",opened.retcode,
         " reject_mask=",opened.reject_mask,
         " submit_reason=",submit_reason,
         " modify_retcode=",modified.retcode,
         " close_retcode=",closed.retcode,
         " magic=",HarnessProfile.magic,
         " chain_id=",HarnessChainId,
         " events=",HarnessEventCount,
         " spool=",HarnessOutbox.Path(),
         " order_authority=TESTER_ONLY reason=",reason);
   Print("G17_E2E passed=",HarnessPassed,
         " profile=",HarnessProfile.profile_id,
         " chain_id=",HarnessChainId,
         " setup_id=",setup_id,
         " signal_id=",signal_id,
         " order_id=",order_id,
         " position_id=",position_id,
         " events=",HarnessEventCount,
         " spool=",HarnessOutbox.Path(),
         " order_authority=TESTER_ONLY");
   if(closed_ok)
      HarnessActiveTicket=0;
  }

int OnInit(void)
  {
   LoadBuildProfile(HarnessProfile);
   HarnessChainId="G17|"+HarnessProfile.profile_id+"|"+
      IntegerToString((long)TimeCurrent());
   HarnessOutbox.Initialize(HarnessProfile);
   FileDelete(HarnessOutbox.Path(),FILE_COMMON);
   string reason="";
   const bool initialized=HarnessBroker.Initialize(HarnessProfile,true,reason);
   if(!initialized)
      Print("G14_EXECUTION_LIFECYCLE passed=false initialized=false reason=",reason);
   return initialized ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
   if(HarnessAttempted)
      return;
   MqlDateTime now;TimeToStruct(TimeCurrent(),now);
   if(now.hour<8 || now.hour>=23)
      return;
   HarnessAttempted=true;
   RunLifecycle();
  }

void OnDeinit(const int reason)
  {
   if(HarnessActiveTicket>0 && PositionSelectByTicket(HarnessActiveTicket))
     {
      string cleanup_reason="";PositionActionReceipt cleanup;
      HarnessBroker.CloseOwnedPosition(HarnessActiveTicket,cleanup,cleanup_reason);
     }
  }
