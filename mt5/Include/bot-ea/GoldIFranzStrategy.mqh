#ifndef GOLDI_FRANZ_STRATEGY_MQH
#define GOLDI_FRANZ_STRATEGY_MQH

#include "GoldIFranzTypes.mqh"

#define FRANZ_STRATEGY_ID "GOLDI_FRANZ_SHAKEOUT"
#define FRANZ_STRATEGY_VERSION "0.1.0"
#define FRANZ_PROFILE_ID "GOLDI_FRANZ"
#define FRANZ_PROFILE_FINGERPRINT "03e01f661bf71ff36c6e750800bb549c53b7f2f72257de649cf1199dcc9a76db"
#define FRANZ_SYMBOL "GOLD.i#"
#define FRANZ_MAGIC 26081914

double FranzClamp(const double value,const double lower,const double upper)
  {
   return MathMin(upper,MathMax(lower,value));
  }

double FranzRange(const FranzBar &bar)
  {
   return MathMax(0.0,bar.high-bar.low);
  }

double FranzBody(const FranzBar &bar)
  {
   return MathAbs(bar.close-bar.open);
  }

bool FranzFinitePositive(const double value)
  {
   return MathIsValidNumber(value) && value>0.0;
  }

double FranzAlignUp(const double value,const double tick_size)
  {
   return NormalizeDouble(MathCeil((value-1e-12)/tick_size)*tick_size,8);
  }

double FranzAlignDown(const double value,const double tick_size)
  {
   return NormalizeDouble(MathFloor((value+1e-12)/tick_size)*tick_size,8);
  }

double FranzMedian(double &values[])
  {
   const int count=ArraySize(values);
   if(count<=0) return 0.0;
   ArraySort(values);
   if((count%2)==1) return values[count/2];
   return (values[count/2-1]+values[count/2])/2.0;
  }

double FranzMedianTrueRange(const FranzBar &bars[],const int start,const int count)
  {
   if(start<0 || count<=0 || start+count>=ArraySize(bars)) return 0.0;
   double values[];
   ArrayResize(values,count);
   for(int index=0;index<count;index++)
     {
      const int cursor=start+index;
      const double previous_close=bars[cursor+1].close;
      values[index]=MathMax(
         bars[cursor].high-bars[cursor].low,
         MathMax(MathAbs(bars[cursor].high-previous_close),
                 MathAbs(bars[cursor].low-previous_close)));
     }
   return FranzMedian(values);
  }

double FranzEfficiencyRatio(const FranzBar &bars[],const int count=12)
  {
   if(count<2 || ArraySize(bars)<count) return -1.0;
   const double net=MathAbs(bars[0].close-bars[count-1].close);
   double path=0.0;
   for(int index=0;index<count-1;index++)
      path+=MathAbs(bars[index].close-bars[index+1].close);
   return path>0.0 ? net/path : 0.0;
  }

bool FranzPivotHigh(const FranzBar &bars[],const int index)
  {
   if(index<2 || index+2>=ArraySize(bars)) return false;
   return bars[index].high>bars[index-1].high &&
          bars[index].high>bars[index-2].high &&
          bars[index].high>=bars[index+1].high &&
          bars[index].high>=bars[index+2].high;
  }

bool FranzPivotLow(const FranzBar &bars[],const int index)
  {
   if(index<2 || index+2>=ArraySize(bars)) return false;
   return bars[index].low<bars[index-1].low &&
          bars[index].low<bars[index-2].low &&
          bars[index].low<=bars[index+1].low &&
          bars[index].low<=bars[index+2].low;
  }

double FranzProjectTrendline(const FranzTrendlineZone &zone,const datetime at_time)
  {
   if(!zone.valid) return 0.0;
   return zone.center_at_projection+
          zone.slope_per_second*(double)(at_time-zone.projected_at);
  }

