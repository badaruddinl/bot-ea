#ifndef GOLD_ENGINE_REVISED_INDICATORS_MQH
#define GOLD_ENGINE_REVISED_INDICATORS_MQH

#include "GoldEngineRevisedTypes.mqh"

double RevisedAtr(const EngineBar &bars[],const int period)
  {
   const int count=ArraySize(bars);
   if(period<1 || count<period+1)
      return 0.0;
   double total=0.0;
   const int start=count-period;
   for(int index=start;index<count;index++)
     {
      const double previous_close=bars[index-1].close;
      const double high_low=bars[index].high-bars[index].low;
      const double high_previous=MathAbs(bars[index].high-previous_close);
      const double low_previous=MathAbs(bars[index].low-previous_close);
      total+=MathMax(high_low,MathMax(high_previous,low_previous));
     }
   return total/period;
  }

double RevisedRsi(const double &closes[],const int period=7)
  {
   const int count=ArraySize(closes);
   if(period<1 || count<period+1)
      return 50.0;

   double gain=0.0;
   double loss=0.0;
   for(int index=1;index<=period;index++)
     {
      const double change=closes[index]-closes[index-1];
      gain+=MathMax(change,0.0);
      loss+=MathMax(-change,0.0);
     }
   gain/=period;
   loss/=period;
   for(int index=period+1;index<count;index++)
     {
      const double change=closes[index]-closes[index-1];
      const double up=MathMax(change,0.0);
      const double down=MathMax(-change,0.0);
      gain=(gain*(period-1)+up)/period;
      loss=(loss*(period-1)+down)/period;
     }
   if(loss<=0.0)
      return gain>0.0 ? 100.0 : 50.0;
   const double relative_strength=gain/loss;
   return 100.0-100.0/(1.0+relative_strength);
  }

int RevisedSwingHighs(const EngineBar &bars[],const int span,double &result[])
  {
   ArrayResize(result,0);
   const int count=ArraySize(bars);
   if(span<1 || count<span*2+1)
      return 0;
   int result_count=0;
   for(int index=span;index<count-span;index++)
     {
      const double pivot=bars[index].high;
      bool confirmed=true;
      for(int offset=1;offset<=span;offset++)
        {
         if(pivot<=bars[index-offset].high || pivot<=bars[index+offset].high)
           {
            confirmed=false;
            break;
           }
        }
      if(confirmed)
        {
         ArrayResize(result,result_count+1);
         result[result_count]=pivot;
         result_count++;
        }
     }
   return result_count;
  }

int RevisedSwingLows(const EngineBar &bars[],const int span,double &result[])
  {
   ArrayResize(result,0);
   const int count=ArraySize(bars);
   if(span<1 || count<span*2+1)
      return 0;
   int result_count=0;
   for(int index=span;index<count-span;index++)
     {
      const double pivot=bars[index].low;
      bool confirmed=true;
      for(int offset=1;offset<=span;offset++)
        {
         if(pivot>=bars[index-offset].low || pivot>=bars[index+offset].low)
           {
            confirmed=false;
            break;
           }
        }
      if(confirmed)
        {
         ArrayResize(result,result_count+1);
         result[result_count]=pivot;
         result_count++;
        }
     }
   return result_count;
  }

double RevisedNormalize(const double value,const double tick)
  {
   if(tick<=0.0)
      return 0.0;
   const double rounded=MathCeil((value-1.0e-12)/tick)*tick;
   return MathRound(rounded*1.0e10)/1.0e10;
  }

#endif
