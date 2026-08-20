#ifndef GOLD_ENGINE_REVISED_SETUP_MQH
#define GOLD_ENGINE_REVISED_SETUP_MQH

#include "GoldEngineRevisedIndicators.mqh"

bool ClassifyRevisedM5Setup(const EngineBar &bars[],
                            const EngineSide side,
                            RevisedM5Setup &setup)
  {
   const int count=ArraySize(bars);
   if(count<2)
      return false;
   const EngineBar latest=bars[count-1];
   const EngineBar previous=bars[count-2];
   const bool has_third=count>=3;
   EngineBar third;
   ZeroMemory(third);
   if(has_third)
      third=bars[count-3];

   const double latest_body=MathAbs(latest.close-latest.open);
   const double previous_body=MathAbs(previous.close-previous.open);
   const double body=MathMax(latest_body,1.0e-12);
   const double lower_wick=MathMin(latest.open,latest.close)-latest.low;
   const double upper_wick=latest.high-MathMax(latest.open,latest.close);
   const double range=latest.high-latest.low;
   const double close_from_low=(range>0.0 ?
                                (latest.close-latest.low)/range : 0.0);
   const double close_from_high=(range>0.0 ?
                                 (latest.high-latest.close)/range : 0.0);
   bool directional=false;
   bool micro_break=false;
   bool engulfing=false;
   bool rejection=false;
   bool star=false;
   double level=0.0;
   double invalidation=0.0;
   string pattern="NONE";

   if(side==ENGINE_SIDE_BUY)
     {
      directional=latest.close>latest.open;
      micro_break=latest.close>previous.high;
      engulfing=directional &&
                latest.open<=previous.close &&
                latest.close>=previous.open &&
                latest_body>=previous_body;
      rejection=directional &&
                latest.low<=previous.low &&
                lower_wick>=body &&
                close_from_low>=0.65;
      const double third_body=(has_third ?
                               MathAbs(third.close-third.open) : 0.0);
      star=has_third &&
           third.close<third.open &&
           previous_body<=third_body*0.60 &&
           directional &&
           latest.close>=(third.open+third.close)/2.0;
      level=previous.high;
      invalidation=previous.low;
      pattern=(star ? "BULL_MORNING_STAR" :
               engulfing ? "BULL_ENGULFING" :
               rejection ? "BULL_REJECTION" :
               directional && micro_break ? "BULL_MICRO_BREAK" :
               "NONE");
     }
   else
     {
      directional=latest.close<latest.open;
      micro_break=latest.close<previous.low;
      engulfing=directional &&
                latest.open>=previous.close &&
                latest.close<=previous.open &&
                latest_body>=previous_body;
      rejection=directional &&
                latest.high>=previous.high &&
                upper_wick>=body &&
                close_from_high>=0.65;
      const double third_body=(has_third ?
                               MathAbs(third.close-third.open) : 0.0);
      star=has_third &&
           third.close>third.open &&
           previous_body<=third_body*0.60 &&
           directional &&
           latest.close<=(third.open+third.close)/2.0;
      level=previous.low;
      invalidation=previous.high;
      pattern=(star ? "BEAR_EVENING_STAR" :
               engulfing ? "BEAR_ENGULFING" :
               rejection ? "BEAR_REJECTION" :
               directional && micro_break ? "BEAR_MICRO_BREAK" :
               "NONE");
     }
   if(pattern=="NONE")
      return false;

   const int votes=(directional ? 1 : 0)+
                   (micro_break ? 1 : 0)+
                   ((engulfing || rejection || star) ? 1 : 0);
   setup.side=side;
   setup.trigger_time=latest.open_time+PeriodSeconds(PERIOD_M5);
   setup.pattern=pattern;
   setup.votes=votes;
   setup.confidence=MathMin(100.0,60.0+votes*10.0);
   setup.level=level;
   setup.invalidation=invalidation;
   return true;
  }

bool RevisedSetupIsStrong(const RevisedM5Setup &setup)
  {
   return setup.votes>=3 &&
          setup.pattern!="BULL_MICRO_BREAK" &&
          setup.pattern!="BEAR_MICRO_BREAK";
  }

RevisedM5Setup MergeRevisedSetup(const RevisedM5Setup &existing,
                                 const RevisedM5Setup &candidate)
  {
   const bool existing_strong=RevisedSetupIsStrong(existing);
   const bool candidate_strong=RevisedSetupIsStrong(candidate);
   const bool use_candidate=candidate_strong || !existing_strong;
   RevisedM5Setup merged;
   merged.side=existing.side;
   merged.trigger_time=existing.trigger_time;
   merged.pattern=(use_candidate ? candidate.pattern : existing.pattern);
   merged.votes=MathMax(existing.votes,candidate.votes);
   merged.confidence=MathMax(existing.confidence,candidate.confidence);
   merged.level=(use_candidate ? candidate.level : existing.level);
   merged.invalidation=(use_candidate ?
                        candidate.invalidation : existing.invalidation);
   return merged;
  }

