#ifndef GOLD_ENGINE_BEAR_SETUP_MQH
#define GOLD_ENGINE_BEAR_SETUP_MQH

#include "GoldEngineBearIndicators.mqh"

struct BearM15Config
  {
   int atr_period,regime_lookback,level_lookback,swing_span;
   double minimum_regime_drop_atr,maximum_regime_drop_atr;
   double maximum_slope_atr_per_bar,resistance_tolerance_atr;
   double maximum_breakout_overshoot_atr,maximum_chase_atr;
   double maximum_confirmed_failure_chase_atr,minimum_body_atr;
   double minimum_upper_wick_fraction,minimum_room_atr,minimum_reward_risk;
   double minimum_psychological_room_atr,minimum_psychological_reward_risk;
   double minimum_continuation_reward_risk,stop_buffer_atr,target_buffer_atr;
   double price_tick,spread_floor;
   int session_open_minute,session_close_minute,session_guard_minutes;
   int confluence_min_votes,fibonacci_lookback;
   double fibonacci_min_impulse_atr,fibonacci_retracement_low;
   double fibonacci_retracement_high;
   int rsi_period;
   double rsi_pullback_minimum,rsi_oversold_floor;
   int stochastic_period,stochastic_smoothing;
   double stochastic_pullback_minimum;
   int supply_lookback;
   double supply_displacement_atr,momentum_body_atr;
   int exhaustion_min_signals;
  };

struct BearLevel
  {
   double price;
   string kind;
  };

struct BearConfluence
  {
   bool qualified;
   int votes;
   double fibonacci_zone_low,fibonacci_zone_high;
   bool fibonacci_retest;
   double rsi_value;
   bool rsi_turn_down;
   double stochastic_k,stochastic_d;
   bool stochastic_turn_down;
   double supply_proximal,supply_distal;
   bool supply_retest,momentum_restart,exhausted;
  };

void LoadBearM15Config(BearM15Config &c,const double spread_floor)
  {
   c.atr_period=14;c.regime_lookback=32;c.level_lookback=24;c.swing_span=2;
   c.minimum_regime_drop_atr=1.25;c.maximum_regime_drop_atr=4.0;
   c.maximum_slope_atr_per_bar=0.025;c.resistance_tolerance_atr=0.28;
   c.maximum_breakout_overshoot_atr=0.85;c.maximum_chase_atr=1.25;
   c.maximum_confirmed_failure_chase_atr=1.75;c.minimum_body_atr=0.12;
   c.minimum_upper_wick_fraction=0.22;c.minimum_room_atr=0.60;
   c.minimum_reward_risk=0.70;c.minimum_psychological_room_atr=0.40;
   c.minimum_psychological_reward_risk=0.35;
   c.minimum_continuation_reward_risk=0.50;c.stop_buffer_atr=0.18;
   c.target_buffer_atr=0.08;c.price_tick=0.01;c.spread_floor=spread_floor;
   c.session_open_minute=62;c.session_close_minute=23*60+58;
   c.session_guard_minutes=15;c.confluence_min_votes=3;
   c.fibonacci_lookback=48;c.fibonacci_min_impulse_atr=1.50;
   c.fibonacci_retracement_low=0.382;c.fibonacci_retracement_high=0.618;
   c.rsi_period=7;c.rsi_pullback_minimum=50.0;c.rsi_oversold_floor=28.0;
   c.stochastic_period=14;c.stochastic_smoothing=3;
   c.stochastic_pullback_minimum=60.0;c.supply_lookback=48;
   c.supply_displacement_atr=1.0;c.momentum_body_atr=0.35;
   c.exhaustion_min_signals=2;
  }

double BearMinimumExecutableRr(const BearSetup &setup)
  {
   BearM15Config config;
   LoadBearM15Config(config,0.01);
   if(StringFind(
         setup.reason,"target_capped_at_nearest_psychological_support")>=0)
      return config.minimum_psychological_reward_risk;
   if(StringFind(setup.reason,"continuation_through_near_support")>=0)
      return config.minimum_continuation_reward_risk;
   return config.minimum_reward_risk;
  }

double BearLinearSlope(const double &values[])
  {
   const int n=ArraySize(values);
   if(n<=1)return 0.0;
   const double xm=(n-1)/2.0;
   double ym=0.0,num=0.0,den=0.0;
   for(int i=0;i<n;i++)ym+=values[i];
   ym/=n;
   for(int i=0;i<n;i++){num+=(i-xm)*(values[i]-ym);den+=(i-xm)*(i-xm);}
   return den>0.0 ? num/den : 0.0;
  }

