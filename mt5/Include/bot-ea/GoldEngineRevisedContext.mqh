#ifndef GOLD_ENGINE_REVISED_CONTEXT_MQH
#define GOLD_ENGINE_REVISED_CONTEXT_MQH

#include "GoldEngineRevisedConfirmation.mqh"

void RevisedMomentumStatistics(const CRevisedSnapshot &snapshot,
                               const RevisedEngineConfig &config,
                               const EngineSide side,
                               const double atr,
                               RevisedMomentumStats &stats)
  {
   stats.momentum=false;
   stats.exhausted=false;
   stats.displacement_atr=0.0;
   stats.body_ratio=0.0;
   stats.close_location=0.0;
   stats.exhaustion_signals=0;
   const int count=ArraySize(snapshot.m5_bars);
   if(count<config.momentum_bars || atr<=0.0)
      return;

   const int start=count-config.momentum_bars;
   const EngineBar first=snapshot.m5_bars[start];
   const EngineBar latest=snapshot.m5_bars[count-1];
   const EngineBar previous=snapshot.m5_bars[count-2];
   const double range=latest.high-latest.low;
   const double body=MathAbs(latest.close-latest.open);
   const double displacement=(side==ENGINE_SIDE_BUY ?
                              latest.close-first.open :
                              first.open-latest.close);
   const double body_ratio=(range>0.0 ? body/range : 0.0);
   const double close_location=(range<=0.0 ? 0.0 :
                                side==ENGINE_SIDE_BUY ?
                                (latest.close-latest.low)/range :
                                (latest.high-latest.close)/range);
   const bool last_directional=(side==ENGINE_SIDE_BUY ?
                                latest.close>latest.open :
                                latest.close<latest.open);
   const bool previous_directional=(side==ENGINE_SIDE_BUY ?
                                    previous.close>previous.open :
                                    previous.close<previous.open);
   const bool expansion=range>=previous.high-previous.low;

   stats.displacement_atr=displacement/atr;
   stats.body_ratio=body_ratio;
   stats.close_location=close_location;
   stats.momentum=last_directional &&
                  previous_directional &&
                  stats.displacement_atr>=config.momentum_min_displacement_atr &&
                  body_ratio>=config.momentum_min_body_fraction &&
                  close_location>=config.momentum_close_location &&
                  expansion;

   if(count>=4)
     {
      const double previous_body=MathAbs(previous.close-previous.open);
      const double previous_range=previous.high-previous.low;
      if(body<previous_body)
         stats.exhaustion_signals++;
      if(range<previous_range)
         stats.exhaustion_signals++;
      if((side==ENGINE_SIDE_BUY && latest.high<=previous.high+atr*0.10) ||
         (side==ENGINE_SIDE_SELL && latest.low>=previous.low-atr*0.10))
         stats.exhaustion_signals++;
      if(body_ratio<0.35)
         stats.exhaustion_signals++;
     }
   stats.exhausted=stats.exhaustion_signals>=config.exhaustion_min_signals;
  }

