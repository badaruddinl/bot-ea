#ifndef GOLD_ENGINE_POSITION_PERSISTENCE_MQH
#define GOLD_ENGINE_POSITION_PERSISTENCE_MQH

#include "GoldEngineTypes.mqh"

enum PositionStateLoadStatus
  {
   POSITION_STATE_MISSING=0,
   POSITION_STATE_VALID=1,
   POSITION_STATE_INVALID=2
  };

struct ExpectedPositionState
  {
   ulong  generation;
   bool   active;
   ulong  ticket;
   ulong  identifier;
   string signal_id;
   double volume;
   double entry_price;
   double stop_loss;
   double take_profit;
  };

void PositionStateReset(ExpectedPositionState &state)
  {
   state.generation=0;
   state.active=false;
   state.ticket=0;
   state.identifier=0;
   state.signal_id="";
   state.volume=0.0;
   state.entry_price=0.0;
   state.stop_loss=0.0;
   state.take_profit=0.0;
  }

uint PositionStateChecksum(const string value)
  {
   uint hash=2166136261;
   const int length=StringLen(value);
   for(int index=0;index<length;index++)
     {
      hash^=(uint)StringGetCharacter(value,index);
      hash*=16777619;
     }
   return hash;
  }

bool PositionStateMatches(const ManagedPosition &actual,
                          const ExpectedPositionState &expected,
                          const double tick_size,
                          string &reason)
  {
   const double tolerance=MathMax(tick_size*0.5,1e-8);
   if(!expected.active)
     {
      reason="POSITION_NOT_EXPECTED_ACTIVE";
      return false;
     }
   if(expected.identifier>0 && actual.identifier!=expected.identifier)
     {
      reason="POSITION_IDENTIFIER_CHANGED";
      return false;
     }
   if(MathAbs(actual.volume-expected.volume)>1e-8)
     {
      reason="POSITION_VOLUME_CHANGED";
      return false;
     }
   if(MathAbs(actual.entry_price-expected.entry_price)>tolerance)
     {
      reason="POSITION_ENTRY_CHANGED";
      return false;
     }
   if(MathAbs(actual.stop_loss-expected.stop_loss)>tolerance)
     {
      reason="POSITION_STOP_CHANGED";
      return false;
     }
   if(MathAbs(actual.take_profit-expected.take_profit)>tolerance)
     {
      reason="POSITION_TARGET_CHANGED";
      return false;
     }
   reason="OK";
   return true;
  }

class CPositionStateStore
  {
private:
   string m_profile_id;
   string m_profile_fingerprint;

   string SlotPath(const int slot) const
     {
      return "bot-ea\\position-"+m_profile_id+"-"+
             IntegerToString(slot)+".state";
     }

   string Serialize(const ExpectedPositionState &state) const
     {
      return StringFormat(
         "2|%s|%s|%I64u|%d|%I64u|%I64u|%s|%.8f|%.8f|%.8f|%.8f",
         m_profile_id,m_profile_fingerprint,state.generation,
         state.active ? 1 : 0,state.ticket,state.identifier,state.signal_id,
         state.volume,state.entry_price,state.stop_loss,state.take_profit);
     }

   PositionStateLoadStatus ReadSlot(const int slot,
                                    ExpectedPositionState &state) const
     {
      PositionStateReset(state);
      const int handle=FileOpen(
         SlotPath(slot),FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(handle==INVALID_HANDLE)
         return POSITION_STATE_MISSING;
      const string payload=FileReadString(handle);
      const string checksum_text=FileReadString(handle);
      FileClose(handle);
      if(payload=="" || checksum_text=="")
         return POSITION_STATE_INVALID;
      if((uint)StringToInteger(checksum_text)!=PositionStateChecksum(payload))
         return POSITION_STATE_INVALID;
      string fields[];
      const int field_count=StringSplit(payload,'|',fields);
      if(field_count<11)
         return POSITION_STATE_INVALID;
      const bool legacy=fields[0]=="1";
      if((!legacy && fields[0]!="2") || fields[1]!=m_profile_id ||
         fields[2]!=m_profile_fingerprint)
         return POSITION_STATE_INVALID;
      state.generation=(ulong)StringToInteger(fields[3]);
      state.active=StringToInteger(fields[4])==1;
      state.ticket=(ulong)StringToInteger(fields[5]);
      const int signal_start=(legacy ? 6 : 7);
      state.identifier=(legacy ? 0 :
         (ulong)StringToInteger(fields[6]));
      state.signal_id=fields[signal_start];
      for(int index=signal_start+1;index<=field_count-5;index++)
         state.signal_id+="|"+fields[index];
      state.volume=StringToDouble(fields[field_count-4]);
      state.entry_price=StringToDouble(fields[field_count-3]);
      state.stop_loss=StringToDouble(fields[field_count-2]);
      state.take_profit=StringToDouble(fields[field_count-1]);
      if(state.generation==0 ||
         (state.active && (state.ticket==0 || (!legacy && state.identifier==0) ||
                           state.signal_id=="" ||
                           state.volume<=0.0)))
         return POSITION_STATE_INVALID;
      return POSITION_STATE_VALID;
     }

public:
   void Initialize(const string profile_id,const string profile_fingerprint)
     {
      m_profile_id=profile_id;
      m_profile_fingerprint=profile_fingerprint;
     }

   PositionStateLoadStatus Load(ExpectedPositionState &state) const
     {
      ExpectedPositionState first;
      ExpectedPositionState second;
      const PositionStateLoadStatus first_status=ReadSlot(0,first);
      const PositionStateLoadStatus second_status=ReadSlot(1,second);
      if(first_status==POSITION_STATE_VALID &&
         second_status==POSITION_STATE_VALID)
        {
         state=(first.generation>=second.generation ? first : second);
         return POSITION_STATE_VALID;
        }
      if(first_status==POSITION_STATE_VALID)
        {
         state=first;
         return POSITION_STATE_VALID;
        }
      if(second_status==POSITION_STATE_VALID)
        {
         state=second;
         return POSITION_STATE_VALID;
        }
      PositionStateReset(state);
      if(first_status==POSITION_STATE_MISSING &&
         second_status==POSITION_STATE_MISSING)
         return POSITION_STATE_MISSING;
      return POSITION_STATE_INVALID;
     }

   bool Save(ExpectedPositionState &state)
     {
      ExpectedPositionState current;
      const PositionStateLoadStatus status=Load(current);
      state.generation=(status==POSITION_STATE_VALID ? current.generation+1 : 1);
      const string payload=Serialize(state);
      const int slot=(int)(state.generation%2);
      const int handle=FileOpen(
         SlotPath(slot),FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(handle==INVALID_HANDLE)
         return false;
      FileWriteString(handle,payload+"\r\n");
      FileWriteString(handle,IntegerToString((long)PositionStateChecksum(payload))+"\r\n");
      FileFlush(handle);
      FileClose(handle);
      ExpectedPositionState verified;
      return ReadSlot(slot,verified)==POSITION_STATE_VALID &&
             verified.generation==state.generation;
     }

   bool Clear(ExpectedPositionState &state)
     {
      PositionStateReset(state);
      return Save(state);
     }

   void DeleteTestState(void) const
     {
      FileDelete(SlotPath(0),FILE_COMMON);
      FileDelete(SlotPath(1),FILE_COMMON);
     }
  };

#endif
