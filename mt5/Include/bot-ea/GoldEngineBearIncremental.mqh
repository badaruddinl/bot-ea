#ifndef GOLD_ENGINE_BEAR_INCREMENTAL_MQH
#define GOLD_ENGINE_BEAR_INCREMENTAL_MQH

#include "GoldEngineBearValidation.mqh"
#include "GoldEngineBearSetup.mqh"

class CBearIncrementalSnapshot
  {
public:
   string               profile_id;
   string               symbol;
   int                  utc_offset_minutes;
   BearIncrementalPhase phase;
   long                 sequence;
   datetime             as_of;
   string               setup_id;
   datetime             setup_time;
   datetime             last_setup_time;
   bool                 has_setup;
   BearSetup            setup;
   bool                 has_arm;
   BearM5Result         arm;
   bool                 has_signal;
   BearEntryPlan        signal;
   int                  touches;
   int                  rejections;
   bool                 acceptance;
   datetime             last_m1;
   datetime             last_m5;
   datetime             last_m15;
   datetime             last_h1;
   EngineBar            m1_bars[];
   EngineBar            m5_bars[];
   EngineBar            m15_bars[];
   EngineBar            h1_bars[];
  };

class CBearIncrementalMachine
  {
private:
   string               m_profile_id;
   string               m_symbol;
   int                  m_utc_offset_minutes;
   BearV4Config         m_config;
   BearIncrementalPhase m_phase;
   long                 m_sequence;
   datetime             m_as_of;
   string               m_setup_id;
   datetime             m_setup_time;
   datetime             m_last_setup_time;
   bool                 m_has_setup;
   BearSetup            m_setup;
   bool                 m_has_arm;
   BearM5Result         m_arm;
   bool                 m_has_signal;
   BearEntryPlan        m_signal;
   int                  m_touches;
   int                  m_rejections;
   bool                 m_acceptance;
   datetime             m_last_m1;
   datetime             m_last_m5;
   datetime             m_last_m15;
   datetime             m_last_h1;
   EngineBar            m_m1_bars[];
   EngineBar            m_m5_bars[];
   EngineBar            m_m15_bars[];
   EngineBar            m_h1_bars[];

   string IsoSemanticTime(const datetime value) const
     {
      MqlDateTime parts;
      TimeToStruct(value,parts);
      const int absolute_minutes=MathAbs(m_utc_offset_minutes);
      const int offset_hours=absolute_minutes/60;
      const int offset_minutes=absolute_minutes%60;
      const string sign=m_utc_offset_minutes>=0 ? "+" : "-";
      return StringFormat(
         "%04d-%02d-%02dT%02d:%02d:%02d%s%02d:%02d",
         parts.year,parts.mon,parts.day,parts.hour,parts.min,parts.sec,
         sign,offset_hours,offset_minutes);
     }

   int Limit(const ENUM_TIMEFRAMES timeframe) const
     {
      if(timeframe==PERIOD_M1)
         return 45;
      if(timeframe==PERIOD_M5)
         return 40;
      if(timeframe==PERIOD_M15)
         return 128;
      return 23;
     }

   datetime Cursor(const ENUM_TIMEFRAMES timeframe) const
     {
      if(timeframe==PERIOD_M1)
         return m_last_m1;
      if(timeframe==PERIOD_M5)
         return m_last_m5;
      if(timeframe==PERIOD_M15)
         return m_last_m15;
      return m_last_h1;
     }

   void SetCursor(const ENUM_TIMEFRAMES timeframe,const datetime value)
     {
      if(timeframe==PERIOD_M1)
         m_last_m1=value;
      else if(timeframe==PERIOD_M5)
         m_last_m5=value;
      else if(timeframe==PERIOD_M15)
         m_last_m15=value;
      else
         m_last_h1=value;
     }

   bool Supported(const ENUM_TIMEFRAMES timeframe) const
     {
      return timeframe==PERIOD_M1 || timeframe==PERIOD_M5 ||
             timeframe==PERIOD_M15 || timeframe==PERIOD_H1;
     }

   bool SnapshotCursorValid(const EngineBar &bars[],
                            const ENUM_TIMEFRAMES timeframe,
                            const datetime cursor) const
     {
      const int count=ArraySize(bars);
      if(count>Limit(timeframe))
         return false;
      if(count==0)
         return cursor==0;
      if(cursor!=bars[count-1].open_time)
         return false;
      for(int index=0;index<count;index++)
        {
         if(bars[index].timeframe!=timeframe ||
            bars[index].close_time!=
               bars[index].open_time+PeriodSeconds(timeframe) ||
            (index>0 &&
             bars[index].open_time<=bars[index-1].open_time))
            return false;
        }
      return true;
     }

   void AppendBounded(EngineBar &bars[],
                      const EngineBar &bar,
                      const int maximum)
     {
      const int count=ArraySize(bars);
      if(count<maximum)
        {
         ArrayResize(bars,count+1);
         bars[count]=bar;
         return;
        }
      for(int index=1;index<count;index++)
         bars[index-1]=bars[index];
      bars[count-1]=bar;
     }

   void AppendForTimeframe(const ENUM_TIMEFRAMES timeframe,
                           const EngineBar &bar)
     {
      if(timeframe==PERIOD_M1)
         AppendBounded(m_m1_bars,bar,Limit(timeframe));
      else if(timeframe==PERIOD_M5)
         AppendBounded(m_m5_bars,bar,Limit(timeframe));
      else if(timeframe==PERIOD_M15)
         AppendBounded(m_m15_bars,bar,Limit(timeframe));
      else
         AppendBounded(m_h1_bars,bar,Limit(timeframe));
     }

   void ResetTerminal(void)
     {
      if(m_phase!=BEAR_PHASE_ENTRY_READY &&
         m_phase!=BEAR_PHASE_CANCELLED)
         return;
      m_phase=BEAR_PHASE_IDLE;
      m_setup_id="";
      m_setup_time=0;
      m_has_setup=false;
      m_has_arm=false;
      m_has_signal=false;
      m_touches=0;
      m_rejections=0;
      m_acceptance=false;
     }

   void Transition(const BearIncrementalPhase next_phase,
                   const string reason,
                   BearIncrementalEvent &events[])
     {
      const BearIncrementalPhase previous=m_phase;
      m_phase=next_phase;
      const int count=ArraySize(events);
      ArrayResize(events,count+1);
      events[count].available_at=m_as_of;
      events[count].profile_id=m_profile_id;
      events[count].setup_id=m_setup_id;
      events[count].from_phase=previous;
      events[count].to_phase=next_phase;
      events[count].reason=reason;
      events[count].event_id=m_profile_id+":BEAR:"+
         IntegerToString(m_sequence)+":"+BearPhaseName(previous)+":"+
         BearPhaseName(next_phase)+":"+reason;
     }

   void BuildH1History(const datetime available_at,EngineBar &result[])
     {
      ArrayResize(result,0);
      const int count=ArraySize(m_h1_bars);
      const int start=MathMax(0,count-(m_config.h1_sma_period+2));
      for(int index=start;index<count;index++)
        {
         if(m_h1_bars[index].close_time>available_at)
            continue;
         const int target=ArraySize(result);
         ArrayResize(result,target+1);
         result[target]=m_h1_bars[index];
        }
     }

   void BuildM5Windows(EngineBar &history[],EngineBar &candidates[])
     {
      ArrayResize(history,0);
      ArrayResize(candidates,0);
      const datetime setup_available=m_setup_time+PeriodSeconds(PERIOD_M15);
      const int count=ArraySize(m_m5_bars);
      int first=count;
      for(int index=0;index<count;index++)
        {
         if(m_m5_bars[index].open_time>=setup_available)
           {
            first=index;
            break;
           }
        }
      const int validation_start=MathMax(0,first-3);
      const int history_start=MathMax(0,validation_start-20);
      ArrayResize(history,validation_start-history_start);
      for(int index=history_start;index<validation_start;index++)
         history[index-history_start]=m_m5_bars[index];
      const int candidate_count=MathMin(
         m_config.m5_watch_bars,count-validation_start);
      ArrayResize(candidates,MathMax(0,candidate_count));
      for(int index=0;index<candidate_count;index++)
         candidates[index]=m_m5_bars[validation_start+index];
     }

   void BuildM1Windows(EngineBar &history[],EngineBar &candidates[])
     {
      ArrayResize(history,0);
      ArrayResize(candidates,0);
      const int count=ArraySize(m_m1_bars);
      int first=count;
      for(int index=0;index<count;index++)
        {
         if(m_m1_bars[index].open_time>=m_arm.armed_at)
           {
            first=index;
            break;
           }
        }
      const int history_start=MathMax(0,first-20);
      ArrayResize(history,first-history_start);
      for(int index=history_start;index<first;index++)
         history[index-history_start]=m_m1_bars[index];
      const int candidate_count=MathMin(
         m_config.m1_entry_bars,count-first);
      ArrayResize(candidates,MathMax(0,candidate_count));
      for(int index=0;index<candidate_count;index++)
         candidates[index]=m_m1_bars[first+index];
     }

   void Advance(const bool has_candidate_setup,
                const BearSetup &candidate_setup,
                BearIncrementalEvent &events[])
     {
      if(m_phase==BEAR_PHASE_IDLE && has_candidate_setup &&
         candidate_setup.time+PeriodSeconds(PERIOD_M15)<=m_as_of &&
         candidate_setup.time>m_last_setup_time)
        {
         if(candidate_setup.symbol!=m_symbol)
            return;
         m_setup=candidate_setup;
         m_has_setup=true;
         m_setup_time=candidate_setup.time;
         m_last_setup_time=candidate_setup.time;
         m_setup_id=m_profile_id+":BEAR:"+
            IsoSemanticTime(candidate_setup.time);
         Transition(BEAR_PHASE_WATCH_H1,"M15_SETUP_ACCEPTED",events);
        }

      if(m_phase==BEAR_PHASE_WATCH_H1)
        {
         EngineBar h1[];
         BuildH1History(m_setup_time+PeriodSeconds(PERIOD_M15),h1);
         if(!BearH1Bearish(h1,m_config.h1_sma_period))
           {
            Transition(
               BEAR_PHASE_CANCELLED,"H1_BEARISH_CONTEXT_REJECTED",events);
            return;
           }
         Transition(
            BEAR_PHASE_WATCH_M5,"H1_BEARISH_CONTEXT_ACCEPTED",events);
        }

      if(m_phase==BEAR_PHASE_WATCH_M5)
        {
         EngineBar history[];
         EngineBar candidates[];
         BuildM5Windows(history,candidates);
         const BearM5Result result=BearArmOnM5(
            m_setup,history,candidates,
            m_setup_time+PeriodSeconds(PERIOD_M15),m_config);
         m_touches=result.touches;
         m_rejections=result.rejections;
         if(result.state==BEAR_M5_CANCELLED)
           {
            m_acceptance=result.reason=="M5_ACCEPTANCE";
            Transition(BEAR_PHASE_CANCELLED,
                       result.reason=="" ? "M5_VALIDATION_CANCELLED" :
                       result.reason,events);
            return;
           }
         if(result.state==BEAR_M5_ARMED)
           {
            m_arm=result;
            m_has_arm=true;
            Transition(BEAR_PHASE_WATCH_M1,"M5_REJECTION_ARMED",events);
           }
         else if(ArraySize(candidates)>=m_config.m5_watch_bars)
           {
            Transition(
               BEAR_PHASE_CANCELLED,"M5_WATCH_WINDOW_EXPIRED",events);
            return;
           }
         else
            return;
        }

      if(m_phase==BEAR_PHASE_WATCH_M1)
        {
         EngineBar history[];
         EngineBar candidates[];
         BuildM1Windows(history,candidates);
         BearEntryPlan plan;
         if(BearEntryOnM1(
               m_setup,m_arm,history,candidates,m_config,plan))
           {
            m_signal=plan;
            m_has_signal=true;
            m_touches=plan.m5_touches;
            m_rejections=plan.m5_rejections;
            Transition(
               BEAR_PHASE_ENTRY_READY,"M1_ENTRY_CONFIRMATION_READY",events);
            return;
           }
         if(ArraySize(candidates)>=m_config.m1_entry_bars)
            Transition(
               BEAR_PHASE_CANCELLED,
               "M1_WATCH_WINDOW_EXPIRED_OR_INVALIDATED",events);
        }
     }

public:
   CBearIncrementalMachine(void)
     {
      Reset();
     }

   void Reset(void)
     {
      m_profile_id="";
      m_symbol="";
      m_utc_offset_minutes=0;
      m_phase=BEAR_PHASE_IDLE;
      m_sequence=0;
      m_as_of=0;
      m_setup_id="";
      m_setup_time=0;
      m_last_setup_time=0;
      m_has_setup=false;
      m_has_arm=false;
      m_has_signal=false;
      m_touches=0;
      m_rejections=0;
      m_acceptance=false;
      m_last_m1=0;
      m_last_m5=0;
      m_last_m15=0;
      m_last_h1=0;
      ArrayResize(m_m1_bars,0);
      ArrayResize(m_m5_bars,0);
      ArrayResize(m_m15_bars,0);
      ArrayResize(m_h1_bars,0);
     }

   bool Initialize(const string profile_id,
                   const string symbol,
                   const double spread_floor,
                   const datetime as_of,
                   const int utc_offset_minutes=180)
     {
      Reset();
      if(profile_id=="" || symbol=="" || spread_floor<0.0 || as_of<=0 ||
         (utc_offset_minutes!=120 && utc_offset_minutes!=180))
         return false;
      m_profile_id=profile_id;
      m_symbol=symbol;
      m_utc_offset_minutes=utc_offset_minutes;
      m_as_of=as_of;
      LoadBearV4Config(m_config,spread_floor);
      return true;
     }

   bool SeedClosedHistory(const EngineBar &m1[],
                          const EngineBar &m5[],
                          const EngineBar &m15[],
                          const EngineBar &h1[])
     {
      if(m_profile_id=="")
         return false;
      if(ArraySize(m_m1_bars)>0 || ArraySize(m_m5_bars)>0 ||
         ArraySize(m_m15_bars)>0 || ArraySize(m_h1_bars)>0)
         return false;
      for(int timeframe_index=0;timeframe_index<4;timeframe_index++)
        {
         const ENUM_TIMEFRAMES timeframe=(timeframe_index==0 ? PERIOD_H1 :
                                          timeframe_index==1 ? PERIOD_M5 :
                                          timeframe_index==2 ? PERIOD_M1 :
                                          PERIOD_M15);
         EngineBar values[];
         if(timeframe==PERIOD_H1)
            ArrayCopy(values,h1);
         else if(timeframe==PERIOD_M5)
            ArrayCopy(values,m5);
         else if(timeframe==PERIOD_M1)
            ArrayCopy(values,m1);
         else
            ArrayCopy(values,m15);
         const int start=MathMax(0,ArraySize(values)-Limit(timeframe));
         for(int index=start;index<ArraySize(values);index++)
           {
            if(index>start &&
               values[index].open_time<=values[index-1].open_time)
               return false;
            AppendForTimeframe(timeframe,values[index]);
            SetCursor(timeframe,values[index].open_time);
            m_as_of=MathMax(m_as_of,values[index].close_time);
           }
        }
      return true;
     }

   bool OnBarClose(const ENUM_TIMEFRAMES timeframe,
                   const EngineBar &bar,
                   const bool has_candidate_setup,
                   const BearSetup &candidate_setup,
                   BearIncrementalEvent &events[],
                   BearEntryPlan &signal,
                   bool &has_signal,
                   string &error)
     {
      ArrayResize(events,0);
      has_signal=false;
      error="OK";
      if(!Supported(timeframe) ||
         bar.timeframe!=timeframe ||
         bar.open_time<=0 ||
         bar.close_time!=bar.open_time+PeriodSeconds(timeframe))
        {
         error="INVALID_CLOSED_BAR";
         return false;
        }
      const datetime cursor=Cursor(timeframe);
      if(cursor>0 && bar.open_time==cursor)
         return true;
      if(cursor>0 && bar.open_time<cursor)
        {
         error="BAR_BEFORE_PROCESSED_CURSOR";
         return false;
        }
      ResetTerminal();
      AppendForTimeframe(timeframe,bar);
      SetCursor(timeframe,bar.open_time);
      m_sequence++;
      m_as_of=MathMax(m_as_of,bar.close_time);
      Advance(has_candidate_setup,candidate_setup,events);
      if(m_has_signal && m_phase==BEAR_PHASE_ENTRY_READY)
        {
         signal=m_signal;
         has_signal=true;
        }
      return true;
     }

   void Snapshot(CBearIncrementalSnapshot &snapshot) const
     {
      snapshot.profile_id=m_profile_id;
      snapshot.symbol=m_symbol;
      snapshot.utc_offset_minutes=m_utc_offset_minutes;
      snapshot.phase=m_phase;
      snapshot.sequence=m_sequence;
      snapshot.as_of=m_as_of;
      snapshot.setup_id=m_setup_id;
      snapshot.setup_time=m_setup_time;
      snapshot.last_setup_time=m_last_setup_time;
      snapshot.has_setup=m_has_setup;
      snapshot.setup=m_setup;
      snapshot.has_arm=m_has_arm;
      snapshot.arm=m_arm;
      snapshot.has_signal=m_has_signal;
      snapshot.signal=m_signal;
      snapshot.touches=m_touches;
      snapshot.rejections=m_rejections;
      snapshot.acceptance=m_acceptance;
      snapshot.last_m1=m_last_m1;
      snapshot.last_m5=m_last_m5;
      snapshot.last_m15=m_last_m15;
      snapshot.last_h1=m_last_h1;
      ArrayCopy(snapshot.m1_bars,m_m1_bars);
      ArrayCopy(snapshot.m5_bars,m_m5_bars);
      ArrayCopy(snapshot.m15_bars,m_m15_bars);
      ArrayCopy(snapshot.h1_bars,m_h1_bars);
     }

   bool Restore(const CBearIncrementalSnapshot &snapshot)
     {
      if(snapshot.profile_id!=m_profile_id ||
         snapshot.symbol!=m_symbol ||
         snapshot.utc_offset_minutes!=m_utc_offset_minutes ||
         snapshot.sequence<0 || snapshot.as_of<=0 ||
         (snapshot.phase!=BEAR_PHASE_IDLE && snapshot.setup_id=="") ||
         (snapshot.has_setup && snapshot.setup.symbol!=m_symbol) ||
         (snapshot.phase==BEAR_PHASE_WATCH_M1 && !snapshot.has_arm) ||
         (snapshot.phase==BEAR_PHASE_ENTRY_READY && !snapshot.has_signal) ||
         !SnapshotCursorValid(
            snapshot.m1_bars,PERIOD_M1,snapshot.last_m1) ||
         !SnapshotCursorValid(
            snapshot.m5_bars,PERIOD_M5,snapshot.last_m5) ||
         !SnapshotCursorValid(
            snapshot.m15_bars,PERIOD_M15,snapshot.last_m15) ||
         !SnapshotCursorValid(
            snapshot.h1_bars,PERIOD_H1,snapshot.last_h1))
         return false;
      m_phase=snapshot.phase;
      m_sequence=snapshot.sequence;
      m_as_of=snapshot.as_of;
      m_setup_id=snapshot.setup_id;
      m_setup_time=snapshot.setup_time;
      m_last_setup_time=snapshot.last_setup_time;
      m_has_setup=snapshot.has_setup;
      m_setup=snapshot.setup;
      m_has_arm=snapshot.has_arm;
      m_arm=snapshot.arm;
      m_has_signal=snapshot.has_signal;
      m_signal=snapshot.signal;
      m_touches=snapshot.touches;
      m_rejections=snapshot.rejections;
      m_acceptance=snapshot.acceptance;
      m_last_m1=snapshot.last_m1;
      m_last_m5=snapshot.last_m5;
      m_last_m15=snapshot.last_m15;
      m_last_h1=snapshot.last_h1;
      ArrayCopy(m_m1_bars,snapshot.m1_bars);
      ArrayCopy(m_m5_bars,snapshot.m5_bars);
      ArrayCopy(m_m15_bars,snapshot.m15_bars);
      ArrayCopy(m_h1_bars,snapshot.h1_bars);
      return true;
     }

   BearIncrementalPhase Phase(void) const
     {
      return m_phase;
     }

   long Sequence(void) const
     {
      return m_sequence;
     }

   string SetupId(void) const
     {
      return m_setup_id;
     }
  };

#endif