bool FranzBuildTrendlineZone(const FranzBar &bars[],
                             const bool bull_support,
                             const datetime projected_at,
                             const double median_range,
                             const double spread,
                             FranzTrendlineZone &zone)
  {
   FranzResetTrendlineZone(zone);
   int newer=-1,older=-1;
   for(int index=2;index<ArraySize(bars)-2;index++)
     {
      const bool pivot=(bull_support ? FranzPivotLow(bars,index) :
                                      FranzPivotHigh(bars,index));
      if(!pivot) continue;
      if(newer<0) newer=index;
      else { older=index; break; }
     }
   if(newer<0 || older<0) return false;
   const double newer_price=(bull_support ? bars[newer].low : bars[newer].high);
   const double older_price=(bull_support ? bars[older].low : bars[older].high);
   const datetime newer_time=bars[newer].close_time;
   const datetime older_time=bars[older].close_time;
   if(newer_time<=older_time || !FranzFinitePositive(median_range)) return false;
   const double slope=(newer_price-older_price)/(double)(newer_time-older_time);
   const double projected=newer_price+slope*(double)(projected_at-newer_time);
   const double half_width=MathMax(2.0*spread,0.15*median_range);
   int touches=0;
   for(int index=2;index<ArraySize(bars)-2;index++)
     {
      const bool pivot=(bull_support ? FranzPivotLow(bars,index) :
                                      FranzPivotHigh(bars,index));
      if(!pivot) continue;
      const double price=(bull_support ? bars[index].low : bars[index].high);
      const double line=older_price+slope*(double)(bars[index].close_time-older_time);
      if(MathAbs(price-line)<=half_width) touches++;
     }
   zone.valid=touches>=2;
   zone.projected_at=projected_at;
   zone.center_at_projection=projected;
   zone.slope_per_second=slope;
   zone.half_width=half_width;
   zone.touches=touches;
   return zone.valid;
  }

bool FranzInitialTrendlineBreak(const FranzSide side,
                                const FranzBar &current,
                                const FranzBar &previous,
                                const FranzTrendlineZone &bull_zone,
                                const FranzTrendlineZone &bear_zone,
                                double &break_level)
  {
   break_level=0.0;
   if(side==FRANZ_SIDE_SELL && bull_zone.valid)
     {
      const double current_level=FranzProjectTrendline(bull_zone,current.close_time)-
         bull_zone.half_width;
      const double previous_level=FranzProjectTrendline(bull_zone,previous.close_time)-
         bull_zone.half_width;
      if(previous.close>=previous_level && current.close<current_level)
        { break_level=current_level; return true; }
     }
   if(side==FRANZ_SIDE_BUY && bear_zone.valid)
     {
      const double current_level=FranzProjectTrendline(bear_zone,current.close_time)+
         bear_zone.half_width;
      const double previous_level=FranzProjectTrendline(bear_zone,previous.close_time)+
         bear_zone.half_width;
      if(previous.close<=previous_level && current.close>current_level)
        { break_level=current_level; return true; }
     }
   return false;
  }

double FranzBarOverlapRatio(const FranzBar &left,const FranzBar &right)
  {
   const double minimum_range=MathMin(FranzRange(left),FranzRange(right));
   if(minimum_range<=0.0) return 0.0;
   const double overlap=MathMax(0.0,
      MathMin(left.high,right.high)-MathMax(left.low,right.low));
   return overlap/minimum_range;
  }

