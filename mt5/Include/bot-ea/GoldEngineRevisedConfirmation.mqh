#ifndef GOLD_ENGINE_REVISED_CONFIRMATION_MQH
#define GOLD_ENGINE_REVISED_CONFIRMATION_MQH

#include "GoldEngineRevisedIndicators.mqh"

int RevisedWindowStartAfterTrigger(const EngineBar &bars[],
                                   const datetime trigger,
                                   const int maximum_bars)
  {
   const int count=ArraySize(bars);
   int start=0;
   if(trigger>0)
     {
      while(start<count && bars[start].open_time<=trigger)
         start++;
     }
   if(maximum_bars>0 && count-start>maximum_bars)
      start=count-maximum_bars;
   return start;
  }

void RevisedRangeStatistics(const CRevisedSnapshot &snapshot,
                            const RevisedEngineConfig &config,
                            const EngineSide side,
                            const double atr,
                            RevisedRangeStats &stats)
  {
   stats.bars=0;
   stats.high=0.0;
   stats.low=0.0;
   stats.width=0.0;
   stats.touches=0;
   stats.rejections=0;
   stats.acceptance=0;
   stats.excursion=0.0;
   stats.boundary=0.0;

   const int count=ArraySize(snapshot.m1_bars);
   const int start=RevisedWindowStartAfterTrigger(
      snapshot.m1_bars,snapshot.m5_trigger_time,config.range_max_bars);
   if(start>=count)
      return;

   double high=snapshot.m1_bars[start].high;
   double low=snapshot.m1_bars[start].low;
   for(int index=start+1;index<count;index++)
     {
      high=MathMax(high,snapshot.m1_bars[index].high);
      low=MathMin(low,snapshot.m1_bars[index].low);
     }
   const double width=high-low;
   const double boundary=(side==ENGINE_SIDE_BUY ? low : high);
   const double tolerance=MathMax(config.spread_floor*2.0,atr*0.10);
   int touches=0;
   int rejections=0;
   int last_touch=-10000;
   double retreat_since_touch=0.0;
   double maximum_excursion=0.0;

   for(int index=start;index<count;index++)
     {
      const EngineBar bar=snapshot.m1_bars[index];
      const double distance_from_boundary=
         (side==ENGINE_SIDE_BUY ? bar.close-boundary : boundary-bar.close);
      if(last_touch>=0)
         retreat_since_touch=MathMax(retreat_since_touch,distance_from_boundary);
      const bool hit=(side==ENGINE_SIDE_BUY ?
                      bar.low<=boundary+tolerance :
                      bar.high>=boundary-tolerance);
      if(!hit || index-last_touch<config.range_touch_separation_bars)
         continue;
      const double retreat=
         (side==ENGINE_SIDE_BUY ? bar.close-boundary : boundary-bar.close);
      if(last_touch>=0 &&
         retreat_since_touch<width*config.range_retreat_fraction)
         continue;
      touches++;
      last_touch=index;
      retreat_since_touch=0.0;
      if(retreat>=width*0.10)
         rejections++;
      maximum_excursion=MathMax(maximum_excursion,retreat);
     }

   int outside=0;
   const int acceptance_start=MathMax(start,count-config.acceptance_window);
   for(int index=acceptance_start;index<count;index++)
     {
      const double close=snapshot.m1_bars[index].close;
      if((side==ENGINE_SIDE_BUY && close<boundary-tolerance) ||
         (side==ENGINE_SIDE_SELL && close>boundary+tolerance))
         outside++;
     }

   stats.bars=count-start;
   stats.high=high;
   stats.low=low;
   stats.width=width;
   stats.touches=touches;
   stats.rejections=rejections;
   stats.acceptance=(outside>=config.acceptance_close_count ? 1 : 0);
   stats.excursion=maximum_excursion;
   stats.boundary=boundary;
  }

