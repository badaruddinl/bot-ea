#ifndef GOLD_ENGINE_REVISED_ZONES_MQH
#define GOLD_ENGINE_REVISED_ZONES_MQH

#include "GoldEngineRevisedContext.mqh"

struct RevisedObstacleCandidate
  {
   double price;
   string kind;
  };

bool RevisedZoneAccepted(const EngineBar &bars[],
                         const int start,
                         const double boundary,
                         const bool above,
                         const int required_closes)
  {
   int consecutive=0;
   for(int index=start;index<ArraySize(bars);index++)
     {
      const bool accepted=(above ?
                           bars[index].close>boundary :
                           bars[index].close<boundary);
      consecutive=(accepted ? consecutive+1 : 0);
      if(consecutive>=required_closes)
         return true;
     }
   return false;
  }

bool RevisedStrongZoneBreakAccepted(const EngineBar &bars[],
                                    const int start,
                                    const double distal,
                                    const double tolerance,
                                    const bool supply)
  {
   for(int index=start;index<ArraySize(bars);index++)
     {
      const EngineBar bar=bars[index];
      const double range=bar.high-bar.low;
      if(range<=0.0)
         continue;
      const double body=MathAbs(bar.close-bar.open);
      if(supply &&
         bar.close>distal+tolerance &&
         body/range>=0.55 &&
         (bar.close-bar.low)/range>=0.75)
         return true;
      if(!supply &&
         bar.close<distal-tolerance &&
         body/range>=0.55 &&
         (bar.high-bar.close)/range>=0.75)
         return true;
     }
   return false;
  }

int RevisedConfirmedZones(const EngineBar &bars[],
                          const double atr,
                          const bool supply,
                          const RevisedEngineConfig &config,
                          RevisedZone &zones[])
  {
   ArrayResize(zones,0);
   const int count=ArraySize(bars);
   const int confirmation=config.supply_confirmation_bars;
   if(count<=confirmation || atr<=0.0)
      return 0;
   int zone_count=0;
   const double tolerance=config.spread_floor;
   for(int index=0;index<count-confirmation;index++)
     {
      const EngineBar origin=bars[index];
      const double origin_range=origin.high-origin.low;
      if(origin_range<=0.0)
         continue;
      const double body_ratio=MathAbs(origin.close-origin.open)/origin_range;
      const int previous_start=MathMax(0,index-2);
      bool swing_origin=true;
      for(int previous=previous_start;previous<index;previous++)
        {
         if((supply && origin.high<bars[previous].high) ||
            (!supply && origin.low>bars[previous].low))
           {
            swing_origin=false;
            break;
           }
        }

      double confirmation_extreme=(supply ?
                                   bars[index+1].low :
                                   bars[index+1].high);
      double confirmation_close=(supply ?
                                 bars[index+1].close :
                                 bars[index+1].close);
      int directional_count=0;
      for(int offset=1;offset<=confirmation;offset++)
        {
         const EngineBar confirming=bars[index+offset];
         if(supply)
           {
            confirmation_extreme=MathMin(confirmation_extreme,confirming.low);
            confirmation_close=MathMin(confirmation_close,confirming.close);
            if(confirming.close<confirming.open)
               directional_count++;
           }
         else
           {
            confirmation_extreme=MathMax(confirmation_extreme,confirming.high);
            confirmation_close=MathMax(confirmation_close,confirming.close);
            if(confirming.close>confirming.open)
               directional_count++;
           }
        }

      const bool base_ok=(supply ?
                          origin.close>=origin.open || body_ratio<=0.55 :
                          origin.close<=origin.open || body_ratio<=0.55);
      const double displacement=(supply ?
                                 origin.high-confirmation_extreme :
                                 confirmation_extreme-origin.low);
      const bool structure_broken=(supply ?
                                   confirmation_close<origin.low :
                                   confirmation_close>origin.high);
      const double proximal=(supply ?
                             MathMin(origin.open,origin.close) :
                             MathMax(origin.open,origin.close));
      const double distal=(supply ? origin.high : origin.low);
      const int later_start=index+confirmation+1;
      const bool accepted=
         RevisedZoneAccepted(
            bars,later_start,
            supply ? distal+tolerance : distal-tolerance,
            supply,config.zone_acceptance_closes) ||
         RevisedStrongZoneBreakAccepted(
            bars,later_start,distal,tolerance,supply);

      if(base_ok &&
         swing_origin &&
         structure_broken &&
         directional_count>=2 &&
         displacement>=atr*config.supply_displacement_atr &&
         !accepted)
        {
         ArrayResize(zones,zone_count+1);
         zones[zone_count].proximal=proximal;
         zones[zone_count].distal=distal;
         zones[zone_count].origin_time=origin.open_time;
         zones[zone_count].displacement_atr=displacement/atr;
         zones[zone_count].timeframe="";
         zones[zone_count].kind="";
         zones[zone_count].obstacle=0.0;
         zones[zone_count].distance=0.0;
         zones[zone_count].inside=false;
         zone_count++;
        }
     }
   return zone_count;
  }