bool FranzBuildSwingZone(const FranzBar &bars[],
                         const int pivot_index,
                         const bool supply,
                         const double median_range,
                         FranzSwingZone &zone)
  {
   FranzResetSwingZone(zone);
   if(pivot_index<3 || pivot_index+1>=ArraySize(bars) ||
      !FranzFinitePositive(median_range)) return false;
   const bool pivot=(supply ? FranzPivotHigh(bars,pivot_index) :
                              FranzPivotLow(bars,pivot_index));
   if(!pivot) return false;
   const double pivot_range=FranzRange(bars[pivot_index]);
   if(pivot_range<=0.0 || FranzBody(bars[pivot_index])/pivot_range>0.55)
      return false;
   int base_end=pivot_index;
   for(int index=pivot_index+1;
       index<ArraySize(bars) && index<=pivot_index+3;index++)
     {
      const double range=FranzRange(bars[index]);
      if(range<=0.0 || FranzBody(bars[index])/range>0.55 ||
         FranzBarOverlapRatio(bars[index-1],bars[index])<0.50) break;
      base_end=index;
     }
   double distal=(supply ? -DBL_MAX : DBL_MAX);
   double proximal=(supply ? DBL_MAX : -DBL_MAX);
   for(int index=pivot_index;index<=base_end;index++)
     {
      if(supply)
        {
         distal=MathMax(distal,bars[index].high);
         proximal=MathMin(proximal,MathMin(bars[index].open,bars[index].close));
        }
      else
        {
         distal=MathMin(distal,bars[index].low);
         proximal=MathMax(proximal,MathMax(bars[index].open,bars[index].close));
        }
     }
   const double width=MathAbs(distal-proximal);
   if(width<=0.0 || width>median_range) return false;
   const int departure_end=MathMax(0,pivot_index-3);
   const double departure=(supply ? bars[pivot_index].close-bars[departure_end].close :
                                     bars[departure_end].close-bars[pivot_index].close);
   if(departure<1.5*median_range) return false;
   double directional=0.0,total=0.0;
   for(int index=pivot_index-1;index>=departure_end;index--)
     {
      const double body=FranzBody(bars[index]);
      total+=body;
      if((supply && bars[index].close<bars[index].open) ||
         (!supply && bars[index].close>bars[index].open)) directional+=body;
     }
   if(total<=0.0 || directional/total<0.65) return false;

   int bounces=0;
   datetime last_touch=0;
   bool inside=false,penetrated=false;
   for(int index=pivot_index-1;index>=0;index--)
     {
      const bool enters=(supply ? bars[index].high>=proximal : bars[index].low<=proximal);
      const bool beyond=(supply ? bars[index].close>distal : bars[index].close<distal);
      if(enters && !inside) { inside=true; penetrated=false; last_touch=bars[index].close_time; }
      if(inside && beyond) penetrated=true;
      const bool exits_origin_side=(supply ? bars[index].close<proximal :
                                               bars[index].close>proximal);
      if(inside && exits_origin_side)
        {
         if(!penetrated) bounces++;
         inside=false;
        }
     }
   int outside=0;
   const int recent=MathMin(4,pivot_index);
   for(int index=0;index<recent;index++)
      if(supply ? bars[index].close>distal : bars[index].close<distal) outside++;
   const bool consecutive=recent>=2 && (supply ?
      bars[0].close>distal && bars[1].close>distal :
      bars[0].close<distal && bars[1].close<distal);
   zone.valid=true;
   zone.supply=supply;
   zone.created_at=bars[pivot_index].close_time;
   zone.proximal=proximal;
   zone.distal=distal;
   zone.median_range=median_range;
   zone.departure_strength=departure/median_range;
   zone.bounces=bounces;
   zone.last_touch_at=last_touch;
   zone.invalidated=consecutive || (recent>=4 && outside>=3);
   return !zone.invalidated;
  }

bool FranzFindSwingZone(const FranzBar &bars[],
                        const bool supply,
                        const double price,
                        FranzSwingZone &zone)
  {
   FranzResetSwingZone(zone);
   const double median=FranzMedianTrueRange(bars,0,20);
   if(!FranzFinitePositive(median)) return false;
   double distance=DBL_MAX;
   for(int index=3;index<ArraySize(bars)-4 && index<=240;index++)
     {
      FranzSwingZone candidate;
      if(!FranzBuildSwingZone(bars,index,supply,median,candidate)) continue;
      const double lower=MathMin(candidate.proximal,candidate.distal);
      const double upper=MathMax(candidate.proximal,candidate.distal);
      const double current=(price<lower ? lower-price : (price>upper ? price-upper : 0.0));
      if(current<distance)
        {
         distance=current;
         zone=candidate;
        }
     }
   return zone.valid;
  }

