#ifndef GOLD_ENGINE_BEAR_VALIDATION_MQH
#define GOLD_ENGINE_BEAR_VALIDATION_MQH

#include "GoldEngineBearIndicators.mqh"

bool BearH1Bearish(const EngineBar &bars[],const int sma_period)
  {
   const int count=ArraySize(bars);
   if(count<sma_period+1)
      return false;
   double current=0.0;
   double previous=0.0;
   for(int index=count-sma_period;index<count;index++)
      current+=bars[index].close;
   for(int index=count-sma_period-1;index<count-1;index++)
      previous+=bars[index].close;
   current/=sma_period;
   previous/=sma_period;
   return bars[count-1].close<current && current<previous;
  }

BearM5Result BearArmOnM5(const BearSetup &setup,
                         const EngineBar &history[],
                         const EngineBar &candidates[],
                         const datetime available_at,
                         const BearV4Config &config)
  {
   BearM5Result result;
   result.state=BEAR_M5_EXPIRED;
   result.reason="";
   result.armed_at=0;
   result.atr=0.0;
   result.touches=1;
   result.rejections=1;
   result.recent_high=0.0;
   int last_touch=-10000;
   bool retreated=true;
   for(int index=0;index<ArraySize(candidates);index++)
     {
      EngineBar context[];
      BearCombineBars(history,candidates,index+1,context);
      if(ArraySize(context)<15)
         continue;
      double atr=0.0;
      if(!BearAverageTrueRange(context,14,atr))
         continue;
      const double tolerance=MathMax(config.spread_floor,atr*0.20);
      bool acceptance=index+1>=config.m5_acceptance_closes;
      if(acceptance)
        {
         for(int offset=index+1-config.m5_acceptance_closes;
             offset<=index;offset++)
           {
            if(candidates[offset].close<=setup.resistance+tolerance)
              {
               acceptance=false;
               break;
              }
           }
        }
      if(acceptance)
        {
         result.state=BEAR_M5_CANCELLED;
         result.reason="M5_ACCEPTANCE";
         return result;
        }
      const EngineBar current=candidates[index];
      const bool touched=current.high>=setup.resistance-tolerance;
      if(!touched)
        {
         if(current.close<=setup.resistance-atr*config.m5_retreat_atr)
            retreated=true;
        }
      else
        {
         if(retreated && index-last_touch>=config.m5_touch_separation_bars)
           {
            result.touches++;
            if(current.close<setup.resistance &&
               (current.close<current.open ||
                BearUpperWick(current)>=BearBody(current)))
               result.rejections++;
            last_touch=index;
            retreated=false;
           }
        }
      const EngineBar previous=context[ArraySize(context)-2];
      const double range=BearRange(current);
      const double close_location=(range>0.0 ?
                                   (current.close-current.low)/range : 1.0);
      const bool momentum=current.close<current.open &&
                          close_location<=0.35 &&
                          (current.close<previous.low ||
                           BearBody(current)>=atr*0.45);
      const bool strong_failure=momentum &&
                                BearBody(current)>=atr*0.55 &&
                                current.high>=setup.resistance-tolerance;
      const bool repeated=result.touches>=config.m5_min_touches &&
                          result.rejections>=config.m5_min_rejections &&
                          momentum;
      if(strong_failure || repeated)
        {
         result.state=BEAR_M5_ARMED;
         result.armed_at=MathMax(
            available_at,current.open_time+PeriodSeconds(PERIOD_M5));
         result.atr=atr;
         result.recent_high=candidates[0].high;
         for(int item=1;item<=index;item++)
            result.recent_high=MathMax(
               result.recent_high,candidates[item].high);
         return result;
        }
     }
   return result;
  }

bool BearEntryOnM1(const BearSetup &setup,
                   const BearM5Result &arm,
                   const EngineBar &history[],
                   const EngineBar &candidates[],
                   const BearV4Config &config,
                   BearEntryPlan &plan)
  {
   plan.valid=false;
   const double zone_low=MathMin(setup.entry,setup.resistance);
   const double tolerance=MathMax(config.spread_floor,arm.atr*0.10);
   int touches=0;
   bool retreated=true;
   for(int index=0;index<ArraySize(candidates);index++)
     {
      if(index>=1 &&
         candidates[index-1].close>setup.resistance+tolerance &&
         candidates[index].close>setup.resistance+tolerance)
         return false;
      const EngineBar current=candidates[index];
      const bool touched=current.high>=zone_low-tolerance;
      if(!touched)
        {
         if(current.close<=zone_low-tolerance)
            retreated=true;
         continue;
        }
      if(retreated)
        {
         touches++;
         retreated=false;
        }
      EngineBar context[];
      BearCombineBars(history,candidates,index+1,context);
      if(ArraySize(context)<2)
         continue;
      const EngineBar previous=context[ArraySize(context)-2];
      const double range=BearRange(current);
      const double body_fraction=(range>0.0 ? BearBody(current)/range : 0.0);
      const double close_location=(range>0.0 ?
                                   (current.close-current.low)/range : 1.0);
      const bool micro_break=current.close<previous.low &&
                             current.close<current.open;
      const bool strong=body_fraction>=0.55 && close_location<=0.25;
      const bool ordinary=touches>=config.m1_min_touches &&
                          body_fraction>=config.m1_body_fraction &&
                          close_location<=config.m1_close_location;
      const double rsi_now=BearSimpleRsi(context,7);
      EngineBar prior_context[];
      ArrayResize(prior_context,ArraySize(context)-1);
      for(int item=0;item<ArraySize(prior_context);item++)
         prior_context[item]=context[item];
      const double rsi_previous=BearSimpleRsi(prior_context,7);
      const BearStochasticStats stochastic=BearStochastic(context,14,3);
      const bool oscillator_turn=rsi_now<rsi_previous ||
                                 (stochastic.k<stochastic.previous_k &&
                                  stochastic.k<stochastic.d);
      if(!(micro_break && oscillator_turn && (strong || ordinary)))
         continue;
      plan.armed_at=arm.armed_at;
      plan.opened_at=current.open_time+PeriodSeconds(PERIOD_M1);
      plan.entry=previous.low-config.price_tick;
      double observed_high=candidates[0].high;
      for(int item=1;item<=index;item++)
         observed_high=MathMax(observed_high,candidates[item].high);
      plan.structural_stop=MathMax(
         setup.resistance,MathMax(arm.recent_high,observed_high))+
         MathMax(config.spread_floor*2.0,
                 arm.atr*config.stop_buffer_atr_m5);
      plan.structural_target=setup.take_profit;
      plan.stop=plan.entry+
                (plan.structural_stop-plan.entry)*config.stop_multiplier;
      const double multiplied_target=plan.entry-
         (plan.entry-plan.structural_target)*config.target_multiplier;
      plan.target=(config.has_fixed_target_r ?
                   plan.entry-config.fixed_target_r*(plan.stop-plan.entry) :
                   multiplied_target);
      if(!(plan.target<plan.entry && plan.entry<plan.stop))
         return false;
      plan.m5_touches=arm.touches;
      plan.m5_rejections=arm.rejections;
      plan.m1_touches=touches;
      plan.valid=true;
      return true;
     }
   return false;
  }

#endif