double BearCeilToTick(const double value,const double tick)
  {return NormalizeDouble(MathCeil((value-1.0e-12)/tick)*tick,10);}

void BearAppendLevel(BearLevel &a[],const double p,const string k)
  {const int n=ArraySize(a);ArrayResize(a,n+1);a[n].price=p;a[n].kind=k;}

void BearSortLevels(BearLevel &a[],const bool descending=false)
  {
   for(int i=0;i<ArraySize(a);i++)for(int j=i+1;j<ArraySize(a);j++)
     {
      const bool swap=descending ? a[j].price>a[i].price : a[j].price<a[i].price;
      if(swap){const BearLevel t=a[i];a[i]=a[j];a[j]=t;}
     }
  }

void BearDeduplicateLevels(const BearLevel &source[],const double tolerance,BearLevel &out[])
  {
   BearLevel ordered[];ArrayResize(ordered,ArraySize(source));
   for(int source_index=0;source_index<ArraySize(source);source_index++)
      ordered[source_index]=source[source_index];
   BearSortLevels(ordered,false);
   ArrayResize(out,0);
   for(int i=0;i<ArraySize(ordered);i++)
     {
      const int n=ArraySize(out);
      if(n>0 && MathAbs(ordered[i].price-out[n-1].price)<=tolerance)
        {
         if(StringFind(ordered[i].kind,"psych_")==0 && out[n-1].kind=="swing")
            out[n-1].kind="swing_psych_confluence";
         continue;
        }
      ArrayResize(out,n+1);out[n]=ordered[i];
     }
  }

void BearSwingLevels(const EngineBar &bars[],const int span,const bool highs,BearLevel &out[])
  {
   ArrayResize(out,0);
   for(int i=span;i<ArraySize(bars)-span;i++)
     {
      const double pivot=highs ? bars[i].high : bars[i].low;
      bool ok=true;
      for(int d=1;d<=span;d++)
        {
         if((highs && (pivot<=bars[i-d].high || pivot<=bars[i+d].high)) ||
            (!highs && (pivot>=bars[i-d].low || pivot>=bars[i+d].low)))
           {ok=false;break;}
        }
      if(ok)BearAppendLevel(out,pivot,"swing");
     }
  }

void BearPsychologicalLevels(const double lower,const double upper,BearLevel &out[])
  {
   ArrayResize(out,0);const double steps[3]={10.0,50.0,100.0};
   for(int s=0;s<3;s++)
     {
      double p=MathFloor(lower/steps[s])*steps[s];
      while(p<=upper+steps[s])
        {
         if(p>=lower && p<=upper)
           {
            bool found=false;
            for(int i=0;i<ArraySize(out);i++)if(MathAbs(out[i].price-p)<=1e-9)
              {out[i].kind="psych_"+DoubleToString(steps[s],0);found=true;break;}
            if(!found)BearAppendLevel(out,p,"psych_"+DoubleToString(steps[s],0));
           }
         p+=steps[s];
        }
     }
  }

void BearSliceBars(const EngineBar &source[],const int start,const int end,EngineBar &out[])
  {
   const int a=MathMax(0,start),b=MathMin(ArraySize(source),MathMax(a,end));
   ArrayResize(out,b-a);for(int i=a;i<b;i++)out[i-a]=source[i];
  }

bool BearInsideSession(const datetime value,const BearM15Config &c)
  {
   MqlDateTime p;TimeToStruct(value,p);const int m=p.hour*60+p.min;
   return m>=c.session_open_minute+c.session_guard_minutes &&
          m<=c.session_close_minute-c.session_guard_minutes;
  }