bool FranzMergeSwingZones(const FranzSwingZone &first,
                          const FranzSwingZone &second,
                          const double median_range,
                          FranzSwingZone &merged)
  {
   if(!first.valid) { merged=second; return second.valid; }
   if(!second.valid) { merged=first; return first.valid; }
   if(first.supply!=second.supply) return false;
   const double first_low=MathMin(first.proximal,first.distal);
   const double first_high=MathMax(first.proximal,first.distal);
   const double second_low=MathMin(second.proximal,second.distal);
   const double second_high=MathMax(second.proximal,second.distal);
   const double gap=MathMax(0.0,MathMax(first_low,second_low)-
      MathMin(first_high,second_high));
   if(gap>0.25*median_range) return false;
   merged=first;
   if(first.supply)
     {
      merged.proximal=MathMin(first.proximal,second.proximal);
      merged.distal=MathMax(first.distal,second.distal);
     }
   else
     {
      merged.proximal=MathMax(first.proximal,second.proximal);
      merged.distal=MathMin(first.distal,second.distal);
     }
   merged.created_at=MathMax(first.created_at,second.created_at);
   merged.departure_strength=MathMax(first.departure_strength,second.departure_strength);
   merged.bounces=first.bounces+second.bounces;
   merged.last_touch_at=MathMax(first.last_touch_at,second.last_touch_at);
   merged.invalidated=first.invalidated || second.invalidated;
   return !merged.invalidated;
  }

bool FranzPriceInSwingZone(const FranzSwingZone &zone,
                           const double price,
                           const double tolerance)
  {
   if(!zone.valid || zone.invalidated) return false;
   const double lower=MathMin(zone.proximal,zone.distal)-tolerance;
   const double upper=MathMax(zone.proximal,zone.distal)+tolerance;
   return price>=lower && price<=upper;
  }

int FranzSwingDirection(const FranzBar &bars[])
  {
   double newest_high=0.0,previous_high=0.0;
   double newest_low=0.0,previous_low=0.0;
   int highs=0,lows=0;
   for(int index=2;index<ArraySize(bars)-2 && (highs<2 || lows<2);index++)
     {
      if(highs<2 && FranzPivotHigh(bars,index))
        {
         if(highs==0) newest_high=bars[index].high;
         else previous_high=bars[index].high;
         highs++;
        }
      if(lows<2 && FranzPivotLow(bars,index))
        {
         if(lows==0) newest_low=bars[index].low;
         else previous_low=bars[index].low;
         lows++;
        }
     }
   if(highs<2 || lows<2) return 0;
   if(newest_high>previous_high && newest_low>previous_low) return 1;
   if(newest_high<previous_high && newest_low<previous_low) return -1;
   return 0;
  }

FranzMode FranzSelectMode(const int d1_direction,
                          const int h4_direction,
                          const int h1_direction,
                          const FranzSide reversal_side,
                          const double h1_efficiency)
  {
   const int required=(reversal_side==FRANZ_SIDE_BUY ? 1 : -1);
   if(d1_direction==required && h4_direction==required && h1_direction==required)
      return FRANZ_MODE_SNIPER_TREND;
   if(!(d1_direction==h4_direction && h4_direction==h1_direction && h1_direction!=0) &&
      h1_efficiency>=0.0 && h1_efficiency<=0.35)
      return FRANZ_MODE_HANDGUN_RANGE;
   return FRANZ_MODE_NONE;
  }

bool FranzEvaluateImpulse(const FranzBar &bars[],
                          FranzSide &reversal_side,
                          double &anchor_a,
                          double &extreme_b,
                          double &median_range,
                          int &impulse_bars,
                          bool &terminal_wick,
                          string &reason)
  {
   reversal_side=FRANZ_SIDE_NONE;
   anchor_a=0.0;
   extreme_b=0.0;
   median_range=FranzMedianTrueRange(bars,0,20);
   impulse_bars=0;
   terminal_wick=false;
   if(!FranzFinitePositive(median_range) || ArraySize(bars)<30)
     { reason="M15_WARMUP_INCOMPLETE"; return false; }

   for(int length=3;length<=8;length++)
     {
      const double displacement=bars[0].close-bars[length-1].open;
      if(MathAbs(displacement)<2.0*median_range) continue;
      const bool upward=displacement>0.0;
      double directional_body=0.0,total_body=0.0,total_overlap=0.0;
      for(int index=0;index<length;index++)
        {
         const double body=FranzBody(bars[index]);
         total_body+=body;
         if((upward && bars[index].close>bars[index].open) ||
            (!upward && bars[index].close<bars[index].open)) directional_body+=body;
         if(index<length-1)
           {
            const double minimum_range=MathMin(FranzRange(bars[index]),
                                                FranzRange(bars[index+1]));
            const double overlap=MathMax(0.0,
               MathMin(bars[index].high,bars[index+1].high)-
               MathMax(bars[index].low,bars[index+1].low));
            total_overlap+=(minimum_range>0.0 ? overlap/minimum_range : 1.0);
           }
        }
      const double body_share=(total_body>0.0 ? directional_body/total_body : 0.0);
      const double overlap_average=total_overlap/(length-1);
      if(body_share<0.65 || overlap_average>0.35) continue;
      reversal_side=(upward ? FRANZ_SIDE_SELL : FRANZ_SIDE_BUY);
      anchor_a=(upward ? bars[length-1].low : bars[length-1].high);
      extreme_b=(upward ? bars[0].high : bars[0].low);
      const double terminal_range=FranzRange(bars[0]);
      const double wick=(upward ? bars[0].high-MathMax(bars[0].open,bars[0].close) :
                                  MathMin(bars[0].open,bars[0].close)-bars[0].low);
      terminal_wick=terminal_range>0.0 && wick/terminal_range>=0.35;
      impulse_bars=length;
      reason="IMPULSE_CONFIRMED";
      return true;
     }
   reason="IMPULSE_NOT_EXTREME";
   return false;
  }

