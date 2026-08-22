#ifndef GOLD_ENGINE_REVISED_GEOMETRY_MQH
#define GOLD_ENGINE_REVISED_GEOMETRY_MQH

#include "GoldEngineRevisedZones.mqh"

double RevisedFallbackRisk(const CRevisedSnapshot &snapshot,
                           const RevisedEngineConfig &config,
                           const double entry,
                           const double atr)
  {
   if(snapshot.has_stop)
      return MathAbs(entry-snapshot.stop);
   return MathMax(atr*config.stop_buffer_atr,config.spread_floor*2.0);
  }

double RevisedEntryStop(const CRevisedSnapshot &snapshot,
                        const RevisedEngineConfig &config,
                        const double entry,
                        const double atr_m1,
                        const double atr_m5,
                        RevisedRiskStats &stats)
  {
   const EngineSide side=snapshot.side;
   const double fallback_risk=RevisedFallbackRisk(snapshot,config,entry,atr_m5);
   const double fallback=(snapshot.has_stop ?
                          snapshot.stop :
                          side==ENGINE_SIDE_BUY ?
                          entry-fallback_risk :
                          entry+fallback_risk);
   string source=(snapshot.has_stop ? "M5_INVALIDATION" : "ATR_FALLBACK");

   const int source_count=ArraySize(snapshot.m1_bars);
   const int source_start=RevisedWindowStartAfterTrigger(
      snapshot.m1_bars,snapshot.m5_trigger_time,0);
   EngineBar bars[];
   const int filtered_count=source_count-source_start;
   ArrayResize(bars,filtered_count);
   for(int index=0;index<filtered_count;index++)
      bars[index]=snapshot.m1_bars[source_start+index];

   double pivots[];
   if(side==ENGINE_SIDE_BUY)
      RevisedSwingLows(bars,config.swing_span,pivots);
   else
      RevisedSwingHighs(bars,config.swing_span,pivots);

   double directional_pivots[];
   int directional_count=0;
   for(int index=0;index<ArraySize(pivots);index++)
     {
      const double price=pivots[index];
      if((side==ENGINE_SIDE_BUY && price<entry) ||
         (side==ENGINE_SIDE_SELL && price>entry))
        {
         ArrayResize(directional_pivots,directional_count+1);
         directional_pivots[directional_count]=price;
         directional_count++;
        }
     }

   const double buffer=MathMax(
      config.spread_floor,atr_m1*config.adaptive_stop_buffer_atr);
   const double minimum_risk=MathMax(
      config.spread_floor*2.0,atr_m1*config.adaptive_stop_min_risk_atr);
   bool has_structural=false;
   double structural=0.0;
   if(directional_count>0)
     {
      double pivot=directional_pivots[0];
      for(int index=1;index<directional_count;index++)
        {
         pivot=(side==ENGINE_SIDE_BUY ?
                MathMax(pivot,directional_pivots[index]) :
                MathMin(pivot,directional_pivots[index]));
        }
      structural=(side==ENGINE_SIDE_BUY ? pivot-buffer : pivot+buffer);
      structural=(side==ENGINE_SIDE_BUY ?
                  MathMin(structural,entry-minimum_risk) :
                  MathMax(structural,entry+minimum_risk));
      has_structural=true;
     }

   double selected=fallback;
   if(has_structural)
     {
      const double fallback_distance=MathAbs(entry-selected);
      const double structural_distance=MathAbs(entry-structural);
      if(minimum_risk<=structural_distance &&
         structural_distance<fallback_distance)
        {
         selected=structural;
         source="M1_CONFIRMED_STRUCTURE";
        }
     }
   selected=RevisedNormalize(selected,config.price_tick);
   stats.source=source;
   stats.original_stop=RevisedNormalize(fallback,config.price_tick);
   stats.selected_stop=selected;
   stats.risk=MathAbs(entry-selected);
   stats.m1_pivot_count=directional_count;
   return selected;
  }

double RevisedStop(const CRevisedSnapshot &snapshot,
                   const RevisedEngineConfig &config,
                   const double entry,
                   const double risk)
  {
   if(snapshot.has_stop)
      return RevisedNormalize(snapshot.stop,config.price_tick);
   return RevisedNormalize(
      snapshot.side==ENGINE_SIDE_BUY ? entry-risk : entry+risk,
      config.price_tick);
  }

bool RevisedTarget(const RevisedEngineConfig &config,
                   const EngineSide side,
                   const double entry,
                   const bool has_obstacle,
                   const double obstacle,
                   const double atr,
                   const bool scalper,
                   double &target)
  {
   target=0.0;
   if(!has_obstacle)
      return false;
   const double buffer_atr=(scalper ?
                            config.scalper_target_buffer_atr :
                            config.strict_target_buffer_atr);
   const double buffer=MathMax(config.spread_floor,atr*buffer_atr);
   target=RevisedNormalize(
      side==ENGINE_SIDE_BUY ? obstacle-buffer : obstacle+buffer,
      config.price_tick);
   return true;
  }

bool RevisedBarsStrictlyOrdered(const EngineBar &bars[])
  {
   for(int index=1;index<ArraySize(bars);index++)
     {
      if(bars[index].open_time<=bars[index-1].open_time)
         return false;
     }
   return true;
  }

bool ValidateRevisedSnapshot(const CRevisedSnapshot &snapshot,string &reason)
  {
   if(StringLen(snapshot.symbol)==0)
     {
      reason="SNAPSHOT_SYMBOL_REQUIRED";
      return false;
     }
   if(ArraySize(snapshot.m1_bars)==0 || ArraySize(snapshot.m5_bars)==0)
     {
      reason="M1_M5_CLOSED_BARS_REQUIRED";
      return false;
     }
   if(!RevisedBarsStrictlyOrdered(snapshot.m1_bars) ||
      !RevisedBarsStrictlyOrdered(snapshot.m5_bars) ||
      !RevisedBarsStrictlyOrdered(snapshot.h1_bars) ||
      !RevisedBarsStrictlyOrdered(snapshot.d1_bars))
     {
      reason="SNAPSHOT_BARS_NOT_STRICTLY_ORDERED";
      return false;
     }
   const int m1_count=ArraySize(snapshot.m1_bars);
   if(snapshot.m1_bars[m1_count-1].open_time>snapshot.current_time)
     {
      reason="SNAPSHOT_CURRENT_TIME_PRECEDES_M1";
      return false;
     }
   reason="OK";
   return true;
  }

#endif
