#ifndef GOLD_ENGINE_RUNTIME_MQH
#define GOLD_ENGINE_RUNTIME_MQH

#include "GoldEngineProfile.mqh"
#include "GoldEngineRevisedGeometry.mqh"
#include "GoldEngineRevised.mqh"
#include "GoldEngineRevisedSetup.mqh"
#include "GoldEngineBearPersistence.mqh"
#include "GoldEngineExecutionBroker.mqh"
#include "GoldEnginePositionPersistence.mqh"
#include "GoldEngineOutbox.mqh"
#include "GoldEngineInstanceLease.mqh"
#include "GoldEngineScheduler.mqh"

class CGoldEngineRuntime
  {
private:
   ProfileConfig       m_profile;
   StrategyState       m_state;
   CClosedBarScheduler m_scheduler;
   EngineEvent         m_last_event;
   CRevisedEngine      m_revised_engine;
   CRevisedSetupDetector m_revised_detector;
   RevisedDecision     m_last_revised_decision;
   bool                m_has_revised_decision;
   CBearIncrementalMachine m_bear_machine;
   CBearStateStore      m_bear_store;
   BearEntryPlan       m_last_bear_signal;
   bool                m_has_bear_signal;
   EngineBar           m_d1_history[];
   EngineBar           m_h1_history[];
   EngineBar           m_m15_history[];
   EngineBar           m_m5_history[];
   EngineBar           m_m1_history[];
   bool                m_initialized;
   bool                m_data_healthy;
   CExecutionBroker    m_execution_broker;
   ExecutionReceipt    m_last_execution_receipt;
   bool                m_has_execution_receipt;
   ManagedPosition     m_owned_positions[];
   bool                m_foreign_symbol_position;
   bool                m_manual_intervention;
   CPositionStateStore m_position_store;
   ExpectedPositionState m_expected_position;
   PositionStateLoadStatus m_position_state_status;
   CEngineOutbox       m_outbox;
   bool                m_outbox_initialized;
   ulong               m_last_bar_close_to_detection_ms;
   ulong               m_last_detection_to_decision_us;
   ulong               m_last_entry_ready_to_submit_us;
   ulong               m_next_heartbeat_due_ms;
   CEngineInstanceLease m_instance_lease;

   string RuntimeEvidencePayload(void) const
     {
      return StringFormat(
         "{\"account_login\":%I64d,\"account_server\":\"%s\","
         "\"trade_mode\":%d,\"order_authority\":\"%s\"}",
         AccountInfoInteger(ACCOUNT_LOGIN),
         OutboxJsonEscape(AccountInfoString(ACCOUNT_SERVER)),
         (int)AccountInfoInteger(ACCOUNT_TRADE_MODE),
         m_execution_broker.AuthorityEnabled() ? "ENABLED" : "DISABLED");
     }

   void EmitTransition(const string event_type,
                       const string setup_id="",
                       const string signal_id="",
                       const string order_id="",
                       const string position_id="",
                       const string payload="{}")
     {
      if(m_outbox_initialized)
         m_outbox.Emit(event_type,m_last_event,setup_id,signal_id,
                       order_id,position_id,payload);
     }

   void MaybeEmitHeartbeat(const datetime server_time)
     {
      const ulong now_ms=GetTickCount64();
      if(m_next_heartbeat_due_ms==0 || now_ms<m_next_heartbeat_due_ms)
         return;
      m_next_heartbeat_due_ms=now_ms+3600000;
      SetEvent(ENGINE_EVENT_HEARTBEAT,server_time,"ENGINE_HEALTHY");
     }

   bool PersistSubmittedPosition(const SignalPlan &plan,
                                 const datetime server_time)
     {
      string reason="";
      if(!m_execution_broker.DiscoverOwnedPositions(
            m_owned_positions,m_foreign_symbol_position,
            m_manual_intervention,reason))
        {
         SetEvent(ENGINE_EVENT_ERROR,server_time,reason);
         return false;
        }
      if(m_foreign_symbol_position || m_manual_intervention ||
         ArraySize(m_owned_positions)!=1)
        {
         m_execution_broker.DisableAuthority();
         SetEvent(ENGINE_EVENT_ERROR,server_time,
            "POSITION_CAPTURE_AMBIGUOUS");
         return false;
        }
      const ManagedPosition position=m_owned_positions[0];
      PositionStateReset(m_expected_position);
      m_expected_position.active=true;
      m_expected_position.ticket=position.ticket;
      m_expected_position.signal_id=plan.signal_id;
      m_expected_position.volume=position.volume;
      m_expected_position.entry_price=position.entry_price;
      m_expected_position.stop_loss=position.stop_loss;
      m_expected_position.take_profit=position.take_profit;
      if(!m_position_store.Save(m_expected_position))
        {
         m_execution_broker.DisableAuthority();
         SetEvent(ENGINE_EVENT_ERROR,server_time,
            "POSITION_STATE_SAVE_FAILED");
         return false;
        }
      m_position_state_status=POSITION_STATE_VALID;
      return true;
     }

   void BuildSignalPlan(const EngineSide side,
                        const string setup_id,
                        const string signal_id,
                        const datetime setup_created_at,
                        const datetime entry_ready_at,
                        const double entry,
                        const double stop_loss,
                        const double take_profit,
                        SignalPlan &plan)
     {
      ZeroMemory(plan);
      plan.profile_id=m_profile.profile_id;
      plan.profile_version=m_profile.profile_version;
      plan.profile_fingerprint=m_profile.profile_fingerprint;
      plan.strategy_version=m_profile.strategy_version;
      plan.setup_id=setup_id;
      plan.signal_id=signal_id;
      plan.symbol=m_profile.symbol;
      plan.side=side;
      plan.account_login=AccountInfoInteger(ACCOUNT_LOGIN);
      plan.account_server=AccountInfoString(ACCOUNT_SERVER);
      plan.trade_mode=(ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
      plan.terminal_identity=m_profile.terminal_identity;
      plan.magic=m_profile.magic;
      plan.setup_created_at=setup_created_at;
      plan.entry_ready_at=entry_ready_at;
      plan.valid_until=entry_ready_at+m_profile.maximum_signal_age_seconds;
      plan.volume=ResolveProfileLot(m_profile,AccountInfoDouble(ACCOUNT_BALANCE));
      plan.tick_size=m_profile.tick_size;
      plan.maximum_drift_r=m_profile.maximum_drift_r;
      plan.maximum_spread=m_profile.maximum_spread;
      plan.planned_entry=entry;
      plan.stop_loss=stop_loss;
      plan.take_profit=take_profit;
      plan.invalidation=stop_loss;
      plan.risk_price=MathAbs(entry-stop_loss);
      plan.executable=plan.volume>0.0 && plan.risk_price>0.0;
      // The GOLDM engineering exception remains unreachable outside Strategy
      // Tester: no input or persisted state can enable this flag live.
      plan.engineering_tester=(bool)MQLInfoInteger(MQL_TESTER);
     }

   void SubmitSignalPlan(const SignalPlan &plan,
                         const datetime server_time,
                         const ulong entry_ready_started_us)
     {
      if(!RecoverOwnedPositions(server_time))
         return;
      if(ArraySize(m_owned_positions)>0)
        {
         SetEvent(ENGINE_EVENT_ENTRY_READY,server_time,
            "POSITION_ALREADY_OPEN");
         return;
        }
      string reason="";
      m_last_entry_ready_to_submit_us=
         GetMicrosecondCount()-entry_ready_started_us;
      m_has_execution_receipt=true;
      const bool submitted=m_execution_broker.Submit(
         plan,m_last_execution_receipt,reason);
      if(submitted)
        {
         if(!PersistSubmittedPosition(plan,server_time))
            return;
         m_state.phase=ENGINE_PHASE_POSITION_OPEN;
         SetEvent(ENGINE_EVENT_POSITION,server_time,"ORDER_SENT");
         const string latency_payload=StringFormat(
            "{\"bar_close_to_detection_ms\":%I64u,"
            "\"detection_to_decision_us\":%I64u,"
            "\"entry_ready_to_submit_us\":%I64u,"
            "\"submit_to_broker_ack_us\":%I64u}",
            m_last_bar_close_to_detection_ms,
            m_last_detection_to_decision_us,
            m_last_entry_ready_to_submit_us,
            m_last_execution_receipt.submit_to_broker_ack_us);
         EmitTransition("POSITION_OPENED",plan.setup_id,plan.signal_id,
            IntegerToString((long)m_last_execution_receipt.order_ticket),
            IntegerToString((long)m_expected_position.ticket),latency_payload);
         return;
        }
      if(m_last_execution_receipt.state==EXECUTION_SUBMIT_DISABLED)
        {
         SetEvent(ENGINE_EVENT_ENTRY_READY,server_time,"ORDER_AUTHORITY_DISABLED");
         return;
        }
      SetEvent(ENGINE_EVENT_ERROR,server_time,reason);
     }

   bool RecoverOwnedPositions(const datetime server_time)
     {
      string reason="";
      if(!m_execution_broker.DiscoverOwnedPositions(
            m_owned_positions,m_foreign_symbol_position,
            m_manual_intervention,reason))
        {
         SetEvent(ENGINE_EVENT_ERROR,server_time,reason);
         return false;
        }
      if(m_foreign_symbol_position || m_manual_intervention)
        {
         m_execution_broker.DisableAuthority();
         SetEvent(ENGINE_EVENT_ERROR,server_time,
            m_manual_intervention ? "MANUAL_INTERVENTION_DETECTED" :
            "FOREIGN_SYMBOL_POSITION_DETECTED");
         return true;
        }
      m_position_state_status=m_position_store.Load(m_expected_position);
      if(m_position_state_status==POSITION_STATE_INVALID)
        {
         m_execution_broker.DisableAuthority();
         m_manual_intervention=true;
         SetEvent(ENGINE_EVENT_ERROR,server_time,"POSITION_STATE_INVALID");
         return true;
        }
      const int owned_count=ArraySize(m_owned_positions);
      if(owned_count>1)
        {
         m_execution_broker.DisableAuthority();
         m_manual_intervention=true;
         SetEvent(ENGINE_EVENT_ERROR,server_time,"MULTIPLE_OWNED_POSITIONS");
         return true;
        }
      if(owned_count==1)
        {
         if(m_position_state_status!=POSITION_STATE_VALID ||
            !m_expected_position.active)
           {
            m_execution_broker.DisableAuthority();
            m_manual_intervention=true;
            SetEvent(ENGINE_EVENT_ERROR,server_time,
               "POSITION_STATE_MISSING");
            return true;
           }
         if(!PositionStateMatches(
               m_owned_positions[0],m_expected_position,
               m_profile.tick_size,reason))
           {
            m_execution_broker.DisableAuthority();
            m_manual_intervention=true;
            SetEvent(ENGINE_EVENT_ERROR,server_time,reason);
            return true;
           }
         m_state.phase=ENGINE_PHASE_POSITION_OPEN;
         SetEvent(ENGINE_EVENT_POSITION,server_time,"POSITION_RECOVERED");
        }
      else
        {
         if(m_position_state_status==POSITION_STATE_VALID &&
            m_expected_position.active &&
            !m_position_store.Clear(m_expected_position))
           {
            m_execution_broker.DisableAuthority();
            SetEvent(ENGINE_EVENT_ERROR,server_time,
               "POSITION_STATE_CLEAR_FAILED");
            return false;
           }
         m_state.phase=ENGINE_PHASE_IDLE;
        }
      return true;
     }

   void CopyLatestBars(const EngineBar &source[],
                       const int maximum,
                       EngineBar &result[])
     {
      const int count=ArraySize(source);
      const int start=MathMax(0,count-maximum);
      ArrayResize(result,count-start);
      for(int index=start;index<count;index++)
         result[index-start]=source[index];
     }

   void SetEvent(const EngineEventType type,const datetime server_time,const string reason)
     {
      m_last_event.type=type;
      m_last_event.profile_id=m_profile.profile_id;
      m_last_event.server_time=server_time;
      m_last_event.reason=reason;
      m_last_event.event_id=
         m_profile.profile_id+"-"+IntegerToString((long)type)+"-"+
         IntegerToString((long)server_time);
      if(type==ENGINE_EVENT_RUNTIME_READY)
        {
         const string payload=RuntimeEvidencePayload();
         EmitTransition("ENGINE_STARTED","","","","",payload);
         EmitTransition("PROFILE_VALIDATED","","","","",payload);
        }
      else if(type==ENGINE_EVENT_HEARTBEAT)
         EmitTransition("ENGINE_HEARTBEAT","","","","",RuntimeEvidencePayload());
      else if(type==ENGINE_EVENT_ENTRY_READY)
         EmitTransition("ENTRY_READY",m_state.setup_id);
      else if(type==ENGINE_EVENT_POSITION)
        {
         if(reason=="ORDER_SENT") EmitTransition("ORDER_SUBMITTED");
         else if(reason=="POSITION_MODIFIED") EmitTransition("POSITION_MODIFIED");
         else if(reason=="POSITION_CLOSED") EmitTransition("POSITION_CLOSED");
         else if(reason=="POSITION_RECOVERED") EmitTransition("RECOVERY_COMPLETED");
        }
      else if(type==ENGINE_EVENT_ERROR)
         EmitTransition("ENGINE_ERROR");
     }

   bool LoadHistory(const ENUM_TIMEFRAMES timeframe,
                    const int required_bars,
                    EngineBar &history[])
     {
      if(required_bars<=0 || required_bars>512)
         return false;
      MqlRates rates[];
      ArraySetAsSeries(rates,true);
      if(CopyRates(m_profile.symbol,timeframe,1,required_bars,rates)!=required_bars)
         return false;
      ArrayResize(history,required_bars);
      const int seconds=PeriodSeconds(timeframe);
      for(int index=0;index<required_bars;index++)
        {
         const MqlRates rate=rates[required_bars-index-1];
         history[index].timeframe=timeframe;
         history[index].open_time=rate.time;
         history[index].close_time=rate.time+seconds;
         history[index].open=rate.open;
         history[index].high=rate.high;
         history[index].low=rate.low;
         history[index].close=rate.close;
         history[index].tick_volume=rate.tick_volume;
         history[index].spread_points=rate.spread;
        }
      return true;
     }

   bool Warmup(void)
     {
      if(!LoadHistory(PERIOD_D1,30,m_d1_history))
         return false;
      if(!LoadHistory(PERIOD_H1,200,m_h1_history))
         return false;
      if(!LoadHistory(PERIOD_M15,300,m_m15_history))
         return false;
      if(!LoadHistory(PERIOD_M5,300,m_m5_history))
         return false;
      if(!LoadHistory(PERIOD_M1,300,m_m1_history))
         return false;
      m_state.warmed=true;
      return true;
     }

   void AppendBounded(EngineBar &history[],
                      const EngineBar &bar,
                      const int maximum)
     {
      const int count=ArraySize(history);
      if(count>0 && bar.open_time<=history[count-1].open_time)
         return;
      if(count<maximum)
        {
         ArrayResize(history,count+1);
         history[count]=bar;
         return;
        }
      for(int index=1;index<count;index++)
         history[index-1]=history[index];
      history[count-1]=bar;
     }

   void BuildRevisedSnapshot(const EngineSide side,
                             const RevisedM5Setup &setup,
                             CRevisedSnapshot &snapshot)
     {
      snapshot.symbol=m_profile.symbol;
      snapshot.side=side;
      const int m1_count=ArraySize(m_m1_history);
      snapshot.current_time=(m1_count>0 ?
                             m_m1_history[m1_count-1].open_time :
                             TimeCurrent());
      ArrayCopy(snapshot.m1_bars,m_m1_history);
      ArrayCopy(snapshot.m5_bars,m_m5_history);
      ArrayCopy(snapshot.h1_bars,m_h1_history);
      ArrayCopy(snapshot.d1_bars,m_d1_history);
      snapshot.m5_trigger_time=setup.trigger_time;
      snapshot.m5_pattern=setup.pattern;
      snapshot.m5_votes=setup.votes;
      snapshot.confidence=setup.confidence;
      snapshot.level=setup.level;
      snapshot.has_level=true;
      snapshot.invalidation=setup.invalidation;
      snapshot.has_invalidation=true;
      snapshot.entry=0.0;
      snapshot.has_entry=false;
      snapshot.stop=0.0;
      snapshot.has_stop=false;
     }

   void EvaluateRevisedSide(const EngineSide side)
     {
      const int m1_count=ArraySize(m_m1_history);
      if(m1_count==0)
         return;
      const datetime current_m1_time=m_m1_history[m1_count-1].open_time;
      RevisedM5Setup setup;
      if(!m_revised_detector.Update(
            m_m5_history,current_m1_time,side,setup))
        {
         string termination_reason="";
         if(!m_revised_detector.PopTermination(
               side,setup,termination_reason))
            return;
         CRevisedSnapshot terminal_snapshot;
         BuildRevisedSnapshot(side,setup,terminal_snapshot);
         m_revised_engine.TerminalDecision(
            terminal_snapshot,termination_reason,m_last_revised_decision);
         m_has_revised_decision=true;
         return;
        }

      CRevisedSnapshot snapshot;
      BuildRevisedSnapshot(side,setup,snapshot);
      string error="";
      if(!m_revised_engine.Evaluate(snapshot,m_last_revised_decision,error))
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),error);
         return;
        }
      m_has_revised_decision=true;
      if(m_last_revised_decision.state==REVISED_STATE_ENTRY_READY)
        {
         SetEvent(
            ENGINE_EVENT_ENTRY_READY,m_last_revised_decision.time,
            m_last_revised_decision.reason);
         m_revised_detector.Consume(side,setup.trigger_time);
         if(!m_last_revised_decision.observation_only &&
            m_last_revised_decision.has_entry &&
            m_last_revised_decision.has_stop &&
            m_last_revised_decision.has_target)
           {
            const ulong entry_ready_started_us=GetMicrosecondCount();
            const string setup_id=m_profile.profile_id+":REVISED:"+
               IntegerToString((long)side)+":"+
               IntegerToString((long)setup.trigger_time);
            const string signal_id=setup_id+":"+
               IntegerToString((long)m_last_revised_decision.time);
            SignalPlan plan;
            BuildSignalPlan(side,setup_id,signal_id,setup.trigger_time,
               m_last_revised_decision.time,m_last_revised_decision.entry,
               m_last_revised_decision.stop,m_last_revised_decision.target,plan);
            SubmitSignalPlan(
               plan,m_last_revised_decision.time,entry_ready_started_us);
           }
        }
      else if(m_last_revised_decision.state==REVISED_STATE_CANCELLED)
         m_revised_detector.Consume(side,setup.trigger_time);
     }

   void EvaluateBearBar(const EngineBar &bar)
     {
      BearSetup candidate;
      ZeroMemory(candidate);
      bool has_candidate=false;
      if(bar.timeframe==PERIOD_M15)
        {
         EngineBar scanner_bars[];
         CopyLatestBars(m_m15_history,50,scanner_bars);
         string scanner_reason="";
         has_candidate=BearM15Setup(
            scanner_bars,m_profile.symbol,
            m_profile.profile_id=="GOLDM" ? 0.24 : 0.20,
            candidate,scanner_reason);
        }
      BearIncrementalEvent events[];
      BearEntryPlan signal;
      bool has_signal=false;
      string error="";
      if(!m_bear_machine.OnBarClose(
            bar.timeframe,bar,has_candidate,candidate,
            events,signal,has_signal,error))
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_ERROR,bar.close_time,error);
         return;
        }
      if(has_signal)
        {
         const ulong entry_ready_started_us=GetMicrosecondCount();
         m_last_bear_signal=signal;
         m_has_bear_signal=true;
         SetEvent(
            ENGINE_EVENT_ENTRY_READY,signal.opened_at,
            "M1_ENTRY_CONFIRMATION_READY");
         const string setup_id=m_bear_machine.SetupId();
         const string signal_id=setup_id+":"+
            IntegerToString((long)signal.opened_at);
         SignalPlan plan;
         BuildSignalPlan(ENGINE_SIDE_SELL,setup_id,signal_id,
            signal.armed_at,signal.opened_at,signal.entry,signal.stop,
            signal.target,plan);
         SubmitSignalPlan(plan,signal.opened_at,entry_ready_started_us);
        }
      else if(ArraySize(events)>0)
        {
         const BearIncrementalEvent latest=events[ArraySize(events)-1];
         SetEvent(ENGINE_EVENT_BAR_CLOSED,latest.available_at,latest.reason);
        }
      if(!m_bear_store.Save(
            m_profile.profile_id,m_profile.profile_fingerprint,m_bear_machine))
        {
         m_data_healthy=false;
         SetEvent(
            ENGINE_EVENT_ERROR,bar.close_time,"BEAR_STATE_SAVE_FAILED");
        }
     }

   void DispatchClosedBar(const EngineBar &bar)
     {
      m_state.bars_processed++;
      SetEvent(ENGINE_EVENT_BAR_CLOSED,bar.close_time,
               EnumToString(bar.timeframe));
      if(bar.timeframe==PERIOD_D1)
         AppendBounded(m_d1_history,bar,64);
      else if(bar.timeframe==PERIOD_H1)
         AppendBounded(m_h1_history,bar,256);
      else if(bar.timeframe==PERIOD_M15)
         AppendBounded(m_m15_history,bar,512);
      else if(bar.timeframe==PERIOD_M5)
         AppendBounded(m_m5_history,bar,512);
      else if(bar.timeframe==PERIOD_M1)
        {
         AppendBounded(m_m1_history,bar,512);
         EvaluateBearBar(bar);
         if(!m_data_healthy)
            return;
         EvaluateRevisedSide(ENGINE_SIDE_BUY);
         if(m_data_healthy)
            EvaluateRevisedSide(ENGINE_SIDE_SELL);
        }
      else
         return;
      if(bar.timeframe==PERIOD_H1 ||
         bar.timeframe==PERIOD_M15 ||
         bar.timeframe==PERIOD_M5)
         EvaluateBearBar(bar);
     }

   void CheckActiveSetupTick(const EngineTick &tick)
     {
      // Bounded live-tick hook. No strategy or order authority exists in G11.
      if(tick.time_msc<=0)
         m_data_healthy=false;
     }

