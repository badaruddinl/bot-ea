#ifndef GOLD_ENGINE_SCHEDULER_MQH
#define GOLD_ENGINE_SCHEDULER_MQH

#include "GoldEngineTypes.mqh"

#define GOLD_ENGINE_TIMEFRAME_COUNT 5

class CClosedBarScheduler
  {
private:
   string          m_symbol;
   ENUM_TIMEFRAMES m_timeframes[GOLD_ENGINE_TIMEFRAME_COUNT];
   datetime        m_last_forming_open[GOLD_ENGINE_TIMEFRAME_COUNT];
   bool            m_initialized;

   bool ReadLatestClosed(const ENUM_TIMEFRAMES timeframe,EngineBar &bar)
     {
      MqlRates rates[];
      ArraySetAsSeries(rates,true);
      if(CopyRates(m_symbol,timeframe,1,1,rates)!=1)
         return false;

      const int seconds=PeriodSeconds(timeframe);
      bar.timeframe=timeframe;
      bar.open_time=rates[0].time;
      bar.close_time=rates[0].time+seconds;
      bar.open=rates[0].open;
      bar.high=rates[0].high;
      bar.low=rates[0].low;
      bar.close=rates[0].close;
      bar.tick_volume=rates[0].tick_volume;
      bar.spread_points=rates[0].spread;
      return true;
     }

public:
   CClosedBarScheduler(void)
     {
      m_symbol="";
      m_initialized=false;
      m_timeframes[0]=PERIOD_D1;
      m_timeframes[1]=PERIOD_H1;
      m_timeframes[2]=PERIOD_M15;
      m_timeframes[3]=PERIOD_M5;
      m_timeframes[4]=PERIOD_M1;
      ArrayInitialize(m_last_forming_open,0);
     }

   bool Initialize(const string symbol)
     {
      m_symbol=symbol;
      for(int index=0;index<GOLD_ENGINE_TIMEFRAME_COUNT;index++)
        {
         const datetime current=iTime(m_symbol,m_timeframes[index],0);
         if(current<=0)
            return false;
         m_last_forming_open[index]=current;
        }
      m_initialized=true;
      return true;
     }

   bool Poll(EngineBar &closed_bars[],int &bar_count,bool &gap_detected)
     {
      bar_count=0;
      gap_detected=false;
      ArrayResize(closed_bars,0);
      if(!m_initialized)
         return false;

      for(int index=0;index<GOLD_ENGINE_TIMEFRAME_COUNT;index++)
        {
         const ENUM_TIMEFRAMES timeframe=m_timeframes[index];
         const datetime current=iTime(m_symbol,timeframe,0);
         if(current<=0)
            return false;
         if(current==m_last_forming_open[index])
            continue;
         if(current<m_last_forming_open[index])
            return false;

         // Wall-clock distance is not a data-gap signal: overnight/weekend
         // closures legitimately have no broker bars. The exact previous bar
         // must become shift 1. A larger shift proves one or more actual broker
         // candles were skipped while the runtime was alive.
         const int previous_shift=iBarShift(
            m_symbol,timeframe,m_last_forming_open[index],true);
         if(previous_shift!=1)
            gap_detected=true;

         EngineBar bar;
         if(!ReadLatestClosed(timeframe,bar))
            return false;

         m_last_forming_open[index]=current;
         ArrayResize(closed_bars,bar_count+1);
         closed_bars[bar_count]=bar;
         bar_count++;
        }
      return true;
     }
  };

#endif
