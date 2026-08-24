#ifndef GOLDI_FRANZ_AUDIT_MQH
#define GOLDI_FRANZ_AUDIT_MQH

#include "GoldIFranzTypes.mqh"

string FranzJsonEscape(const string value)
  {
   string escaped=value;
   StringReplace(escaped,"\\","\\\\");
   StringReplace(escaped,"\"","\\\"");
   StringReplace(escaped,"\r","\\r");
   StringReplace(escaped,"\n","\\n");
   StringReplace(escaped,"\t","\\t");
   return escaped;
  }

class CFranzAudit
  {
private:
   bool m_healthy;
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

public:
   CFranzAudit(void) { m_healthy=true; m_namespace="default"; }
   void Configure(const string run_id) { m_namespace=SafeNamespace(run_id); }
   bool Healthy(void) const { return m_healthy; }
   string Path(void) const { return BasePath()+"\\audit.jsonl"; }

   bool Emit(const string event_type,
             const datetime server_time,
             const FranzPersistentState &state,
             const string reason,
             const string payload="{}")
     {
      if(!FolderCreate(BasePath()))
        { m_healthy=false; return false; }
      const string setup_id=(StringLen(state.setup_id)>0 ? state.setup_id : "");
      const string event_id=setup_id+"|"+event_type+"|"+
         IntegerToString((long)server_time)+"|"+reason;
      const string line=StringFormat(
         "{\"schema_version\":1,\"event_id\":\"%s\"," 
         "\"strategy\":\"GOLDI_FRANZ_SHAKEOUT\",\"version\":\"0.1.0\"," 
         "\"symbol\":\"GOLD.i#\",\"magic\":26081914,"
         "\"event_type\":\"%s\",\"server_time\":%I64d,"
         "\"state\":%d,\"mode\":\"%s\",\"side\":\"%s\","
         "\"setup_id\":\"%s\",\"reason\":\"%s\",\"payload\":%s}\r\n",
         FranzJsonEscape(event_id),FranzJsonEscape(event_type),(long)server_time,
         (int)state.state,FranzModeName(state.mode),FranzSideName(state.side),
         FranzJsonEscape(setup_id),FranzJsonEscape(reason),payload);
      const int handle=FileOpen(Path(),FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|
         FILE_SHARE_READ|FILE_SHARE_WRITE);
      if(handle==INVALID_HANDLE) { m_healthy=false; return false; }
      FileSeek(handle,0,SEEK_END);
      const uint written=FileWriteString(handle,line);
      FileFlush(handle);
      FileClose(handle);
      m_healthy=written==StringLen(line);
      return m_healthy;
     }
  };

#endif