bool FranzNearestSwing(const FranzBar &bars[],
                       const FranzSide side,
                       const double price,
                       double &level)
  {
   level=0.0;
   double distance=DBL_MAX;
   for(int index=2;index<ArraySize(bars)-2;index++)
     {
      const bool valid=(side==FRANZ_SIDE_SELL ? FranzPivotHigh(bars,index) :
                                                 FranzPivotLow(bars,index));
      if(!valid) continue;
      const double candidate=(side==FRANZ_SIDE_SELL ? bars[index].high : bars[index].low);
      const double current=MathAbs(candidate-price);
      if(current<distance) { distance=current; level=candidate; }
     }
   return level>0.0;
  }

bool FranzComputeFibonacci(const FranzSide side,
                           const double anchor_a,
                           const double extreme_b,
                           FranzFibonacci &fib)
  {
   FranzResetFibonacci(fib);
   const double range=MathAbs(extreme_b-anchor_a);
   if(!FranzFinitePositive(anchor_a) || !FranzFinitePositive(extreme_b) || range<=0.0)
      return false;
   if(side==FRANZ_SIDE_SELL && extreme_b<=anchor_a) return false;
   if(side==FRANZ_SIDE_BUY && extreme_b>=anchor_a) return false;
   const double direction=(side==FRANZ_SIDE_BUY ? 1.0 : -1.0);
   fib.locked=true;
   fib.anchor_a=anchor_a;
   fib.anchor_b=extreme_b;
   fib.range=range;
   fib.level_236=extreme_b+direction*0.236*range;
   fib.level_382=extreme_b+direction*0.382*range;
   fib.level_500=extreme_b+direction*0.500*range;
   fib.level_618=extreme_b+direction*0.618*range;
   fib.level_1000=extreme_b+direction*1.000*range;
   fib.level_1130=extreme_b-direction*0.130*range;
   fib.level_1272=extreme_b+direction*1.272*range;
   return true;
  }