void RevisedM1ConfirmationForWindow(const EngineBar &bars[],
                                    const int start,
                                    const int end,
                                    const EngineSide side,
                                    RevisedM1Confirmation &result)
  {
   result.votes=0;
   result.directional=false;
   result.micro_break=false;
   result.rsi_ok=false;
   result.rsi7=0.0;
   result.body_ratio=0.0;
   result.close_location=0.0;
   if(start<0 || end-start+1<2 || end>=ArraySize(bars))
      return;

   const EngineBar latest=bars[end];
   const EngineBar previous=bars[end-1];
   const double range=latest.high-latest.low;
   const double body=MathAbs(latest.close-latest.open);
   result.body_ratio=(range>0.0 ? body/range : 0.0);
   if(side==ENGINE_SIDE_BUY)
     {
      result.directional=latest.close>latest.open;
      result.micro_break=latest.close>previous.high;
      result.close_location=(range>0.0 ? (latest.close-latest.low)/range : 0.0);
     }
   else
     {
      result.directional=latest.close<latest.open;
      result.micro_break=latest.close<previous.low;
      result.close_location=(range>0.0 ? (latest.high-latest.close)/range : 0.0);
     }

   const int close_count=end-start+1;
   double closes[];
   ArrayResize(closes,close_count);
   for(int index=0;index<close_count;index++)
      closes[index]=bars[start+index].close;
   result.rsi7=RevisedRsi(closes,7);
   result.rsi_ok=(side==ENGINE_SIDE_BUY ? result.rsi7>=50.0 : result.rsi7<=50.0);
   result.votes=(result.directional ? 1 : 0)+
                (result.micro_break ? 1 : 0)+
                (result.rsi_ok ? 1 : 0);
  }

void RevisedM1ConfirmationLatest(const EngineBar &bars[],
                                 const EngineSide side,
                                 RevisedM1Confirmation &result)
  {
   RevisedM1ConfirmationForWindow(bars,0,ArraySize(bars)-1,side,result);
  }

bool RevisedStrongM1Confirmation(const RevisedM1Confirmation &m1,
                                 const RevisedEngineConfig &config)
  {
   return m1.votes==3 &&
          m1.micro_break &&
          m1.body_ratio>=config.strong_m1_body_ratio &&
          m1.close_location>=config.strong_m1_close_location;
  }

bool RevisedQualifiedRangeM1Confirmation(const RevisedM1Confirmation &m1,
                                         const RevisedEngineConfig &config)
  {
   return m1.votes==3 &&
          m1.micro_break &&
          m1.body_ratio>=config.range_min_body_fraction &&
          m1.close_location>=config.range_min_close_location;
  }

bool RevisedStrongM1Latched(const CRevisedSnapshot &snapshot,
                            const RevisedEngineConfig &config,
                            const EngineSide side)
  {
   const int count=ArraySize(snapshot.m1_bars);
   const int start=RevisedWindowStartAfterTrigger(
      snapshot.m1_bars,snapshot.m5_trigger_time,config.watch_max_m1_bars);
   for(int end=start+1;end<count;end++)
     {
      RevisedM1Confirmation m1;
      RevisedM1ConfirmationForWindow(snapshot.m1_bars,start,end,side,m1);
      if(RevisedQualifiedRangeM1Confirmation(m1,config))
         return true;
     }
   return false;
  }

bool RevisedRangeConfirmed(const RevisedRangeStats &stats,
                           const RevisedM1Confirmation &m1,
                           const RevisedEngineConfig &config)
  {
   return stats.touches>=config.range_min_rejections &&
          stats.rejections>=config.range_min_rejections &&
          stats.width>0.0 &&
          stats.excursion>=stats.width*config.range_min_excursion_fraction &&
          stats.acceptance==0 &&
          m1.micro_break &&
          m1.body_ratio>=config.range_min_body_fraction &&
          m1.close_location>=config.range_min_close_location &&
          m1.votes>=3;
  }

#endif
