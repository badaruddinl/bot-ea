#ifndef GOLD_ENGINE_BEAR_PERSISTENCE_MQH
#define GOLD_ENGINE_BEAR_PERSISTENCE_MQH

#include "GoldEngineBearIncremental.mqh"

enum BearStateLoadStatus
  {
   BEAR_STATE_MISSING=0,
   BEAR_STATE_LOADED=1,
   BEAR_STATE_STALE=2,
   BEAR_STATE_INVALID=3
  };

class CBearStateStore
  {
private:
   string m_namespace;

   string SlotPath(const string profile_id,const bool first) const
     {
      const string suffix=(m_namespace=="" ? "" : "-"+m_namespace);
      return "bot-ea-state-"+profile_id+"-bear"+suffix+"-"+
             (first ? "a" : "b")+".bin";
     }

   bool WriteInt(const int handle,const int value) const
     {
      return FileWriteInteger(handle,value,INT_VALUE)>0;
     }

   bool WriteLong(const int handle,const long value) const
     {
      return FileWriteLong(handle,value)>0;
     }

   bool WriteDouble(const int handle,const double value) const
     {
      return FileWriteDouble(handle,value)>0;
     }

   bool WriteBool(const int handle,const bool value) const
     {
      return WriteInt(handle,value ? 1 : 0);
     }

   bool WriteString(const int handle,const string value) const
     {
      const int length=StringLen(value);
      if(!WriteInt(handle,length))
         return false;
      return length==0 || FileWriteString(handle,value,length)>0;
     }

   bool ReadInt(const int handle,int &value) const
     {
      if(FileTell(handle)+4>FileSize(handle))
         return false;
      value=FileReadInteger(handle,INT_VALUE);
      return true;
     }

   bool ReadLong(const int handle,long &value) const
     {
      if(FileTell(handle)+8>FileSize(handle))
         return false;
      value=FileReadLong(handle);
      return true;
     }

   bool ReadDouble(const int handle,double &value) const
     {
      if(FileTell(handle)+8>FileSize(handle))
         return false;
      value=FileReadDouble(handle);
      return MathIsValidNumber(value);
     }

   bool ReadBool(const int handle,bool &value) const
     {
      int raw=0;
      if(!ReadInt(handle,raw) || (raw!=0 && raw!=1))
         return false;
      value=raw==1;
      return true;
     }

   bool ReadString(const int handle,string &value,const int maximum=4096) const
     {
      int length=0;
      if(!ReadInt(handle,length) || length<0 || length>maximum)
         return false;
      if(length==0)
        {
         value="";
         return true;
        }
      value=FileReadString(handle,length);
      return StringLen(value)==length;
     }

   bool WriteBar(const int handle,const EngineBar &bar) const
     {
      return WriteInt(handle,(int)bar.timeframe) &&
             WriteLong(handle,(long)bar.open_time) &&
             WriteLong(handle,(long)bar.close_time) &&
             WriteDouble(handle,bar.open) &&
             WriteDouble(handle,bar.high) &&
             WriteDouble(handle,bar.low) &&
             WriteDouble(handle,bar.close) &&
             WriteLong(handle,bar.tick_volume) &&
             WriteInt(handle,bar.spread_points);
     }

   bool ReadBar(const int handle,EngineBar &bar) const
     {
      int timeframe=0;
      long open_time=0;
      long close_time=0;
      long volume=0;
      if(!ReadInt(handle,timeframe) ||
         !ReadLong(handle,open_time) ||
         !ReadLong(handle,close_time) ||
         !ReadDouble(handle,bar.open) ||
         !ReadDouble(handle,bar.high) ||
         !ReadDouble(handle,bar.low) ||
         !ReadDouble(handle,bar.close) ||
         !ReadLong(handle,volume) ||
         !ReadInt(handle,bar.spread_points))
         return false;
      bar.timeframe=(ENUM_TIMEFRAMES)timeframe;
      bar.open_time=(datetime)open_time;
      bar.close_time=(datetime)close_time;
      bar.tick_volume=volume;
      return bar.low<=MathMin(bar.open,bar.close) &&
             bar.high>=MathMax(bar.open,bar.close) &&
             bar.high>=bar.low && bar.tick_volume>=0 &&
             bar.spread_points>=0;
     }

   bool WriteBars(const int handle,const EngineBar &bars[]) const
     {
      if(!WriteInt(handle,ArraySize(bars)))
         return false;
      for(int index=0;index<ArraySize(bars);index++)
         if(!WriteBar(handle,bars[index]))
            return false;
      return true;
     }

   bool ReadBars(const int handle,EngineBar &bars[],const int maximum) const
     {
      int count=0;
      if(!ReadInt(handle,count) || count<0 || count>maximum)
         return false;
      ArrayResize(bars,count);
      for(int index=0;index<count;index++)
         if(!ReadBar(handle,bars[index]))
            return false;
      return true;
     }

   bool WriteSetup(const int handle,const BearSetup &value) const
     {
      return WriteLong(handle,(long)value.time) &&
             WriteString(handle,value.symbol) &&
             WriteString(handle,value.reason) &&
             WriteInt(handle,value.score) &&
             WriteDouble(handle,value.resistance) &&
             WriteString(handle,value.resistance_kind) &&
             WriteDouble(handle,value.support) &&
             WriteDouble(handle,value.entry) &&
             WriteDouble(handle,value.stop) &&
             WriteDouble(handle,value.take_profit) &&
             WriteDouble(handle,value.take_profit_2) &&
             WriteDouble(handle,value.reward_risk) &&
             WriteDouble(handle,value.atr) &&
             WriteDouble(handle,value.regime_slope_atr) &&
             WriteDouble(handle,value.regime_drop_atr) &&
             WriteDouble(handle,value.chase_distance_atr) &&
             WriteInt(handle,value.confluence_votes) &&
             WriteDouble(handle,value.fibonacci_zone_low) &&
             WriteDouble(handle,value.fibonacci_zone_high) &&
             WriteBool(handle,value.fibonacci_retest) &&
             WriteDouble(handle,value.rsi_value) &&
             WriteBool(handle,value.rsi_turn_down) &&
             WriteDouble(handle,value.stochastic_k) &&
             WriteDouble(handle,value.stochastic_d) &&
             WriteBool(handle,value.stochastic_turn_down) &&
             WriteDouble(handle,value.supply_proximal) &&
             WriteDouble(handle,value.supply_distal) &&
             WriteBool(handle,value.supply_retest) &&
             WriteBool(handle,value.momentum_restart) &&
             WriteBool(handle,value.exhausted);
     }

   bool ReadSetup(const int handle,BearSetup &value) const
     {
      long time=0;
      if(!ReadLong(handle,time) ||
         !ReadString(handle,value.symbol,64) ||
         !ReadString(handle,value.reason,512) ||
         !ReadInt(handle,value.score) ||
         !ReadDouble(handle,value.resistance) ||
         !ReadString(handle,value.resistance_kind,128) ||
         !ReadDouble(handle,value.support) ||
         !ReadDouble(handle,value.entry) ||
         !ReadDouble(handle,value.stop) ||
         !ReadDouble(handle,value.take_profit) ||
         !ReadDouble(handle,value.take_profit_2) ||
         !ReadDouble(handle,value.reward_risk) ||
         !ReadDouble(handle,value.atr) ||
         !ReadDouble(handle,value.regime_slope_atr) ||
         !ReadDouble(handle,value.regime_drop_atr) ||
         !ReadDouble(handle,value.chase_distance_atr) ||
         !ReadInt(handle,value.confluence_votes) ||
         !ReadDouble(handle,value.fibonacci_zone_low) ||
         !ReadDouble(handle,value.fibonacci_zone_high) ||
         !ReadBool(handle,value.fibonacci_retest) ||
         !ReadDouble(handle,value.rsi_value) ||
         !ReadBool(handle,value.rsi_turn_down) ||
         !ReadDouble(handle,value.stochastic_k) ||
         !ReadDouble(handle,value.stochastic_d) ||
         !ReadBool(handle,value.stochastic_turn_down) ||
         !ReadDouble(handle,value.supply_proximal) ||
         !ReadDouble(handle,value.supply_distal) ||
         !ReadBool(handle,value.supply_retest) ||
         !ReadBool(handle,value.momentum_restart) ||
         !ReadBool(handle,value.exhausted))
         return false;
      value.time=(datetime)time;
      return value.score>=0 && value.score<=100 &&
             value.confluence_votes>=0 && value.confluence_votes<=5;
     }

   bool WriteArm(const int handle,const BearM5Result &value) const
     {
      return WriteInt(handle,(int)value.state) &&
             WriteString(handle,value.reason) &&
             WriteLong(handle,(long)value.armed_at) &&
             WriteDouble(handle,value.atr) &&
             WriteInt(handle,value.touches) &&
             WriteInt(handle,value.rejections) &&
             WriteDouble(handle,value.recent_high);
     }

   bool ReadArm(const int handle,BearM5Result &value) const
     {
      int state=0;
      long armed_at=0;
      if(!ReadInt(handle,state) || state<BEAR_M5_EXPIRED ||
         state>BEAR_M5_CANCELLED ||
         !ReadString(handle,value.reason,256) ||
         !ReadLong(handle,armed_at) ||
         !ReadDouble(handle,value.atr) ||
         !ReadInt(handle,value.touches) ||
         !ReadInt(handle,value.rejections) ||
         !ReadDouble(handle,value.recent_high))
         return false;
      value.state=(BearM5State)state;
      value.armed_at=(datetime)armed_at;
      return value.touches>=0 && value.rejections>=0;
     }

   bool WriteSignal(const int handle,const BearEntryPlan &value) const
     {
      return WriteBool(handle,value.valid) &&
             WriteLong(handle,(long)value.armed_at) &&
             WriteLong(handle,(long)value.opened_at) &&
             WriteDouble(handle,value.entry) &&
             WriteDouble(handle,value.stop) &&
             WriteDouble(handle,value.target) &&
             WriteDouble(handle,value.structural_stop) &&
             WriteDouble(handle,value.structural_target) &&
             WriteInt(handle,value.m5_touches) &&
             WriteInt(handle,value.m5_rejections) &&
             WriteInt(handle,value.m1_touches);
     }

   bool ReadSignal(const int handle,BearEntryPlan &value) const
     {
      long armed_at=0;
      long opened_at=0;
      if(!ReadBool(handle,value.valid) ||
         !ReadLong(handle,armed_at) ||
         !ReadLong(handle,opened_at) ||
         !ReadDouble(handle,value.entry) ||
         !ReadDouble(handle,value.stop) ||
         !ReadDouble(handle,value.target) ||
         !ReadDouble(handle,value.structural_stop) ||
         !ReadDouble(handle,value.structural_target) ||
         !ReadInt(handle,value.m5_touches) ||
         !ReadInt(handle,value.m5_rejections) ||
         !ReadInt(handle,value.m1_touches))
         return false;
      value.armed_at=(datetime)armed_at;
      value.opened_at=(datetime)opened_at;
      return value.m5_touches>=0 && value.m5_rejections>=0 &&
             value.m1_touches>=0;
     }

   bool WriteSnapshot(const int handle,const CBearIncrementalSnapshot &value) const
     {
      return WriteString(handle,value.profile_id) &&
             WriteString(handle,value.symbol) &&
             WriteInt(handle,value.utc_offset_minutes) &&
             WriteInt(handle,(int)value.phase) &&
             WriteLong(handle,value.sequence) &&
             WriteLong(handle,(long)value.as_of) &&
             WriteString(handle,value.setup_id) &&
             WriteLong(handle,(long)value.setup_time) &&
             WriteLong(handle,(long)value.last_setup_time) &&
             WriteBool(handle,value.has_setup) &&
             WriteSetup(handle,value.setup) &&
             WriteBool(handle,value.has_arm) &&
             WriteArm(handle,value.arm) &&
             WriteBool(handle,value.has_signal) &&
             WriteSignal(handle,value.signal) &&
             WriteInt(handle,value.touches) &&
             WriteInt(handle,value.rejections) &&
             WriteBool(handle,value.acceptance) &&
             WriteLong(handle,(long)value.last_m1) &&
             WriteLong(handle,(long)value.last_m5) &&
             WriteLong(handle,(long)value.last_m15) &&
             WriteLong(handle,(long)value.last_h1) &&
             WriteBars(handle,value.m1_bars) &&
             WriteBars(handle,value.m5_bars) &&
             WriteBars(handle,value.m15_bars) &&
             WriteBars(handle,value.h1_bars);
     }

   bool ReadSnapshot(const int handle,CBearIncrementalSnapshot &value) const
     {
      int phase=0;
      long sequence=0;
      long as_of=0,setup_time=0,last_setup_time=0;
      long last_m1=0,last_m5=0,last_m15=0,last_h1=0;
      if(!ReadString(handle,value.profile_id,16) ||
         !ReadString(handle,value.symbol,64) ||
         !ReadInt(handle,value.utc_offset_minutes) ||
         !ReadInt(handle,phase) || phase<BEAR_PHASE_IDLE ||
         phase>BEAR_PHASE_CANCELLED ||
         !ReadLong(handle,sequence) || sequence<0 ||
         !ReadLong(handle,as_of) || as_of<=0 ||
         !ReadString(handle,value.setup_id,512) ||
         !ReadLong(handle,setup_time) ||
         !ReadLong(handle,last_setup_time) ||
         !ReadBool(handle,value.has_setup) ||
         !ReadSetup(handle,value.setup) ||
         !ReadBool(handle,value.has_arm) ||
         !ReadArm(handle,value.arm) ||
         !ReadBool(handle,value.has_signal) ||
         !ReadSignal(handle,value.signal) ||
         !ReadInt(handle,value.touches) ||
         !ReadInt(handle,value.rejections) ||
         !ReadBool(handle,value.acceptance) ||
         !ReadLong(handle,last_m1) ||
         !ReadLong(handle,last_m5) ||
         !ReadLong(handle,last_m15) ||
         !ReadLong(handle,last_h1) ||
         !ReadBars(handle,value.m1_bars,45) ||
         !ReadBars(handle,value.m5_bars,40) ||
         !ReadBars(handle,value.m15_bars,128) ||
         !ReadBars(handle,value.h1_bars,23))
         return false;
      value.phase=(BearIncrementalPhase)phase;
      value.sequence=sequence;
      value.as_of=(datetime)as_of;
      value.setup_time=(datetime)setup_time;
      value.last_setup_time=(datetime)last_setup_time;
      value.last_m1=(datetime)last_m1;
      value.last_m5=(datetime)last_m5;
      value.last_m15=(datetime)last_m15;
      value.last_h1=(datetime)last_h1;
      return value.touches>=0 && value.rejections>=0 &&
             FileTell(handle)==FileSize(handle);
     }

   bool SaveSlot(const string path,
                 const string fingerprint,
                 const CBearIncrementalSnapshot &snapshot) const
     {
      ResetLastError();
      const int handle=FileOpen(path,FILE_WRITE|FILE_BIN);
      if(handle==INVALID_HANDLE)
         return false;
      const bool written=WriteString(handle,"G13_BEAR_STATE") &&
                         WriteInt(handle,1) &&
                         WriteString(handle,fingerprint) &&
                         WriteSnapshot(handle,snapshot);
      FileFlush(handle);
      const bool healthy=written && FileTell(handle)==FileSize(handle);
      FileClose(handle);
      return healthy;
     }

   bool LoadSlot(const string path,
                 const string expected_fingerprint,
                 CBearIncrementalSnapshot &snapshot) const
     {
      const int handle=FileOpen(path,FILE_READ|FILE_BIN);
      if(handle==INVALID_HANDLE)
         return false;
      string magic="";
      string fingerprint="";
      int schema=0;
      const bool loaded=ReadString(handle,magic,32) &&
                        magic=="G13_BEAR_STATE" &&
                        ReadInt(handle,schema) && schema==1 &&
                        ReadString(handle,fingerprint,64) &&
                        fingerprint==expected_fingerprint &&
                        ReadSnapshot(handle,snapshot);
      FileClose(handle);
      return loaded;
     }

public:
   CBearStateStore(void)
     {
      m_namespace="";
     }

   bool SetNamespace(const string value)
     {
      for(int index=0;index<StringLen(value);index++)
        {
         const ushort character=StringGetCharacter(value,index);
         const bool valid=(character>='a' && character<='z') ||
                          (character>='0' && character<='9') ||
                          character=='-';
         if(!valid)
            return false;
        }
      m_namespace=value;
      return true;
     }

   bool Save(const string profile_id,
             const string fingerprint,
             const CBearIncrementalMachine &machine) const
     {
      if(profile_id=="" || StringLen(fingerprint)!=64)
         return false;
      CBearIncrementalSnapshot snapshot;
      machine.Snapshot(snapshot);
      const bool first=(snapshot.sequence%2)==0;
      return SaveSlot(SlotPath(profile_id,first),fingerprint,snapshot);
     }

   BearStateLoadStatus Load(const string profile_id,
                            const string symbol,
                            const string fingerprint,
                            const datetime current_time,
                            const int maximum_age_seconds,
                            CBearIncrementalMachine &machine) const
     {
      const string first_path=SlotPath(profile_id,true);
      const string second_path=SlotPath(profile_id,false);
      const bool first_exists=FileIsExist(first_path);
      const bool second_exists=FileIsExist(second_path);
      if(!first_exists && !second_exists)
         return BEAR_STATE_MISSING;
      CBearIncrementalSnapshot first;
      CBearIncrementalSnapshot second;
      const bool first_valid=first_exists &&
         LoadSlot(first_path,fingerprint,first) &&
         first.profile_id==profile_id && first.symbol==symbol;
      const bool second_valid=second_exists &&
         LoadSlot(second_path,fingerprint,second) &&
         second.profile_id==profile_id && second.symbol==symbol;
      if(!first_valid && !second_valid)
         return BEAR_STATE_INVALID;
      const bool use_first=first_valid &&
         (!second_valid || first.sequence>=second.sequence);
      const datetime as_of=(use_first ? first.as_of : second.as_of);
      if(current_time<as_of || current_time-as_of>maximum_age_seconds)
         return BEAR_STATE_STALE;
      if(use_first)
        {
         if(machine.Restore(first))
            return BEAR_STATE_LOADED;
         if(second_valid && machine.Restore(second))
            return BEAR_STATE_LOADED;
        }
      else
        {
         if(machine.Restore(second))
            return BEAR_STATE_LOADED;
         if(first_valid && machine.Restore(first))
            return BEAR_STATE_LOADED;
        }
      return BEAR_STATE_INVALID;
     }
  };

#endif