void RevisedConsiderNearestSupply(const EngineBar &bars[],
                                  const string timeframe,
                                  const double entry,
                                  const bool blocking_only,
                                  const RevisedEngineConfig &config,
                                  bool &found,
                                  RevisedZone &selected)
  {
   RevisedZone zones[];
   const double atr=RevisedAtr(bars,config.atr_period);
   RevisedConfirmedZones(bars,atr,true,config,zones);
   for(int index=0;index<ArraySize(zones);index++)
     {
      RevisedZone zone=zones[index];
      if(entry>zone.distal)
         continue;
      const bool inside=zone.proximal<=entry && entry<=zone.distal;
      if(blocking_only && inside && timeframe=="H1")
         continue;
      zone.timeframe=timeframe;
      zone.inside=inside;
      zone.kind=(inside ?
                 timeframe+"_SUPPLY_INSIDE" :
                 timeframe+"_SUPPLY_PROXIMAL");
      zone.obstacle=(inside ? entry : zone.proximal);
      zone.distance=MathAbs(zone.obstacle-entry);
      if(!found || zone.distance<selected.distance)
        {
         selected=zone;
         found=true;
        }
     }
  }

bool RevisedNearestSupplyZone(const CRevisedSnapshot &snapshot,
                              const double entry,
                              const bool blocking_only,
                              const RevisedEngineConfig &config,
                              RevisedZone &selected)
  {
   bool found=false;
   RevisedConsiderNearestSupply(
      snapshot.m5_bars,"M5",entry,blocking_only,config,found,selected);
   RevisedConsiderNearestSupply(
      snapshot.h1_bars,"H1",entry,blocking_only,config,found,selected);
   return found;
  }

void RevisedConsiderNearestDemand(const EngineBar &bars[],
                                  const string timeframe,
                                  const double entry,
                                  const RevisedEngineConfig &config,
                                  bool &found,
                                  RevisedZone &selected)
  {
   RevisedZone zones[];
   const double atr=RevisedAtr(bars,config.atr_period);
   RevisedConfirmedZones(bars,atr,false,config,zones);
   for(int index=0;index<ArraySize(zones);index++)
     {
      RevisedZone zone=zones[index];
      if(entry<zone.distal)
         continue;
      const bool inside=zone.distal<=entry && entry<=zone.proximal;
      zone.timeframe=timeframe;
      zone.inside=inside;
      zone.kind=(inside ?
                 timeframe+"_DEMAND_INSIDE" :
                 timeframe+"_DEMAND_PROXIMAL");
      zone.obstacle=(inside ? entry : zone.proximal);
      zone.distance=(inside ? 0.0 : entry-zone.proximal);
      if(!found || zone.distance<selected.distance)
        {
         selected=zone;
         found=true;
        }
     }
  }

bool RevisedNearestDemandZone(const CRevisedSnapshot &snapshot,
                              const double entry,
                              const RevisedEngineConfig &config,
                              RevisedZone &selected)
  {
   bool found=false;
   RevisedConsiderNearestDemand(
      snapshot.m5_bars,"M5",entry,config,found,selected);
   RevisedConsiderNearestDemand(
      snapshot.h1_bars,"H1",entry,config,found,selected);
   return found;
  }