void RevisedFibonacciStatistics(const CRevisedSnapshot &snapshot,
                                const RevisedEngineConfig &config,
                                const EngineSide side,
                                const double atr_m1,
                                RevisedFibonacciStats &stats)
  {
   stats.available=false;
   stats.anchor_start=0.0;
   stats.anchor_end=0.0;
   stats.zone_low=0.0;
   stats.zone_high=0.0;
   stats.retests=0;
   stats.current_rejection=false;

   const int m5_count=ArraySize(snapshot.m5_bars);
   int end_before_trigger=m5_count;
   if(snapshot.m5_trigger_time>0)
     {
      end_before_trigger=0;
      while(end_before_trigger<m5_count &&
            snapshot.m5_bars[end_before_trigger].open_time<snapshot.m5_trigger_time)
         end_before_trigger++;
     }
   const int start=MathMax(0,end_before_trigger-config.fibonacci_lookback_m5);
   if(end_before_trigger-start<3)
      return;

   double best_start=0.0;
   double best_end=0.0;
   double best_range=0.0;
   for(int start_index=start;start_index<end_before_trigger-1;start_index++)
     {
      for(int end_index=start_index+1;end_index<end_before_trigger;end_index++)
        {
         const double distance=(side==ENGINE_SIDE_BUY ?
                                snapshot.m5_bars[end_index].high-
                                snapshot.m5_bars[start_index].low :
                                snapshot.m5_bars[start_index].high-
                                snapshot.m5_bars[end_index].low);
         if(distance>best_range)
           {
            best_range=distance;
            best_start=(side==ENGINE_SIDE_BUY ?
                        snapshot.m5_bars[start_index].low :
                        snapshot.m5_bars[start_index].high);
            best_end=(side==ENGINE_SIDE_BUY ?
                      snapshot.m5_bars[end_index].high :
                      snapshot.m5_bars[end_index].low);
           }
        }
     }
   if(best_range<=0.0)
      return;

   const double zone_low=(side==ENGINE_SIDE_BUY ?
                          best_end-best_range*0.618 :
                          best_end+best_range*0.382);
   const double zone_high=(side==ENGINE_SIDE_BUY ?
                           best_end-best_range*0.382 :
                           best_end+best_range*0.618);
   const int m1_count=ArraySize(snapshot.m1_bars);
   const int m1_start=RevisedWindowStartAfterTrigger(
      snapshot.m1_bars,snapshot.m5_trigger_time,config.watch_max_m1_bars);
   int retests=0;
   int last_touch=-10000;
   bool left_zone=true;
   const double leave_distance=MathMax(
      (zone_high-zone_low)*config.fibonacci_leave_fraction,atr_m1*0.10);
   for(int index=m1_start;index<m1_count;index++)
     {
      const EngineBar bar=snapshot.m1_bars[index];
      const bool overlaps=bar.low<=zone_high && bar.high>=zone_low;
      if(!overlaps)
        {
         left_zone=(side==ENGINE_SIDE_BUY ?
                    bar.close>=zone_high+leave_distance :
                    bar.close<=zone_low-leave_distance);
         continue;
        }
      const int relative_index=index-m1_start;
      if(left_zone &&
         relative_index-last_touch>=config.fibonacci_retest_separation_bars)
        {
         retests++;
         last_touch=relative_index;
         left_zone=false;
        }
     }

   const int after_count=m1_count-m1_start;
   const bool recent_touch=last_touch>=0 && last_touch>=after_count-3;
   bool current_rejection=false;
   if(after_count>0 && recent_touch)
     {
      const double current_close=snapshot.m1_bars[m1_count-1].close;
      current_rejection=(side==ENGINE_SIDE_BUY ?
                         current_close>zone_high :
                         current_close<zone_low);
     }

   stats.available=true;
   stats.anchor_start=best_start;
   stats.anchor_end=best_end;
   stats.zone_low=zone_low;
   stats.zone_high=zone_high;
   stats.retests=retests;
   stats.current_rejection=current_rejection;
  }

bool RevisedHardInvalidation(const CRevisedSnapshot &snapshot,
                             const RevisedEngineConfig &config,
                             const EngineSide side,
                             const double atr_m1)
  {
   if(!snapshot.has_invalidation || snapshot.m5_trigger_time<=0)
      return false;
   const int count=ArraySize(snapshot.m1_bars);
   const int start=RevisedWindowStartAfterTrigger(
      snapshot.m1_bars,snapshot.m5_trigger_time,config.acceptance_window);
   if(count-start<config.acceptance_close_count)
      return false;

   const double tolerance=MathMax(config.spread_floor,atr_m1*0.10);
   int outside=0;
   for(int index=start;index<count;index++)
     {
      const double close=snapshot.m1_bars[index].close;
      if((side==ENGINE_SIDE_BUY &&
          close<snapshot.invalidation-tolerance) ||
         (side==ENGINE_SIDE_SELL &&
          close>snapshot.invalidation+tolerance))
         outside++;
     }

   bool consecutive=true;
   const int consecutive_start=count-config.acceptance_close_count;
   for(int index=consecutive_start;index<count;index++)
     {
      const double close=snapshot.m1_bars[index].close;
      const bool accepted=(side==ENGINE_SIDE_BUY ?
                           close<snapshot.invalidation-tolerance :
                           close>snapshot.invalidation+tolerance);
      if(!accepted)
        {
         consecutive=false;
         break;
        }
     }
   const double displacement=MathAbs(
      snapshot.m1_bars[count-1].close-snapshot.m1_bars[start].open);
   return consecutive ||
          (outside>=3 &&
           count-start>=4 &&
           displacement>=atr_m1*config.acceptance_displacement_atr);
  }

#endif
