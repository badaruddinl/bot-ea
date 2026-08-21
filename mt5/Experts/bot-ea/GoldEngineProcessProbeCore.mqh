#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineInstanceLease.mqh"

ProfileConfig ProbeProfile;
CEngineInstanceLease ProbeLease;
string ProbePath="";
string ProbeRuntimeId="";
ulong ProbeGeneration=0;

bool ProbeExpectedBinding(long &login,string &server)
  {
#ifdef BUILD_PROFILE_GOLDI
   login=108098316;
   server="XMGlobal-MT5 5";
#else
   login=391425346;
   server="XMGlobal-MT5 14";
#endif
   return true;
  }

bool WriteProbeHeartbeat(void)
  {
   if(!FolderCreate("bot-ea\\probe",FILE_COMMON) &&
      GetLastError()!=ERR_FILE_IS_DIRECTORY)
      return false;
   const int handle=FileOpen(
      ProbePath,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_COMMON);
   if(handle==INVALID_HANDLE)
      return false;
   ProbeGeneration++;
   FileWriteString(handle,StringFormat(
      "{\"profile_id\":\"%s\",\"profile_fingerprint\":\"%s\","
      "\"account_login\":%I64d,\"server\":\"%s\",\"generation\":%I64u,"
      "\"server_time\":%I64d,\"chart_id\":%I64d,"
      "\"runtime_id\":\"%s\","
      "\"order_authority\":\"DISABLED\"}\r\n",
      ProbeProfile.profile_id,ProbeProfile.profile_fingerprint,
      AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER),
      ProbeGeneration,(long)TimeCurrent(),ChartID(),ProbeRuntimeId));
   FileFlush(handle);
   FileClose(handle);
   return true;
  }

int OnInit(void)
  {
   LoadBuildProfile(ProbeProfile);
   long expected_login=0;string expected_server="";string reason="";
   ProbeExpectedBinding(expected_login,expected_server);
   if(!ValidateObservedAccountBinding(
         ProbeProfile,expected_login,expected_server,
         AccountInfoInteger(ACCOUNT_LOGIN),AccountInfoString(ACCOUNT_SERVER),
         (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE),reason))
     {
      Print("G18_PROCESS_PROBE rejected profile=",ProbeProfile.profile_id,
            " reason=",reason);
      return INIT_FAILED;
     }
   if(!ProbeLease.Acquire(ProbeProfile,expected_login,reason))
     {
      Print("G18_PROCESS_PROBE rejected profile=",ProbeProfile.profile_id,
            " reason=",reason);
      return INIT_FAILED;
     }
   ProbePath="bot-ea\\probe\\"+ProbeProfile.profile_id+".json";
   ProbeRuntimeId=StringFormat(
      "%I64d-%I64u-%I64d",(long)TimeLocal(),GetTickCount64(),ChartID());
   if(!WriteProbeHeartbeat())
      return INIT_FAILED;
   EventSetTimer(1);
   Print("G18_PROCESS_PROBE profile=",ProbeProfile.profile_id,
         " state=ONLINE order_authority=DISABLED");
   return INIT_SUCCEEDED;
  }

void OnTimer(void)
  {
   WriteProbeHeartbeat();
  }

void OnTick(void)
  {
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   ProbeLease.Release();
   Print("G18_PROCESS_PROBE profile=",ProbeProfile.profile_id,
         " state=STOPPED reason=",reason);
  }