void RevisedSliceBars(const EngineBar &source[],
                      const int start,
                      const int end,
                      EngineBar &result[])
  {
   const int safe_start=MathMax(0,start);
   const int safe_end=MathMin(ArraySize(source),MathMax(safe_start,end));
   ArrayResize(result,safe_end-safe_start);
   for(int index=safe_start;index<safe_end;index++)
      result[index-safe_start]=source[index];
  }

void RevisedMarketRegime(const CRevisedSnapshot &snapshot,
                         const RevisedEngineConfig &config,
                         RevisedMarketRegimeStats &stats)
  {
   const int atr_window=config.atr_period+1;
   stats.m5_atr=RevisedAtr(snapshot.m5_bars,config.atr_period);
   EngineBar prior_m5[];
   const int m5_count=ArraySize(snapshot.m5_bars);
   RevisedSliceBars(
      snapshot.m5_bars,m5_count-atr_window*2,m5_count-atr_window,prior_m5);
   const double prior_atr=RevisedAtr(prior_m5,config.atr_period);
   stats.m5_atr_expansion=(prior_atr>0.0 ? stats.m5_atr/prior_atr : 1.0);
   stats.h1_atr=RevisedAtr(snapshot.h1_bars,config.atr_period);

   const int h1_count=ArraySize(snapshot.h1_bars);
   const int trend_start=MathMax(0,h1_count-24);
   if(h1_count-trend_start>=2)
     {
      const double trend_move=
         snapshot.h1_bars[h1_count-1].close-
         snapshot.h1_bars[trend_start].close;
      double travelled=0.0;
      for(int index=trend_start+1;index<h1_count;index++)
         travelled+=MathAbs(
            snapshot.h1_bars[index].close-
            snapshot.h1_bars[index-1].close);
      stats.h1_trend_atr=(stats.h1_atr>0.0 ?
                          trend_move/stats.h1_atr : 0.0);
      stats.h1_efficiency=(travelled>0.0 ?
                           MathAbs(trend_move)/travelled : 0.0);
     }
   else
     {
      stats.h1_trend_atr=0.0;
      stats.h1_efficiency=0.0;
     }

   const int sma_start=MathMax(0,h1_count-20);
   double sma_total=0.0;
   for(int index=sma_start;index<h1_count;index++)
      sma_total+=snapshot.h1_bars[index].close;
   const double h1_sma=(h1_count>sma_start ?
                        sma_total/(h1_count-sma_start) : 0.0);
   const int m1_count=ArraySize(snapshot.m1_bars);
   const double current_price=(m1_count>0 ?
                               snapshot.m1_bars[m1_count-1].close : 0.0);
   stats.above_h1_sma20=(h1_sma>0.0 && current_price>=h1_sma);
  }

void RevisedAddObstacleCandidate(RevisedObstacleCandidate &candidates[],
                                 const double price,
                                 const string kind)
  {
   const int count=ArraySize(candidates);
   ArrayResize(candidates,count+1);
   candidates[count].price=price;
   candidates[count].kind=kind;
  }

void RevisedAddSwingObstacleCandidates(const EngineBar &bars[],
                                       const string kind,
                                       const EngineSide side,
                                       const double entry,
                                       const int span,
                                       RevisedObstacleCandidate &candidates[])
  {
   double pivots[];
   if(side==ENGINE_SIDE_BUY)
      RevisedSwingHighs(bars,span,pivots);
   else
      RevisedSwingLows(bars,span,pivots);
   for(int index=0;index<ArraySize(pivots);index++)
     {
      const double price=pivots[index];
      if((side==ENGINE_SIDE_BUY && price>entry) ||
         (side==ENGINE_SIDE_SELL && price<entry))
         RevisedAddObstacleCandidate(candidates,price,kind);
     }
  }

