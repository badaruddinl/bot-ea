#ifndef GOLD_ENGINE_ENTRY_GATE_MQH
#define GOLD_ENGINE_ENTRY_GATE_MQH

#include "GoldEngineTypes.mqh"

class CEntryGate
  {
private:
   ProfileConfig m_profile;
   bool          m_initialized;
   bool          m_enabled;
   string        m_session_id;

   string SessionPath(void) const
     {
      return "bot-ea\\control\\"+m_profile.profile_id+".entry-session";
     }

   string CommandPath(void) const
     {
      return "bot-ea\\control\\"+m_profile.profile_id+".entry-gate";
     }

   bool WriteSession(const bool authority_enabled)
     {
      FolderCreate("bot-ea\\control",FILE_COMMON);
      const int handle=FileOpen(SessionPath(),
         FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ);
      if(handle==INVALID_HANDLE)
         return false;
      const string payload=StringFormat("1|%s|%s|%I64d|%s|%s",
         m_profile.profile_id,m_profile.profile_fingerprint,
         AccountInfoInteger(ACCOUNT_LOGIN),m_session_id,
         authority_enabled ? "ENABLED" : "DISABLED");
      const uint written=FileWriteString(handle,payload+"\r\n");
      FileFlush(handle);
      FileClose(handle);
      return written>0;
     }

   bool ReadEnabledCommand(void) const
     {
      const int handle=FileOpen(CommandPath(),
         FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE);
      if(handle==INVALID_HANDLE)
         return false;
      const string payload=FileReadString(handle);
      FileClose(handle);
      string parts[];
      const ushort separator=(ushort)StringGetCharacter("|",0);
      if(StringSplit(payload,separator,parts)!=8)
         return false;
      return parts[0]=="1" &&
         parts[1]==m_profile.profile_id &&
         parts[2]==m_profile.profile_fingerprint &&
         parts[3]==IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) &&
         parts[4]==m_session_id &&
         parts[5]=="ENABLED";
     }

public:
   CEntryGate(void)
     {
      m_initialized=false;
      m_enabled=false;
      m_session_id="";
     }

   bool Initialize(const ProfileConfig &profile,const bool authority_enabled)
     {
      m_profile=profile;
      m_enabled=false;
      m_session_id=StringFormat("%I64d-%I64d-%I64u",
         AccountInfoInteger(ACCOUNT_LOGIN),(long)TimeLocal(),GetTickCount64());
      if((bool)MQLInfoInteger(MQL_TESTER))
        {
         m_enabled=authority_enabled;
         m_initialized=true;
         return true;
        }
      if(!WriteSession(authority_enabled))
         return false;
      m_initialized=true;
      return true;
     }

   bool Refresh(bool &changed)
     {
      changed=false;
      if(!m_initialized)
         return false;
      if((bool)MQLInfoInteger(MQL_TESTER))
         return true;
      const bool next=ReadEnabledCommand();
      changed=(next!=m_enabled);
      m_enabled=next;
      return true;
     }

   bool Enabled(void) const
     {
      return m_initialized && m_enabled;
     }
  };

#endif