BearConfluence BearM15Confluence(const EngineBar &bars[],const double atr,
                                 const BearM15Config &c)
  {
   BearConfluence r;ZeroMemory(r);const int n=ArraySize(bars);
   const EngineBar latest=bars[n-1],previous=bars[n-2];
   const double tolerance=MathMax(c.spread_floor,atr*0.08);
   const int fs=MathMax(0,n-1-c.fibonacci_lookback);
   double best=0.0,impulse_low=0.0;bool impulse=false;
   for(int hi=fs;hi<n-2;hi++)for(int lo=hi+1;lo<n-1;lo++)
     {
      const double drop=bars[hi].high-bars[lo].low;
      if(drop>best){best=drop;impulse_low=bars[lo].low;impulse=true;}
     }
   if(impulse && best>=atr*c.fibonacci_min_impulse_atr)
     {
      r.fibonacci_zone_low=impulse_low+best*c.fibonacci_retracement_low;
      r.fibonacci_zone_high=impulse_low+best*c.fibonacci_retracement_high;
      bool intersects=false;
      for(int i=MathMax(0,n-3);i<n;i++)
         if(bars[i].high>=r.fibonacci_zone_low-tolerance &&
            bars[i].low<=r.fibonacci_zone_high+tolerance)intersects=true;
      r.fibonacci_retest=intersects && latest.close<=r.fibonacci_zone_high+tolerance;
     }
   EngineBar prior[];BearSliceBars(bars,0,n-1,prior);
   const double prior_rsi=BearSimpleRsi(prior,c.rsi_period);
   r.rsi_value=BearSimpleRsi(bars,c.rsi_period);
   r.rsi_turn_down=prior_rsi>=c.rsi_pullback_minimum &&
                   r.rsi_value<prior_rsi && r.rsi_value>c.rsi_oversold_floor;
   const BearStochasticStats st=BearStochastic(bars,c.stochastic_period,c.stochastic_smoothing);
   r.stochastic_k=st.k;r.stochastic_d=st.d;
   r.stochastic_turn_down=st.recent_peak>=c.stochastic_pullback_minimum &&
                          st.k<st.previous_k && st.k<st.d;
   const int ss=MathMax(0,n-1-(c.supply_lookback+4));
   for(int i=n-5;i>=ss;i--)
     {
      int bears=0;double low=bars[i+1].low;
      for(int j=i+1;j<=i+3;j++){if(bars[j].close<bars[j].open)bears++;low=MathMin(low,bars[j].low);}
      if(bears>=2 && bars[i].high-low>=atr*c.supply_displacement_atr &&
         BearBody(bars[i])<=atr*0.80)
        {r.supply_proximal=MathMin(bars[i].open,bars[i].close);r.supply_distal=bars[i].high;break;}
     }
   if(r.supply_distal>0.0)
     {
      bool intersects=false;
      for(int i=MathMax(0,n-3);i<n;i++)
         if(bars[i].high>=r.supply_proximal-tolerance &&
            bars[i].low<=r.supply_distal+tolerance)intersects=true;
      r.supply_retest=intersects && latest.close<=r.supply_distal+tolerance;
     }
   const double range=BearRange(latest);
   const double loc=range>0.0 ? (latest.close-latest.low)/range : 1.0;
   r.momentum_restart=latest.close<latest.open && loc<=0.40 &&
      (latest.close<previous.low || BearBody(latest)>=atr*c.momentum_body_atr);
   int exhaustion=0;
   if(BearBody(latest)<BearBody(previous))exhaustion++;
   if(BearRange(latest)<BearRange(previous))exhaustion++;
   if(r.rsi_value<=c.rsi_oversold_floor)exhaustion++;
   if(r.stochastic_k<=20.0)exhaustion++;
   r.exhausted=exhaustion>=c.exhaustion_min_signals;
   r.votes=(r.fibonacci_retest?1:0)+(r.rsi_turn_down?1:0)+
           (r.stochastic_turn_down?1:0)+(r.supply_retest?1:0)+
           (r.momentum_restart?1:0);
   r.qualified=r.votes>=c.confluence_min_votes && r.momentum_restart &&
               (r.fibonacci_retest || r.supply_retest) && !r.exhausted;
   return r;
  }