bool FranzClusterEvidence(const FranzBar &bars[],
                          const FranzSide side,
                          const double reference,
                          const double touch_tolerance,
                          const double tick_size,
                          int &touches,
                          int &direction_changes,
                          double &cluster_high,
                          double &cluster_low,
                          double &sweep_extreme)
  {
   touches=0;
   direction_changes=0;
   cluster_high=-DBL_MAX;
   cluster_low=DBL_MAX;
   sweep_extreme=(side==FRANZ_SIDE_SELL ? -DBL_MAX : DBL_MAX);
   const int count=MathMin(12,ArraySize(bars));
   if(count<4) return false;
   int previous_direction=0,last_touch=-100;
   bool excursion_after_touch=true;
   for(int index=count-1;index>=0;index--)
     {
      cluster_high=MathMax(cluster_high,bars[index].high);
      cluster_low=MathMin(cluster_low,bars[index].low);
      const int direction=(bars[index].close>bars[index].open ? 1 :
                           (bars[index].close<bars[index].open ? -1 : 0));
      if(direction!=0 && previous_direction!=0 && direction!=previous_direction)
         direction_changes++;
      if(direction!=0) previous_direction=direction;
      const bool touch=(side==FRANZ_SIDE_SELL ?
         bars[index].high>=reference-touch_tolerance :
         bars[index].low<=reference+touch_tolerance);
      if(last_touch>=0)
        {
         const double away=(side==FRANZ_SIDE_SELL ? reference-bars[index].low :
                                                    bars[index].high-reference);
         if(away>=0.25*MathMax(tick_size,cluster_high-cluster_low))
            excursion_after_touch=true;
        }
      if(touch && (last_touch<0 || MathAbs(index-last_touch)>=2) && excursion_after_touch)
        {
         touches++;
         last_touch=index;
         excursion_after_touch=false;
        }
      if(side==FRANZ_SIDE_SELL) sweep_extreme=MathMax(sweep_extreme,bars[index].high);
      else sweep_extreme=MathMin(sweep_extreme,bars[index].low);
     }
   const bool swept=(side==FRANZ_SIDE_SELL ? sweep_extreme>=reference+tick_size :
                                            sweep_extreme<=reference-tick_size);
   return touches>=2 && direction_changes>=3 && swept;
  }

bool FranzStochasticReinforced(const FranzSide side,
                               const double k1,
                               const double d1,
                               const double k2,
                               const double d2,
                               const double k_previous_sweep,
                               const double k_current_sweep)
  {
   if(side==FRANZ_SIDE_SELL)
      return k2>=d2 && k1<d1 && (MathMax(k1,k2)>=80.0 ||
             k_current_sweep<k_previous_sweep);
   if(side==FRANZ_SIDE_BUY)
      return k2<=d2 && k1>d1 && (MathMin(k1,k2)<=20.0 ||
             k_current_sweep>k_previous_sweep);
   return false;
  }

int FranzRsiVotes(const FranzSide side,
                  const double previous_price_extreme,
                  const double current_price_extreme,
                  const double previous_rsi_extreme,
                  const double current_rsi_extreme,
                  const double rsi1,
                  const double rsi2,
                  const double rsi3,
                  const double rsi_m5_1,
                  const double rsi_m5_3)
  {
   int votes=0;
   if(side==FRANZ_SIDE_SELL)
     {
      if(current_price_extreme>previous_price_extreme &&
         current_rsi_extreme<=previous_rsi_extreme-3.0) votes++;
      if(rsi2>=60.0 && rsi1<60.0 && rsi1<rsi2 && rsi2<rsi3) votes++;
      if(rsi_m5_1<rsi_m5_3) votes++;
     }
   else if(side==FRANZ_SIDE_BUY)
     {
      if(current_price_extreme<previous_price_extreme &&
         current_rsi_extreme>=previous_rsi_extreme+3.0) votes++;
      if(rsi2<=40.0 && rsi1>40.0 && rsi1>rsi2 && rsi2>rsi3) votes++;
      if(rsi_m5_1>rsi_m5_3) votes++;
     }
   return votes;
  }

bool FranzFailedBreakConfirmed(const FranzBar &bars[],
                               const FranzSide side,
                               const double reference,
                               const double rejection_high,
                               const double rejection_low,
                               const bool stochastic_reinforced,
                               int &reentry_closes,
                               bool &micro_break,
                               bool &accepted_outside,
                               string &reason)
  {
   reentry_closes=0;
   micro_break=false;
   accepted_outside=false;
   const int count=MathMin(4,ArraySize(bars));
   if(count<2) { reason="BREAK_WARMUP_INCOMPLETE"; return false; }
   int outside=0;
   for(int index=0;index<count;index++)
     {
      const bool is_outside=(side==FRANZ_SIDE_SELL ? bars[index].close>reference :
                                                       bars[index].close<reference);
      if(is_outside) outside++;
      else reentry_closes++;
     }
   const bool consecutive=(side==FRANZ_SIDE_SELL ?
      bars[0].close>reference && bars[1].close>reference :
      bars[0].close<reference && bars[1].close<reference);
   accepted_outside=consecutive || (count>=4 && outside>=3);
   if(accepted_outside) { reason="BREAK_ACCEPTED_OUTSIDE"; return false; }
   micro_break=(side==FRANZ_SIDE_SELL ? bars[0].close<rejection_low :
                                       bars[0].close>rejection_high);
   const int required_reentries=(stochastic_reinforced ? 1 : 2);
   if(reentry_closes>=required_reentries && micro_break)
     { reason="BREAK_FAILED_CONFIRMED"; return true; }
   reason="BREAK_FAILURE_INCOMPLETE";
   return false;
  }

