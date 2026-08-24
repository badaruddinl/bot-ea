#ifndef GOLDI_FRANZ_PERSISTENCE_MQH
#define GOLDI_FRANZ_PERSISTENCE_MQH

#include "GoldIFranzStrategy.mqh"

enum FranzLoadStatus
  {
   FRANZ_LOAD_MISSING=0,
   FRANZ_LOAD_VALID=1,
   FRANZ_LOAD_INVALID=2
  };

uint FranzStateChecksum(const string value)
  {
   uint hash=2166136261;
   for(int index=0;index<StringLen(value);index++)
     {
      hash^=(uint)StringGetCharacter(value,index);
      hash*=16777619;
     }
   return hash;
  }

class CFranzStateStore
  {
private:
   string m_namespace;

   string SafeNamespace(const string value) const
     {
      string result="";
      for(int index=0;index<StringLen(value);index++)
        {
         const ushort character=StringGetCharacter(value,index);
         const bool allowed=(character>='A' && character<='Z') ||
                            (character>='a' && character<='z') ||
                            (character>='0' && character<='9') ||
                            character=='-' || character=='_';
         result+=allowed ? ShortToString(character) : "_";
        }
      return StringLen(result)>0 ? result : "default";
     }

   string BasePath(void) const
     {
      return "bot-ea\\goldi-franz\\"+m_namespace;
     }

   string SlotPath(const int slot) const
     {
      return BasePath()+"\\state-"+IntegerToString(slot)+".txt";
     }

   string Serialize(const FranzPersistentState &state) const
     {
      const string header=StringFormat(
         "1|%s|%I64u|%d|%d|%d|%d|%d|%.10f|%I64d|%I64d|%I64d|%I64d|%s|"
         "%I64d|%I64d|%d|%d|%d",
         FRANZ_PROFILE_FINGERPRINT,state.generation,(int)state.state,
         (int)state.mode,(int)state.side,state.day_key,state.daily_setups,
         state.daily_r,(long)state.cooldown_until,(long)state.last_m15_close,
         (long)state.last_m5_close,(long)state.last_m1_close,state.setup_id,
         (long)state.setup_created_at,(long)state.setup_expires_at,
         state.watch_m1_bars,state.break_m1_bars,state.fib_m1_bars);
      const string geometry=StringFormat(
         "%.10f|%.10f|%.10f|%.10f|%.10f|%.10f|%d|%d|"
         "%.10f|%.10f|%.10f|%.10f|%.10f|%.10f|%.10f|%.10f|%.10f|%.10f",
         state.liquidity_reference,state.sweep_extreme,state.cluster_high,
         state.cluster_low,state.rejection_high,state.rejection_low,
         state.reentry_closes,state.fibonacci.locked ? 1 : 0,
         state.fibonacci.anchor_a,state.fibonacci.anchor_b,state.fibonacci.range,
         state.fibonacci.level_236,state.fibonacci.level_382,
         state.fibonacci.level_500,state.fibonacci.level_618,
         state.fibonacci.level_1000,state.fibonacci.level_1130,
         state.fibonacci.level_1272);
      const string execution=StringFormat(
         "%.10f|%.10f|%.10f|%.10f|%.10f|%.10f|%I64u|%I64u|%I64u|%I64u|"
         "%d|%d|%d|%I64d|%.10f|%d|%I64u|%s",
         state.planned_entry,state.stop_loss,state.take_profit_1,
         state.take_profit_2,state.initial_risk_price,state.setup_risk_usd,
         state.leg1_ticket,state.leg2_ticket,state.leg1_position_id,
         state.leg2_position_id,state.leg1_closed ? 1 : 0,
         state.leg2_closed ? 1 : 0,state.tp1_hit ? 1 : 0,
         (long)state.position_opened_at,state.setup_realized_pnl,
         state.cleanup_attempts,state.cleanup_started_ms,state.close_reason);
      const string trendlines=StringFormat(
         "%d|%I64d|%.10f|%.12f|%.10f|%d|%d|%I64d|%.10f|%.12f|%.10f|%d|%d|%.10f",
         state.bull_zone.valid ? 1 : 0,(long)state.bull_zone.projected_at,
         state.bull_zone.center_at_projection,state.bull_zone.slope_per_second,
         state.bull_zone.half_width,state.bull_zone.touches,
         state.bear_zone.valid ? 1 : 0,(long)state.bear_zone.projected_at,
         state.bear_zone.center_at_projection,state.bear_zone.slope_per_second,
         state.bear_zone.half_width,state.bear_zone.touches,
         state.initial_trendline_break ? 1 : 0,state.initial_break_level);
      const string swing_zones=StringFormat(
         "%d|%d|%I64d|%.10f|%.10f|%.10f|%.10f|%d|%I64d|%d|"
         "%d|%d|%I64d|%.10f|%.10f|%.10f|%.10f|%d|%I64d|%d",
         state.supply_zone.valid ? 1 : 0,state.supply_zone.supply ? 1 : 0,
         (long)state.supply_zone.created_at,state.supply_zone.proximal,
         state.supply_zone.distal,state.supply_zone.median_range,
         state.supply_zone.departure_strength,state.supply_zone.bounces,
         (long)state.supply_zone.last_touch_at,state.supply_zone.invalidated ? 1 : 0,
         state.demand_zone.valid ? 1 : 0,state.demand_zone.supply ? 1 : 0,
         (long)state.demand_zone.created_at,state.demand_zone.proximal,
         state.demand_zone.distal,state.demand_zone.median_range,
         state.demand_zone.departure_strength,state.demand_zone.bounces,
         (long)state.demand_zone.last_touch_at,state.demand_zone.invalidated ? 1 : 0);
      return header+"|"+geometry+"|"+execution+"|"+trendlines+"|"+swing_zones;
     }

   FranzLoadStatus ReadSlot(const int slot,FranzPersistentState &state) const
     {
      FranzResetPersistentState(state);
      const int handle=FileOpen(SlotPath(slot),FILE_READ|FILE_TXT|FILE_ANSI);
      if(handle==INVALID_HANDLE) return FRANZ_LOAD_MISSING;
      const string payload=FileReadString(handle);
      const string checksum=FileReadString(handle);
      FileClose(handle);
      if(payload=="" || checksum=="" ||
         (uint)StringToInteger(checksum)!=FranzStateChecksum(payload))
         return FRANZ_LOAD_INVALID;
      string fields[];
      const int count=StringSplit(payload,'|',fields);
      if(count!=89 || fields[0]!="1" || fields[1]!=FRANZ_PROFILE_FINGERPRINT)
         return FRANZ_LOAD_INVALID;
      state.generation=(ulong)StringToInteger(fields[2]);
      state.state=(FranzState)StringToInteger(fields[3]);
      state.mode=(FranzMode)StringToInteger(fields[4]);
      state.side=(FranzSide)StringToInteger(fields[5]);
      state.day_key=(int)StringToInteger(fields[6]);
      state.daily_setups=(int)StringToInteger(fields[7]);
      state.daily_r=StringToDouble(fields[8]);
      state.cooldown_until=(datetime)StringToInteger(fields[9]);
      state.last_m15_close=(datetime)StringToInteger(fields[10]);
      state.last_m5_close=(datetime)StringToInteger(fields[11]);
      state.last_m1_close=(datetime)StringToInteger(fields[12]);
      state.setup_id=fields[13];
      state.setup_created_at=(datetime)StringToInteger(fields[14]);
      state.setup_expires_at=(datetime)StringToInteger(fields[15]);
      state.watch_m1_bars=(int)StringToInteger(fields[16]);
      state.break_m1_bars=(int)StringToInteger(fields[17]);
      state.fib_m1_bars=(int)StringToInteger(fields[18]);
      state.liquidity_reference=StringToDouble(fields[19]);
      state.sweep_extreme=StringToDouble(fields[20]);
      state.cluster_high=StringToDouble(fields[21]);
      state.cluster_low=StringToDouble(fields[22]);
      state.rejection_high=StringToDouble(fields[23]);
      state.rejection_low=StringToDouble(fields[24]);
      state.reentry_closes=(int)StringToInteger(fields[25]);
      state.fibonacci.locked=StringToInteger(fields[26])==1;
      state.fibonacci.anchor_a=StringToDouble(fields[27]);
      state.fibonacci.anchor_b=StringToDouble(fields[28]);
      state.fibonacci.range=StringToDouble(fields[29]);
      state.fibonacci.level_236=StringToDouble(fields[30]);
      state.fibonacci.level_382=StringToDouble(fields[31]);
      state.fibonacci.level_500=StringToDouble(fields[32]);
      state.fibonacci.level_618=StringToDouble(fields[33]);
      state.fibonacci.level_1000=StringToDouble(fields[34]);
      state.fibonacci.level_1130=StringToDouble(fields[35]);
      state.fibonacci.level_1272=StringToDouble(fields[36]);
      state.planned_entry=StringToDouble(fields[37]);
      state.stop_loss=StringToDouble(fields[38]);
      state.take_profit_1=StringToDouble(fields[39]);
      state.take_profit_2=StringToDouble(fields[40]);
      state.initial_risk_price=StringToDouble(fields[41]);
      state.setup_risk_usd=StringToDouble(fields[42]);
      state.leg1_ticket=(ulong)StringToInteger(fields[43]);
      state.leg2_ticket=(ulong)StringToInteger(fields[44]);
      state.leg1_position_id=(ulong)StringToInteger(fields[45]);
      state.leg2_position_id=(ulong)StringToInteger(fields[46]);
      state.leg1_closed=StringToInteger(fields[47])==1;
      state.leg2_closed=StringToInteger(fields[48])==1;
      state.tp1_hit=StringToInteger(fields[49])==1;
      state.position_opened_at=(datetime)StringToInteger(fields[50]);
      state.setup_realized_pnl=StringToDouble(fields[51]);
      state.cleanup_attempts=(int)StringToInteger(fields[52]);
      state.cleanup_started_ms=(ulong)StringToInteger(fields[53]);
      state.close_reason=fields[54];
      state.bull_zone.valid=StringToInteger(fields[55])==1;
      state.bull_zone.projected_at=(datetime)StringToInteger(fields[56]);
      state.bull_zone.center_at_projection=StringToDouble(fields[57]);
      state.bull_zone.slope_per_second=StringToDouble(fields[58]);
      state.bull_zone.half_width=StringToDouble(fields[59]);
      state.bull_zone.touches=(int)StringToInteger(fields[60]);
      state.bear_zone.valid=StringToInteger(fields[61])==1;
      state.bear_zone.projected_at=(datetime)StringToInteger(fields[62]);
      state.bear_zone.center_at_projection=StringToDouble(fields[63]);
      state.bear_zone.slope_per_second=StringToDouble(fields[64]);
      state.bear_zone.half_width=StringToDouble(fields[65]);
      state.bear_zone.touches=(int)StringToInteger(fields[66]);
      state.initial_trendline_break=StringToInteger(fields[67])==1;
      state.initial_break_level=StringToDouble(fields[68]);
      state.supply_zone.valid=StringToInteger(fields[69])==1;
      state.supply_zone.supply=StringToInteger(fields[70])==1;
      state.supply_zone.created_at=(datetime)StringToInteger(fields[71]);
      state.supply_zone.proximal=StringToDouble(fields[72]);
      state.supply_zone.distal=StringToDouble(fields[73]);
      state.supply_zone.median_range=StringToDouble(fields[74]);
      state.supply_zone.departure_strength=StringToDouble(fields[75]);
      state.supply_zone.bounces=(int)StringToInteger(fields[76]);
      state.supply_zone.last_touch_at=(datetime)StringToInteger(fields[77]);
      state.supply_zone.invalidated=StringToInteger(fields[78])==1;
      state.demand_zone.valid=StringToInteger(fields[79])==1;
      state.demand_zone.supply=StringToInteger(fields[80])==1;
      state.demand_zone.created_at=(datetime)StringToInteger(fields[81]);
      state.demand_zone.proximal=StringToDouble(fields[82]);
      state.demand_zone.distal=StringToDouble(fields[83]);
      state.demand_zone.median_range=StringToDouble(fields[84]);
      state.demand_zone.departure_strength=StringToDouble(fields[85]);
      state.demand_zone.bounces=(int)StringToInteger(fields[86]);
      state.demand_zone.last_touch_at=(datetime)StringToInteger(fields[87]);
      state.demand_zone.invalidated=StringToInteger(fields[88])==1;
      if(state.generation==0 || state.state<FRANZ_STATE_COLD ||
         state.state>FRANZ_STATE_DAILY_LOCKED ||
         state.mode<FRANZ_MODE_NONE || state.mode>FRANZ_MODE_SNIPER_TREND ||
         state.side<FRANZ_SIDE_SELL || state.side>FRANZ_SIDE_BUY)
         return FRANZ_LOAD_INVALID;
      return FRANZ_LOAD_VALID;
     }

public:
   CFranzStateStore(void) { m_namespace="default"; }

   void Configure(const string run_id)
     {
      m_namespace=SafeNamespace(run_id);
     }

   FranzLoadStatus Load(FranzPersistentState &state) const
     {
      FranzPersistentState first,second;
      const FranzLoadStatus first_status=ReadSlot(0,first);
      const FranzLoadStatus second_status=ReadSlot(1,second);
      if(first_status==FRANZ_LOAD_VALID && second_status==FRANZ_LOAD_VALID)
        {
         state=(first.generation>=second.generation ? first : second);
         return FRANZ_LOAD_VALID;
        }
      if(first_status==FRANZ_LOAD_VALID) { state=first; return FRANZ_LOAD_VALID; }
      if(second_status==FRANZ_LOAD_VALID) { state=second; return FRANZ_LOAD_VALID; }
      FranzResetPersistentState(state);
      return (first_status==FRANZ_LOAD_MISSING && second_status==FRANZ_LOAD_MISSING ?
              FRANZ_LOAD_MISSING : FRANZ_LOAD_INVALID);
     }

   bool Save(FranzPersistentState &state) const
     {
      if(!FolderCreate(BasePath())) return false;
      FranzPersistentState current;
      const FranzLoadStatus loaded=Load(current);
      state.generation=(loaded==FRANZ_LOAD_VALID ? current.generation+1 : 1);
      const string payload=Serialize(state);
      const int slot=(int)(state.generation%2);
      const int handle=FileOpen(SlotPath(slot),FILE_WRITE|FILE_TXT|FILE_ANSI);
      if(handle==INVALID_HANDLE) return false;
      const string checksum=IntegerToString((long)FranzStateChecksum(payload));
      const uint payload_written=FileWriteString(handle,payload+"\r\n");
      const uint checksum_written=FileWriteString(handle,checksum+"\r\n");
      FileFlush(handle);
      FileClose(handle);
      if(payload_written==0 || checksum_written==0) return false;
      FranzPersistentState verified;
      return ReadSlot(slot,verified)==FRANZ_LOAD_VALID &&
             verified.generation==state.generation;
     }

   void DeleteTestState(void) const
     {
      FileDelete(SlotPath(0));
      FileDelete(SlotPath(1));
     }
  };

#endif