bool BearM15Setup(const EngineBar &bars[],const string symbol,const double spread_floor,
                  BearSetup &setup,string &reason)
  {
   reason="";BearM15Config c;LoadBearM15Config(c,spread_floor);const int n=ArraySize(bars);
   if(n<50){reason="insufficient_history";return false;}
   for(int i=1;i<n;i++)if(bars[i].open_time<=bars[i-1].open_time)
     {reason="bars_not_strictly_ordered";return false;}
   const EngineBar latest=bars[n-1],previous=bars[n-2];
   if(!BearInsideSession(latest.open_time,c)){reason="outside_trade_session";return false;}
   double atr=0.0;if(!BearAverageTrueRange(bars,c.atr_period,atr)||atr<=0.0)
     {reason="zero_volatility";return false;}
   double closes[];ArrayResize(closes,c.regime_lookback);const int rs=n-c.regime_lookback;
   double regime_high=bars[rs].high;
   for(int i=0;i<c.regime_lookback;i++)
     {closes[i]=bars[rs+i].close;if(i<c.regime_lookback-1)regime_high=MathMax(regime_high,bars[rs+i].high);}
   const double slope=BearLinearSlope(closes)/atr;
   const double regime_drop=(regime_high-latest.close)/atr;
   if(slope>c.maximum_slope_atr_per_bar||regime_drop<c.minimum_regime_drop_atr)
     {reason="bear_regime_not_confirmed";return false;}
   if(regime_drop>c.maximum_regime_drop_atr){reason="bear_move_overextended";return false;}
   EngineBar history[];BearSliceBars(bars,n-(c.level_lookback+1),n-1,history);
   EngineBar recent[];BearSliceBars(bars,n-4,n,recent);
   const double tolerance=c.resistance_tolerance_atr*atr;
   const double overshoot=c.maximum_breakout_overshoot_atr*atr;
   BearLevel swings[];BearSwingLevels(history,c.swing_span,true,swings);
   BearLevel psych[];BearPsychologicalLevels(latest.low-tolerance,latest.high+tolerance,psych);
   BearLevel raw_res[];ArrayResize(raw_res,ArraySize(swings));
   for(int swing_index=0;swing_index<ArraySize(swings);swing_index++)
      raw_res[swing_index]=swings[swing_index];
   const int sn=ArraySize(raw_res);
   ArrayResize(raw_res,sn+ArraySize(psych));for(int i=0;i<ArraySize(psych);i++)raw_res[sn+i]=psych[i];
   BearLevel dedup[];BearDeduplicateLevels(raw_res,MathMax(0.01,atr*0.04),dedup);
   BearLevel valid[];
   for(int l=0;l<ArraySize(dedup);l++)
     {
      bool touched=false;for(int i=0;i<ArraySize(recent);i++)
         if(recent[i].high>=dedup[l].price-tolerance&&recent[i].high<=dedup[l].price+overshoot)touched=true;
      if(touched&&latest.close<=dedup[l].price+tolerance)BearAppendLevel(valid,dedup[l].price,dedup[l].kind);
     }
   if(ArraySize(valid)==0){reason="no_resistance_retest";return false;}
   int nearest=0;for(int i=1;i<ArraySize(valid);i++)
      if(MathAbs(valid[i].price-latest.high)<MathAbs(valid[nearest].price-latest.high))nearest=i;
   const BearLevel resistance=valid[nearest];const double chase=resistance.price-latest.close;
   const bool failure=latest.close<previous.low&&latest.close<latest.open&&BearBody(latest)>=0.65*atr;
   if(chase<-tolerance){reason="resistance_broken_upward";return false;}
   if(chase>c.maximum_chase_atr*atr&&(!failure||chase>c.maximum_confirmed_failure_chase_atr*atr))
     {reason="sell_move_already_extended";return false;}
   const double range=BearRange(latest);
   const bool body_rejection=latest.close<latest.open&&BearBody(latest)>=c.minimum_body_atr*atr&&
      latest.close<previous.close&&latest.close<previous.low;
   const double wick_fraction=range>0.0?BearUpperWick(latest)/range:0.0;
   const bool wick_rejection=wick_fraction>=c.minimum_upper_wick_fraction&&
      latest.close<=latest.low+0.55*range&&latest.close<previous.close&&latest.close<previous.low;
   if(latest.close>resistance.price+tolerance||!(body_rejection||wick_rejection))
     {reason="pullback_at_"+resistance.kind+"_resistance_waiting_rejection";return false;}
   const BearConfluence conf=BearM15Confluence(bars,atr,c);
   if(!conf.qualified){reason="rejection_confirmed_waiting_confluence";return false;}
   const double entry=latest.close;double recent_high=recent[0].high;
   for(int i=1;i<ArraySize(recent);i++)recent_high=MathMax(recent_high,recent[i].high);
   const double bar_spread=MathMax(latest.spread_points*c.price_tick,c.spread_floor);
   const double stop=BearCeilToTick(MathMax(recent_high,resistance.price)+
      MathMax(atr*c.stop_buffer_atr,bar_spread*2.0),c.price_tick);
   BearLevel swing_support[];BearSwingLevels(history,c.swing_span,false,swing_support);
   BearLevel raw_support[];for(int i=0;i<ArraySize(swing_support);i++)
      if(swing_support[i].price<entry)BearAppendLevel(raw_support,swing_support[i].price,"swing");
   double lower=history[0].low;for(int i=1;i<ArraySize(history);i++)lower=MathMin(lower,history[i].low);
   BearLevel psych_support[];BearPsychologicalLevels(lower,entry,psych_support);
   for(int i=0;i<ArraySize(psych_support);i++)if(psych_support[i].price<entry)
      BearAppendLevel(raw_support,psych_support[i].price,psych_support[i].kind);
   BearLevel supports[];BearDeduplicateLevels(raw_support,0.02,supports);BearSortLevels(supports,true);
   if(ArraySize(supports)==0){reason="no_support_or_psychological_target";return false;}
   double targets[];const double buffer=atr*c.target_buffer_atr;
   for(int i=0;i<ArraySize(supports)&&ArraySize(targets)<2;i++)
     {
      const double target=BearCeilToTick(supports[i].price+buffer,c.price_tick);
      if(target>=entry)continue;bool duplicate=false;
      for(int j=0;j<ArraySize(targets);j++)if(MathAbs(target-targets[j])<=0.02)duplicate=true;
      if(!duplicate){const int k=ArraySize(targets);ArrayResize(targets,k+1);targets[k]=target;}
     }
   if(ArraySize(targets)==0){reason="insufficient_room_before_support";return false;}
   double tp=targets[0];const double risk=stop-entry;double reward=entry-tp;
   double rr=risk>0.0?reward/risk:0.0;const bool psych_near=StringFind(supports[0].kind,"psych")>=0;
   double required_room=psych_near?c.minimum_psychological_room_atr:c.minimum_room_atr;
   double required_rr=psych_near?c.minimum_psychological_reward_risk:c.minimum_reward_risk;
   bool continuation=false;
   if((reward<required_room*atr||rr<required_rr)&&failure&&ArraySize(targets)>1)
     {
      const double cr=entry-targets[1],crr=risk>0.0?cr/risk:0.0;
      if(cr>=c.minimum_room_atr*atr&&crr>=c.minimum_continuation_reward_risk)
        {tp=targets[1];reward=cr;rr=crr;continuation=true;required_room=c.minimum_room_atr;required_rr=c.minimum_continuation_reward_risk;}
     }
   if(reward<required_room*atr){reason="rejection_confirmed_but_nearest_barrier_too_close";return false;}
   if(rr<required_rr){reason="rejection_confirmed_but_reward_risk_too_small";return false;}
   ZeroMemory(setup);setup.time=latest.open_time;setup.symbol=symbol;
   setup.reason="bear_pullback_rejected_at_"+resistance.kind+"_resistance"+
      (continuation?"_continuation_through_near_support":psych_near?"_target_capped_at_nearest_psychological_support":"");
   setup.score=(int)MathRound(MathMin(100.0,15.0+MathMin(25.0,MathAbs(MathMin(0.0,slope))*500.0)+
      MathMin(30.0,regime_drop*7.5)+30.0));
   setup.resistance=resistance.price;setup.resistance_kind=resistance.kind;setup.support=supports[0].price;
   setup.entry=entry;setup.stop=stop;setup.take_profit=tp;
   setup.take_profit_2=(!continuation&&ArraySize(targets)>1)?targets[1]:0.0;setup.reward_risk=rr;
   setup.atr=atr;setup.regime_slope_atr=slope;setup.regime_drop_atr=regime_drop;setup.chase_distance_atr=chase/atr;
   setup.confluence_votes=conf.votes;setup.fibonacci_zone_low=conf.fibonacci_zone_low;
   setup.fibonacci_zone_high=conf.fibonacci_zone_high;setup.fibonacci_retest=conf.fibonacci_retest;
   setup.rsi_value=conf.rsi_value;setup.rsi_turn_down=conf.rsi_turn_down;
   setup.stochastic_k=conf.stochastic_k;setup.stochastic_d=conf.stochastic_d;
   setup.stochastic_turn_down=conf.stochastic_turn_down;setup.supply_proximal=conf.supply_proximal;
   setup.supply_distal=conf.supply_distal;setup.supply_retest=conf.supply_retest;
   setup.momentum_restart=conf.momentum_restart;setup.exhausted=conf.exhausted;reason=setup.reason;
   return true;
  }

#endif