bool FranzFibReclaimed(const FranzSide side,const FranzFibonacci &fib,const double close)
  {
   if(!fib.locked) return false;
   return side==FRANZ_SIDE_BUY ? close>=fib.level_236 : close<=fib.level_236;
  }

bool FranzFibRetest(const FranzSide side,const FranzFibonacci &fib,const FranzBar &bar)
  {
   if(!fib.locked) return false;
   const double deep_level=(side==FRANZ_SIDE_BUY ?
      fib.anchor_b+0.146*fib.range : fib.anchor_b-0.146*fib.range);
   const double lower=MathMin(fib.anchor_b,deep_level);
   const double upper=MathMax(fib.anchor_b,deep_level);
   const bool touched=bar.high>=lower && bar.low<=upper;
   const bool directional=(side==FRANZ_SIDE_BUY ? bar.close>bar.open : bar.close<bar.open);
   return touched && directional;
  }

bool FranzTrendlineRetest(const FranzSide side,
                          const double break_level,
                          const FranzBar &bar,
                          const double tolerance)
  {
   if(!FranzFinitePositive(break_level) || tolerance<0.0) return false;
   const bool touched=bar.high>=break_level-tolerance &&
                      bar.low<=break_level+tolerance;
   const bool directional=(side==FRANZ_SIDE_BUY ? bar.close>bar.open :
                                                     bar.close<bar.open);
   return touched && directional;
  }

bool FranzBarTouchesSwingZone(const FranzSwingZone &zone,
                              const FranzBar &bar,
                              const double tolerance)
  {
   if(!zone.valid || zone.invalidated) return false;
   const double lower=MathMin(zone.proximal,zone.distal)-tolerance;
   const double upper=MathMax(zone.proximal,zone.distal)+tolerance;
   return bar.high>=lower && bar.low<=upper;
  }

bool FranzPassedHalfBeforeEntry(const FranzSide side,
                                const FranzFibonacci &fib,
                                const double close)
  {
   return side==FRANZ_SIDE_BUY ? close>=fib.level_500 : close<=fib.level_500;
  }

double FranzStructuralStop(const FranzSide side,
                           const FranzFibonacci &fib,
                           const double sweep_extreme,
                           const double spread,
                           const double tick_size)
  {
   const double buffer=MathMax(spread,2.0*tick_size);
   if(side==FRANZ_SIDE_SELL)
      return FranzAlignUp(MathMax(sweep_extreme+buffer,fib.level_1130),tick_size);
   return FranzAlignDown(MathMin(sweep_extreme-buffer,fib.level_1130),tick_size);
  }

double FranzTargetBeforeObstacle(const FranzSide side,
                                 const double fibonacci_target,
                                 const double obstacle,
                                 const double entry,
                                 const double tick_size)
  {
   double target=fibonacci_target;
   if(FranzFinitePositive(obstacle))
     {
      if(side==FRANZ_SIDE_BUY && obstacle>entry && obstacle<target)
         target=obstacle-tick_size;
      if(side==FRANZ_SIDE_SELL && obstacle<entry && obstacle>target)
         target=obstacle+tick_size;
     }
   return side==FRANZ_SIDE_BUY ? FranzAlignDown(target,tick_size) :
                                FranzAlignUp(target,tick_size);
  }

double FranzProjectedR(const FranzSide side,
                       const double entry,
                       const double stop_loss,
                       const double target)
  {
   const double risk=MathAbs(entry-stop_loss);
   if(risk<=0.0) return 0.0;
   const double reward=(side==FRANZ_SIDE_BUY ? target-entry : entry-target);
   return reward/risk;
  }

#endif