class CRevisedSetupDetector
  {
private:
   RevisedDetectorState m_state;
   int                  m_maximum_age_seconds;

   bool IsConsumed(const EngineSide side,const datetime trigger_time) const
     {
      const datetime consumed=(side==ENGINE_SIDE_BUY ?
                               m_state.buy_consumed_at :
                               m_state.sell_consumed_at);
      return consumed>0 && trigger_time<=consumed;
     }

   bool HasActive(const EngineSide side) const
     {
      return side==ENGINE_SIDE_BUY ? m_state.buy_active : m_state.sell_active;
     }

   RevisedM5Setup Active(const EngineSide side) const
     {
      return side==ENGINE_SIDE_BUY ? m_state.buy_setup : m_state.sell_setup;
     }

   void SetActive(const EngineSide side,const RevisedM5Setup &setup)
     {
      if(side==ENGINE_SIDE_BUY)
        {
         m_state.buy_setup=setup;
         m_state.buy_active=true;
        }
      else
        {
         m_state.sell_setup=setup;
         m_state.sell_active=true;
        }
     }

   void ClearActive(const EngineSide side)
     {
      if(side==ENGINE_SIDE_BUY)
         m_state.buy_active=false;
      else
         m_state.sell_active=false;
     }

   void Terminate(const EngineSide side,
                  const RevisedM5Setup &setup,
                  const string reason)
     {
      if(side==ENGINE_SIDE_BUY)
        {
         m_state.buy_terminated=true;
         m_state.buy_terminated_setup=setup;
         m_state.buy_termination_reason=reason;
        }
      else
        {
         m_state.sell_terminated=true;
         m_state.sell_terminated_setup=setup;
         m_state.sell_termination_reason=reason;
        }
     }

   void ProcessCandidate(const RevisedM5Setup &candidate)
     {
      const EngineSide side=candidate.side;
      if(IsConsumed(side,candidate.trigger_time))
         return;
      const EngineSide opposite=(side==ENGINE_SIDE_BUY ?
                                 ENGINE_SIDE_SELL : ENGINE_SIDE_BUY);
      const bool opposite_active=HasActive(opposite);
      if(RevisedSetupIsStrong(candidate))
        {
         if(opposite_active)
           {
            const RevisedM5Setup terminated=Active(opposite);
            ClearActive(opposite);
            Terminate(opposite,terminated,"OPPOSITE_M5_SETUP_ACCEPTED");
           }
        }
      else if(opposite_active)
         return;

      if(HasActive(side))
        {
         const RevisedM5Setup merged=MergeRevisedSetup(Active(side),candidate);
         SetActive(side,merged);
        }
      else
         SetActive(side,candidate);
     }

public:
   CRevisedSetupDetector(void)
     {
      Reset();
      m_maximum_age_seconds=60*60;
     }

   void Reset(void)
     {
      m_state.buy_active=false;
      m_state.sell_active=false;
      m_state.buy_terminated=false;
      m_state.sell_terminated=false;
      m_state.buy_termination_reason="";
      m_state.sell_termination_reason="";
      m_state.buy_consumed_at=0;
      m_state.sell_consumed_at=0;
      m_state.last_classified_m5=0;
     }

   void SetMaximumAgeBars(const int maximum_m1_bars)
     {
      m_maximum_age_seconds=MathMax(1,maximum_m1_bars)*60;
     }

   void SeedWarmup(const datetime latest_closed_m5)
     {
      if(!m_state.buy_active && !m_state.sell_active)
         m_state.last_classified_m5=latest_closed_m5;
     }

   RevisedDetectorState Snapshot(void) const
     {
      return m_state;
     }

   void Restore(const RevisedDetectorState &state)
     {
      m_state=state;
     }

   bool Update(const EngineBar &m5_bars[],
               const datetime current_m1_time,
               const EngineSide side,
               RevisedM5Setup &setup)
     {
      const int count=ArraySize(m5_bars);
      if(count<2)
         return false;
      const datetime latest=m5_bars[count-1].open_time;
      if(m_state.last_classified_m5<=0 || latest>m_state.last_classified_m5)
        {
         m_state.last_classified_m5=latest;
         RevisedM5Setup candidate;
         if(ClassifyRevisedM5Setup(m5_bars,ENGINE_SIDE_BUY,candidate))
            ProcessCandidate(candidate);
         if(ClassifyRevisedM5Setup(m5_bars,ENGINE_SIDE_SELL,candidate))
            ProcessCandidate(candidate);
        }
      if(!HasActive(side))
         return false;
      setup=Active(side);
      if(current_m1_time<=setup.trigger_time)
         return false;
      if(current_m1_time-setup.trigger_time>m_maximum_age_seconds)
        {
         ClearActive(side);
         Terminate(side,setup,"WATCH_WINDOW_EXPIRED");
         return false;
        }
      return true;
     }

   bool PopTermination(const EngineSide side,
                       RevisedM5Setup &setup,
                       string &reason)
     {
      if(side==ENGINE_SIDE_BUY)
        {
         if(!m_state.buy_terminated)
            return false;
         setup=m_state.buy_terminated_setup;
         reason=m_state.buy_termination_reason;
         m_state.buy_terminated=false;
         m_state.buy_termination_reason="";
         return true;
        }
      if(!m_state.sell_terminated)
         return false;
      setup=m_state.sell_terminated_setup;
      reason=m_state.sell_termination_reason;
      m_state.sell_terminated=false;
      m_state.sell_termination_reason="";
      return true;
     }

   void Consume(const EngineSide side,const datetime trigger_time)
     {
      if(side==ENGINE_SIDE_BUY)
        {
         if(trigger_time>m_state.buy_consumed_at)
            m_state.buy_consumed_at=trigger_time;
         if(m_state.buy_active &&
            m_state.buy_setup.trigger_time==trigger_time)
            m_state.buy_active=false;
        }
      else
        {
         if(trigger_time>m_state.sell_consumed_at)
            m_state.sell_consumed_at=trigger_time;
         if(m_state.sell_active &&
            m_state.sell_setup.trigger_time==trigger_time)
            m_state.sell_active=false;
        }
     }
  };

#endif
