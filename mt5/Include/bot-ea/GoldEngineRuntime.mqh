#ifndef GOLD_ENGINE_RUNTIME_MQH
#define GOLD_ENGINE_RUNTIME_MQH

#include "GoldEngineProfile.mqh"
#include "GoldEngineRevisedContext.mqh"
#include "GoldEngineScheduler.mqh"

class CGoldEngineRuntime
  {
private:
   ProfileConfig       m_profile;
   StrategyState       m_state;
   CClosedBarScheduler m_scheduler;
   EngineEvent         m_last_event;
   bool                m_initialized;
   bool                m_data_healthy;

   void SetEvent(const EngineEventType type,const datetime server_time,const string reason)
     {
      m_last_event.type=type;
      m_last_event.profile_id=m_profile.profile_id;
      m_last_event.server_time=server_time;
      m_last_event.reason=reason;
      m_last_event.event_id=
         m_profile.profile_id+"-"+IntegerToString((long)type)+"-"+
         IntegerToString((long)server_time);
     }

   bool LoadWarmup(const ENUM_TIMEFRAMES timeframe,const int required_bars)
     {
      if(required_bars<=0 || required_bars>512)
         return false;
      MqlRates rates[];
      ArraySetAsSeries(rates,true);
      return CopyRates(m_profile.symbol,timeframe,1,required_bars,rates)==required_bars;
     }

   bool Warmup(void)
     {
      if(!LoadWarmup(PERIOD_D1,30))
         return false;
      if(!LoadWarmup(PERIOD_H1,200))
         return false;
      if(!LoadWarmup(PERIOD_M15,300))
         return false;
      if(!LoadWarmup(PERIOD_M5,300))
         return false;
      if(!LoadWarmup(PERIOD_M1,300))
         return false;
      m_state.warmed=true;
      return true;
     }

   void DispatchClosedBar(const EngineBar &bar)
     {
      // G11 dispatches state only. Strategy semantics are introduced at G12/G13.
      m_state.bars_processed++;
      SetEvent(ENGINE_EVENT_BAR_CLOSED,bar.close_time,
               EnumToString(bar.timeframe));
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
     }

   int Initialize(const long expected_login,const string expected_server)
     {
      LoadBuildProfile(m_profile);
      string reason="";
      if(!ValidateBuildProfile(m_profile,expected_login,expected_server,reason))
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

      m_data_healthy=true;
      m_initialized=true;
      SetEvent(ENGINE_EVENT_RUNTIME_READY,TimeCurrent(),"WARMUP_COMPLETE");
      Print("GOLD_ENGINE_READY profile=",m_profile.profile_id,
            " fingerprint=",m_profile.profile_fingerprint,
            " order_authority=DISABLED");
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
         DispatchClosedBar(closed_bars[index]);

      if(m_state.active_setup)
         CheckActiveSetupTick(tick);
     }

   void Deinitialize(const int reason)
     {
      m_initialized=false;
      m_data_healthy=false;
      Print("GOLD_ENGINE_STOP profile=",m_profile.profile_id,
            " reason=",reason);
     }

   long BarsProcessed(void) const
     {
      return m_state.bars_processed;
     }

   bool IsDataHealthy(void) const
     {
      return m_data_healthy;
     }
  };

#endif