public:
   CGoldEngineRuntime(void)
     {
      m_initialized=false;
      m_data_healthy=false;
      m_state.phase=ENGINE_PHASE_IDLE;
      m_state.warmed=false;
      m_state.active_setup=false;
      m_state.setup_created_at=0;
      m_state.bars_processed=0;
      m_state.setup_id="";
      m_last_event.type=ENGINE_EVENT_NONE;
      m_has_revised_decision=false;
      m_has_bear_signal=false;
      m_has_execution_receipt=false;
      m_foreign_symbol_position=false;
      m_manual_intervention=false;
      m_outbox_initialized=false;
      m_last_bar_close_to_detection_ms=0;
      m_last_detection_to_decision_us=0;
      m_last_entry_ready_to_submit_us=0;
      m_next_heartbeat_due_ms=0;
      m_position_state_status=POSITION_STATE_MISSING;
      PositionStateReset(m_expected_position);
     }

   int Initialize(const long expected_login,
                  const string expected_server,
                  const bool order_authority_requested=false)
     {
      LoadBuildProfile(m_profile);
      string reason="";
      if(!ValidateBuildProfile(m_profile,expected_login,expected_server,reason))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=",reason);
         return INIT_FAILED;
        }
      if(!m_instance_lease.Acquire(
            m_profile,AccountInfoInteger(ACCOUNT_LOGIN),reason))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=",reason);
         return INIT_FAILED;
        }
      if(!Warmup())
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=WARMUP_INCOMPLETE");
         return INIT_FAILED;
        }
      if(!m_scheduler.Initialize(m_profile.symbol))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=SCHEDULER_INIT_FAILED");
         return INIT_FAILED;
        }
      if(!m_execution_broker.Initialize(
            m_profile,order_authority_requested,reason))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=",reason);
         return INIT_FAILED;
        }
      m_position_store.Initialize(
         m_profile.profile_id,m_profile.profile_fingerprint);
      m_outbox_initialized=m_outbox.Initialize(m_profile);

      m_revised_engine.Initialize(m_profile.symbol);
      m_revised_detector.SetMaximumAgeBars(60);
      const datetime bear_as_of=(ArraySize(m_h1_history)>0 ?
         m_h1_history[0].open_time : TimeCurrent());
      if(!m_bear_machine.Initialize(
            m_profile.profile_id,m_profile.symbol,
            m_profile.profile_id=="GOLDM" ? 0.24 : 0.20,
            bear_as_of,BearBrokerUtcOffsetMinutes(TimeCurrent())))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=BEAR_MACHINE_INIT_FAILED");
         return INIT_FAILED;
        }
      const BearStateLoadStatus bear_load=m_bear_store.Load(
         m_profile.profile_id,m_profile.symbol,m_profile.profile_fingerprint,
         TimeCurrent(),180,m_bear_machine);
      if(bear_load==BEAR_STATE_INVALID)
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=BEAR_STATE_INVALID");
         return INIT_FAILED;
        }
      if((bear_load==BEAR_STATE_MISSING || bear_load==BEAR_STATE_STALE) &&
         !m_bear_machine.SeedClosedHistory(
            m_m1_history,m_m5_history,m_m15_history,m_h1_history))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=BEAR_WARMUP_INCOMPLETE");
         return INIT_FAILED;
        }
      m_data_healthy=true;
      m_initialized=true;
      const int m5_count=ArraySize(m_m5_history);
      if(m5_count>0)
         m_revised_detector.SeedWarmup(
            m_m5_history[m5_count-1].open_time);
      SetEvent(ENGINE_EVENT_RUNTIME_READY,TimeCurrent(),"WARMUP_COMPLETE");
      if(!RecoverOwnedPositions(TimeCurrent()))
         return INIT_FAILED;
      // Health evidence must remain live while the market is closed and no
      // ticks arrive. The timer only emits observability events; strategy and
      // execution remain exclusively tick/closed-bar driven.
      m_next_heartbeat_due_ms=GetTickCount64()+60000;
      if(!EventSetTimer(1))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=HEARTBEAT_TIMER_FAILED");
         return INIT_FAILED;
        }
      Print("GOLD_ENGINE_READY profile=",m_profile.profile_id,
            " fingerprint=",m_profile.profile_fingerprint,
            " order_authority=",
            m_execution_broker.AuthorityEnabled() ? "ENABLED" : "DISABLED");
      return INIT_SUCCEEDED;
     }

   void OnTick(void)
     {
      if(!m_initialized || !m_data_healthy)
         return;

      MqlTick raw_tick;
      if(!SymbolInfoTick(m_profile.symbol,raw_tick))
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),"TICK_UNAVAILABLE");
         return;
        }
      EngineTick tick;
      tick.time_msc=raw_tick.time_msc;
      tick.bid=raw_tick.bid;
      tick.ask=raw_tick.ask;
      tick.last=raw_tick.last;

      MaybeEmitHeartbeat(raw_tick.time);

      EngineBar closed_bars[];
      int bar_count=0;
      bool gap_detected=false;
      if(!m_scheduler.Poll(closed_bars,bar_count,gap_detected))
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),"SCHEDULER_POLL_FAILED");
         return;
        }
      if(gap_detected)
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_DATA_GAP,TimeCurrent(),"CLOSED_BAR_GAP");
         Print("GOLD_ENGINE_FAIL_CLOSED profile=",m_profile.profile_id,
               " reason=CLOSED_BAR_GAP");
         return;
        }

      for(int index=0;index<bar_count;index++)
        {
         const long closed_at_msc=(long)closed_bars[index].close_time*1000;
         m_last_bar_close_to_detection_ms=
            raw_tick.time_msc>closed_at_msc ?
            (ulong)(raw_tick.time_msc-closed_at_msc) : 0;
         const ulong decision_started_us=GetMicrosecondCount();
         DispatchClosedBar(closed_bars[index]);
         m_last_detection_to_decision_us=
            GetMicrosecondCount()-decision_started_us;
        }

      if(m_state.active_setup)
         CheckActiveSetupTick(tick);
     }

   void OnTimer(void)
     {
      if(!m_initialized || !m_data_healthy)
         return;
      MaybeEmitHeartbeat(TimeCurrent());
     }

   void Deinitialize(const int reason)
     {
      EventKillTimer();
      if(m_initialized)
         m_bear_store.Save(
            m_profile.profile_id,m_profile.profile_fingerprint,m_bear_machine);
      m_instance_lease.Release();
      m_initialized=false;
      m_data_healthy=false;
      Print("GOLD_ENGINE_STOP profile=",m_profile.profile_id,
            " reason=",reason);
     }

   void OnTradeTransaction(const MqlTradeTransaction &transaction,
                           const MqlTradeRequest &request,
                           const MqlTradeResult &result)
     {
      if(!m_initialized)
         return;
      if(transaction.symbol!="" && transaction.symbol!=m_profile.symbol)
         return;
      RecoverOwnedPositions(TimeCurrent());
     }

   bool ModifyOwnedPosition(const ulong ticket,
                            const double stop_loss,
                            const double take_profit,
                            PositionActionReceipt &receipt)
     {
      string reason="";
      if(m_manual_intervention ||
         !m_execution_broker.ModifyOwnedPosition(
            ticket,stop_loss,take_profit,receipt,reason))
         return false;
      if(!m_execution_broker.DiscoverOwnedPositions(
            m_owned_positions,m_foreign_symbol_position,
            m_manual_intervention,reason) ||
         ArraySize(m_owned_positions)!=1 ||
         m_owned_positions[0].ticket!=ticket)
        {
         m_execution_broker.DisableAuthority();
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),
            "POSITION_MODIFY_RECOVERY_FAILED");
         return false;
        }
      const ManagedPosition position=m_owned_positions[0];
      m_expected_position.active=true;
      m_expected_position.ticket=position.ticket;
      m_expected_position.volume=position.volume;
      m_expected_position.entry_price=position.entry_price;
      m_expected_position.stop_loss=position.stop_loss;
      m_expected_position.take_profit=position.take_profit;
      if(!m_position_store.Save(m_expected_position))
        {
         m_execution_broker.DisableAuthority();
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),
            "POSITION_STATE_SAVE_FAILED");
         return false;
        }
      SetEvent(ENGINE_EVENT_POSITION,TimeCurrent(),"POSITION_MODIFIED");
      return true;
     }

   bool CloseOwnedPosition(const ulong ticket,PositionActionReceipt &receipt)
     {
      string reason="";
      if(m_manual_intervention ||
         !m_execution_broker.CloseOwnedPosition(ticket,receipt,reason))
         return false;
      if(!m_position_store.Clear(m_expected_position))
        {
         m_execution_broker.DisableAuthority();
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),
            "POSITION_STATE_CLEAR_FAILED");
         return false;
        }
      ArrayResize(m_owned_positions,0);
      m_state.phase=ENGINE_PHASE_IDLE;
      SetEvent(ENGINE_EVENT_POSITION,TimeCurrent(),"POSITION_CLOSED");
      return true;
     }

   bool OrderAuthorityEnabled(void) const
     {
      return m_execution_broker.AuthorityEnabled();
     }

   bool ManualInterventionDetected(void) const
     {
     return m_manual_intervention;
     }

   bool OutboxHealthy(void) const
     {
      return m_outbox_initialized && m_outbox.Healthy();
     }

   long BarsProcessed(void) const
     {
      return m_state.bars_processed;
     }

   bool IsDataHealthy(void) const
     {
      return m_data_healthy;
     }

   bool HasRevisedDecision(void) const
     {
      return m_has_revised_decision;
     }

   RevisedDecision LastRevisedDecision(void) const
     {
      return m_last_revised_decision;
     }

   bool HasBearSignal(void) const
     {
      return m_has_bear_signal;
     }

   BearEntryPlan LastBearSignal(void) const
     {
      return m_last_bear_signal;
     }

   BearIncrementalPhase BearPhase(void) const
     {
      return m_bear_machine.Phase();
     }

   ulong LastBarCloseToDetectionMs(void) const
     {
      return m_last_bar_close_to_detection_ms;
     }

   ulong LastDetectionToDecisionUs(void) const
     {
      return m_last_detection_to_decision_us;
     }

   ulong LastEntryReadyToSubmitUs(void) const
     {
      return m_last_entry_ready_to_submit_us;
     }
  };

#endif