bool RevisedFirstObstacle(const CRevisedSnapshot &snapshot,
                          const RevisedEngineConfig &config,
                          const double entry,
                          const double atr_m1,
                          double &obstacle,
                          string &kind)
  {
   RevisedObstacleCandidate candidates[];
   if(snapshot.side==ENGINE_SIDE_BUY)
     {
      RevisedZone supply;
      if(RevisedNearestSupplyZone(snapshot,entry,true,config,supply))
         RevisedAddObstacleCandidate(candidates,supply.obstacle,supply.kind);
     }

   for(int index=0;index<3;index++)
     {
      const double step=config.psychological_steps[index];
      double price=0.0;
      if(snapshot.side==ENGINE_SIDE_BUY)
        {
         price=MathCeil((entry+1.0e-12)/step)*step;
         if(price<=entry)
            price+=step;
        }
      else
        {
         price=MathFloor((entry-1.0e-12)/step)*step;
         if(price>=entry)
            price-=step;
        }
      RevisedAddObstacleCandidate(
         candidates,MathRound(price*1.0e8)/1.0e8,
         "PSYCH_"+DoubleToString(step,0));
     }

   RevisedAddSwingObstacleCandidates(
      snapshot.m5_bars,"M5_SWING",snapshot.side,entry,config.swing_span,candidates);
   RevisedAddSwingObstacleCandidates(
      snapshot.h1_bars,"H1_SWING",snapshot.side,entry,config.swing_span,candidates);
   RevisedAddSwingObstacleCandidates(
      snapshot.d1_bars,"D1_SWING",snapshot.side,entry,config.swing_span,candidates);

   const int m1_count=ArraySize(snapshot.m1_bars);
   int pre_trigger_count=m1_count;
   if(snapshot.m5_trigger_time>0)
     {
      pre_trigger_count=0;
      while(pre_trigger_count<m1_count &&
            snapshot.m1_bars[pre_trigger_count].open_time<snapshot.m5_trigger_time)
         pre_trigger_count++;
     }
   EngineBar pre_trigger_m1[];
   RevisedSliceBars(snapshot.m1_bars,0,pre_trigger_count,pre_trigger_m1);
   double m1_pivots[];
   if(snapshot.side==ENGINE_SIDE_BUY)
      RevisedSwingHighs(pre_trigger_m1,config.swing_span,m1_pivots);
   else
      RevisedSwingLows(pre_trigger_m1,config.swing_span,m1_pivots);
   double directional_m1[];
   int directional_count=0;
   for(int index=0;index<ArraySize(m1_pivots);index++)
     {
      const double price=m1_pivots[index];
      if((snapshot.side==ENGINE_SIDE_BUY && price>entry) ||
         (snapshot.side==ENGINE_SIDE_SELL && price<entry))
        {
         ArrayResize(directional_m1,directional_count+1);
         directional_m1[directional_count]=price;
         directional_count++;
        }
     }
   const double tolerance=MathMax(config.spread_floor*2.0,atr_m1*0.20);
   for(int index=0;index<directional_count;index++)
     {
      const double price=directional_m1[index];
      bool repeated=false;
      for(int other=0;other<directional_count;other++)
        {
         if(other!=index && MathAbs(price-directional_m1[other])<=tolerance)
           {
            repeated=true;
            break;
           }
        }
      bool confluent=false;
      for(int candidate=0;candidate<ArraySize(candidates);candidate++)
        {
         if(MathAbs(price-candidates[candidate].price)<=tolerance)
           {
            confluent=true;
            break;
           }
        }
      if(repeated || confluent)
         RevisedAddObstacleCandidate(candidates,price,"M1_SWING_CLUSTER");
     }

   const int candidate_count=ArraySize(candidates);
   if(candidate_count==0)
      return false;
   int selected=0;
   if(snapshot.side==ENGINE_SIDE_BUY)
     {
      for(int index=1;index<candidate_count;index++)
        {
         const double distance=MathAbs(candidates[index].price-entry);
         const double selected_distance=MathAbs(candidates[selected].price-entry);
         const bool supply=StringFind(candidates[index].kind,"SUPPLY")>=0;
         const bool selected_supply=StringFind(candidates[selected].kind,"SUPPLY")>=0;
         if(distance<selected_distance ||
            (distance==selected_distance && supply && !selected_supply))
            selected=index;
        }
     }
   else
     {
      for(int index=1;index<candidate_count;index++)
        {
         if(candidates[index].price>candidates[selected].price)
            selected=index;
        }
     }
   obstacle=candidates[selected].price;
   kind=candidates[selected].kind;
   return true;
  }

#endif
