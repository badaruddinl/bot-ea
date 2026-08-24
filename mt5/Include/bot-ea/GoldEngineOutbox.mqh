#ifndef GOLD_ENGINE_OUTBOX_MQH
#define GOLD_ENGINE_OUTBOX_MQH

#include "GoldEngineTypes.mqh"

string OutboxJsonEscape(const string value)
  {
   string escaped=value;
   StringReplace(escaped,"\\","\\\\");
   StringReplace(escaped,"\"","\\\"");
   StringReplace(escaped,"\r","\\r");
   StringReplace(escaped,"\n","\\n");
   StringReplace(escaped,"\t","\\t");
   return escaped;
  }

class CEngineOutbox
  {
private:
   ProfileConfig m_profile;
   string        m_path;
   bool          m_initialized;
   bool          m_last_write_ok;

   string Audience(const string event_type) const
     {
      if(m_profile.profile_id=="GOLDM")
         return "admin_only";
      if(event_type=="WATCH_UPDATED" || event_type=="SETUP_CREATED" ||
         event_type=="ENTRY_READY")
         return "internal";
      if(m_profile.profile_id=="GOLDI" &&
         (event_type=="POSITION_OPENED" || event_type=="POSITION_CLOSED"))
         return "goldi_approved";
      return "admin_only";
     }

public:
   CEngineOutbox(void)
     {
      m_initialized=false;
      m_last_write_ok=true;
     }

   bool Initialize(const ProfileConfig &profile)
     {
      m_profile=profile;
      m_path="bot-ea\\spool\\"+profile.profile_id+".jsonl";
      m_initialized=profile.profile_id!="" &&
         StringLen(profile.profile_fingerprint)==64;
      m_last_write_ok=m_initialized;
      return m_initialized;
     }

   string Path(void) const
     {
      return m_path;
     }

   bool Healthy(void) const
     {
      return m_initialized && m_last_write_ok;
     }

   bool Emit(const string event_type,
             const EngineEvent &event,
             const string setup_id="",
             const string signal_id="",
             const string order_id="",
             const string position_id="",
             const string payload="{}")
     {
      if(!m_initialized)
         return false;
      const string outbox_event_id=event.event_id+"|"+event_type+"|"+event.reason;
      const string line=StringFormat(
         "{\"schema_version\":1,\"event_id\":\"%s\","
         "\"profile_id\":\"%s\",\"profile_version\":\"%s\","
         "\"profile_fingerprint\":\"%s\",\"event_type\":\"%s\","
         "\"symbol\":\"%s\",\"server_time\":%I64d,\"reason\":\"%s\","
         "\"audience\":\"%s\",\"setup_id\":\"%s\","
         "\"signal_id\":\"%s\",\"order_id\":\"%s\","
         "\"position_id\":\"%s\",\"payload\":%s}\r\n",
         OutboxJsonEscape(outbox_event_id),OutboxJsonEscape(m_profile.profile_id),
         OutboxJsonEscape(m_profile.profile_version),
         OutboxJsonEscape(m_profile.profile_fingerprint),OutboxJsonEscape(event_type),
         OutboxJsonEscape(m_profile.symbol),(long)event.server_time,
         OutboxJsonEscape(event.reason),Audience(event_type),
         OutboxJsonEscape(setup_id),OutboxJsonEscape(signal_id),
         OutboxJsonEscape(order_id),OutboxJsonEscape(position_id),payload);
      const int handle=FileOpen(
         m_path,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|
         FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON);
      if(handle==INVALID_HANDLE)
        {
         m_last_write_ok=false;
         return false;
        }
      FileSeek(handle,0,SEEK_END);
      const uint written=FileWriteString(handle,line);
      FileFlush(handle);
      FileClose(handle);
      m_last_write_ok=written==StringLen(line);
      return m_last_write_ok;
     }
  };

#endif
