#ifndef GOLD_ENGINE_BEAR_INDICATORS_MQH
#define GOLD_ENGINE_BEAR_INDICATORS_MQH

#include "GoldEngineBearTypes.mqh"

double BearBody(const EngineBar &bar)
  {
   return MathAbs(bar.close-bar.open);
  }

double BearRange(const EngineBar &bar)
  {
   return bar.high-bar.low;
  }

double BearUpperWick(const EngineBar &bar)
  {
   return bar.high-MathMax(bar.open,bar.close);
  }

bool BearAverageTrueRange(const EngineBar &bars[],
                          const int period,
                          double &value)
  {
   const int count=ArraySize(bars);
   if(period<1 || count<period+1)
      return false;
   double total=0.0;
   const int start=count-period;
   for(int index=start;index<count;index++)
     {
      const EngineBar previous=bars[index-1];
      const EngineBar current=bars[index];
      total+=MathMax(
         current.high-current.low,
         MathMax(
            MathAbs(current.high-previous.close),
            MathAbs(current.low-previous.close)));
     }
   value=total/period;
   return MathIsValidNumber(value);
  }

double BearSimpleRsi(const EngineBar &bars[],const int period)
  {
   const int count=ArraySize(bars);
   if(count<period+1)
      return 50.0;
   double gains=0.0;
   double losses=0.0;
   const int start=count-period;
   for(int index=start;index<count;index++)
     {
      const double change=bars[index].close-bars[index-1].close;
      gains+=MathMax(change,0.0);
      losses+=MathMax(-change,0.0);
     }
   const double average_gain=gains/period;
   const double average_loss=losses/period;
   if(average_loss<=0.0)
      return average_gain>0.0 ? 100.0 : 50.0;
   const double relative_strength=average_gain/average_loss;
   return 100.0-100.0/(1.0+relative_strength);
  }

struct BearStochasticStats
  {
   double k;
   double d;
   double previous_k;
   double recent_peak;
  };

BearStochasticStats BearStochastic(const EngineBar &bars[],
                                    const int period,
                                    const int smoothing)
  {
   BearStochasticStats stats;
   stats.k=50.0;
   stats.d=50.0;
   stats.previous_k=50.0;
   stats.recent_peak=50.0;
   const int count=ArraySize(bars);
   if(count<period+smoothing)
      return stats;
   double values[];
   ArrayResize(values,smoothing+1);
   for(int offset=0;offset<=smoothing;offset++)
     {
      const int end=count-smoothing+offset;
      double lowest=bars[end-period].low;
      double highest=bars[end-period].high;
      for(int index=end-period+1;index<end;index++)
        {
         lowest=MathMin(lowest,bars[index].low);
         highest=MathMax(highest,bars[index].high);
        }
      const double denominator=highest-lowest;
      values[offset]=(denominator<=0.0 ? 50.0 :
                      (bars[end-1].close-lowest)/denominator*100.0);
     }
   stats.k=values[smoothing];
   stats.previous_k=values[smoothing-1];
   stats.d=0.0;
   stats.recent_peak=values[0];
   for(int index=0;index<=smoothing;index++)
     {
      stats.recent_peak=MathMax(stats.recent_peak,values[index]);
      if(index>0)
         stats.d+=values[index];
     }
   stats.d/=smoothing;
   return stats;
  }

void BearCombineBars(const EngineBar &history[],
                     const EngineBar &candidates[],
                     const int candidate_count,
                     EngineBar &result[])
  {
   const int history_count=ArraySize(history);
   const int bounded=MathMax(0,MathMin(candidate_count,ArraySize(candidates)));
   ArrayResize(result,history_count+bounded);
   for(int index=0;index<history_count;index++)
      result[index]=history[index];
   for(int index=0;index<bounded;index++)
      result[history_count+index]=candidates[index];
  }

#endif
