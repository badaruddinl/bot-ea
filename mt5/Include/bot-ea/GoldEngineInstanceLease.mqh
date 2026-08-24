#ifndef GOLD_ENGINE_INSTANCE_LEASE_MQH
#define GOLD_ENGINE_INSTANCE_LEASE_MQH

#include "GoldEngineTypes.mqh"

class CEngineInstanceLease
  {
private:
   int    m_handle;
   string m_path;

public:
   CEngineInstanceLease(void)
     {
      m_handle=INVALID_HANDLE;
      m_path="";
     }

   bool Acquire(const ProfileConfig &profile,const long account_login,string &reason)
     {
      if(m_handle!=INVALID_HANDLE)
        {
         reason="INSTANCE_LEASE_ALREADY_HELD";
         return true;
        }
      if(account_login<=0 || profile.profile_id=="" || profile.magic<=0)
        {
         reason="INSTANCE_LEASE_IDENTITY_INVALID";
         return false;
        }
      if(!FolderCreate("bot-ea\\locks",FILE_COMMON) &&
         GetLastError()!=ERR_FILE_IS_DIRECTORY)
        {
         reason="INSTANCE_LEASE_DIRECTORY_FAILED";
         return false;
        }
      m_path="bot-ea\\locks\\"+profile.profile_id+"-"+
         IntegerToString(account_login)+"-"+IntegerToString(profile.magic)+".lock";
      ResetLastError();
      m_handle=FileOpen(m_path,FILE_READ|FILE_WRITE|FILE_BIN|FILE_COMMON);
      if(m_handle==INVALID_HANDLE)
        {
         reason="DUPLICATE_EA_INSTANCE";
         return false;
        }
      FileSeek(m_handle,0,SEEK_SET);
      FileWriteString(m_handle,StringFormat(
         "profile=%s\nlogin=%I64d\nmagic=%I64d\nchart=%I64d\n",
         profile.profile_id,account_login,profile.magic,ChartID()));
      FileFlush(m_handle);
      reason="INSTANCE_LEASE_ACQUIRED";
      return true;
     }

   bool Held(void) const
     {
      return m_handle!=INVALID_HANDLE;
     }

   string Path(void) const
     {
      return m_path;
     }

   void Release(void)
     {
      if(m_handle!=INVALID_HANDLE)
        {
         FileClose(m_handle);
         m_handle=INVALID_HANDLE;
        }
     }
  };

#endif
