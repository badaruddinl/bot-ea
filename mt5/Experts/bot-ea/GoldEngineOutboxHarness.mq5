#property strict
#property tester_everytick_calculate

#define BUILD_PROFILE_GOLDI
#include "../../Include/bot-ea/GoldEngineProfile.mqh"
#include "../../Include/bot-ea/GoldEngineOutbox.mqh"

bool HarnessPassed=false;

bool ReadOutboxLine(const string path,string &line)
  {
   const int handle=FileOpen(path,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE)
      return false;
   line=FileReadString(handle);
   FileClose(handle);
   return line!="";
  }

int OnInit(void)
  {
   ProfileConfig goldi;LoadBuildProfile(goldi);
   CEngineOutbox goldi_outbox;
   const bool goldi_initialized=goldi_outbox.Initialize(goldi);
   FileDelete(goldi_outbox.Path(),FILE_COMMON);
   EngineEvent entry;
   entry.type=ENGINE_EVENT_ENTRY_READY;
   entry.profile_id="GOLDI";
   entry.event_id="G16-GOLDI-ENTRY-1";
   entry.server_time=TimeCurrent();
   entry.reason="M1_CONFIRMATION_READY";
   const bool entry_written=goldi_outbox.Emit(
      "ENTRY_READY",entry,"setup-1","signal-1");
   string goldi_line="";
   const bool goldi_read=ReadOutboxLine(goldi_outbox.Path(),goldi_line);

   ProfileConfig goldm=goldi;
   goldm.profile_id="GOLDM";
   goldm.profile_version="1.0.0";
   goldm.profile_fingerprint=
      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
   goldm.symbol="GOLDm#";
   CEngineOutbox goldm_outbox;
   const bool goldm_initialized=goldm_outbox.Initialize(goldm);
   FileDelete(goldm_outbox.Path(),FILE_COMMON);
   EngineEvent watch=entry;
   watch.profile_id="GOLDM";
   watch.event_id="G16-GOLDM-WATCH-1";
   watch.reason="WATCH_H1";
   const bool watch_written=goldm_outbox.Emit("WATCH_UPDATED",watch,"setup-2");
   string goldm_line="";
   const bool goldm_read=ReadOutboxLine(goldm_outbox.Path(),goldm_line);

   HarnessPassed=goldi_initialized && entry_written && goldi_read &&
      StringFind(goldi_line,"\"profile_id\":\"GOLDI\"")>=0 &&
      StringFind(goldi_line,"\"audience\":\"goldi_approved\"")>=0 &&
      goldm_initialized && watch_written && goldm_read &&
      StringFind(goldm_line,"\"profile_id\":\"GOLDM\"")>=0 &&
      StringFind(goldm_line,"\"audience\":\"admin_only\"")>=0 &&
      goldi_outbox.Healthy() && goldm_outbox.Healthy();
   Print("G16_OUTBOX passed=",HarnessPassed,
         " goldi_append=",entry_written," goldm_append=",watch_written,
         " goldi_audience=goldi_approved goldm_audience=admin_only",
         " order_authority=DISABLED");
   FileDelete(goldi_outbox.Path(),FILE_COMMON);
   FileDelete(goldm_outbox.Path(),FILE_COMMON);
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
