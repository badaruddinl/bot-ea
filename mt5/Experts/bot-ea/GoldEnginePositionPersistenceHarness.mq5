#property strict
#property tester_everytick_calculate

#include <bot-ea/GoldEnginePositionPersistence.mqh>

bool HarnessPassed=false;

bool RunHarness(void)
  {
   const string profile_id="G14POSITIONTEST";
   const string fingerprint=
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
   CPositionStateStore store;
   store.Initialize(profile_id,fingerprint);
   store.DeleteTestState();

   ExpectedPositionState state;
   const bool missing=store.Load(state)==POSITION_STATE_MISSING;
   PositionStateReset(state);
   state.active=true;
   state.ticket=77123;
   state.signal_id="GOLDI:REVISED:BUY:77123";
   state.volume=0.02;
   state.entry_price=4400.10;
   state.stop_loss=4390.10;
   state.take_profit=4425.10;
   const bool saved=store.Save(state);

   ExpectedPositionState loaded;
   const bool loaded_valid=store.Load(loaded)==POSITION_STATE_VALID &&
      loaded.active && loaded.ticket==state.ticket &&
      loaded.signal_id==state.signal_id;
   ManagedPosition actual;
   ZeroMemory(actual);
   actual.ticket=loaded.ticket;
   actual.volume=loaded.volume;
   actual.entry_price=loaded.entry_price;
   actual.stop_loss=loaded.stop_loss;
   actual.take_profit=loaded.take_profit;
   string match_reason="";
   const bool geometry_matches=PositionStateMatches(
      actual,loaded,0.01,match_reason);
   actual.stop_loss+=0.02;
   string intervention_reason="";
   const bool manual_detected=!PositionStateMatches(
      actual,loaded,0.01,intervention_reason) &&
      intervention_reason=="POSITION_STOP_CHANGED";

   loaded.take_profit=4420.10;
   const bool second_saved=store.Save(loaded);
   const int corrupt=FileOpen(
      "bot-ea\\position-"+profile_id+"-0.state",
      FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(corrupt!=INVALID_HANDLE)
     {
      FileWriteString(corrupt,"corrupt\r\n0\r\n");
      FileClose(corrupt);
     }
   CPositionStateStore restarted;
   restarted.Initialize(profile_id,fingerprint);
   ExpectedPositionState recovered;
   const bool fallback_recovered=
      restarted.Load(recovered)==POSITION_STATE_VALID &&
      recovered.generation==1 && recovered.take_profit==4425.10;
   const bool cleared=restarted.Clear(recovered) &&
      restarted.Load(recovered)==POSITION_STATE_VALID && !recovered.active;
   restarted.DeleteTestState();

   const bool passed=missing && saved && loaded_valid && geometry_matches &&
      manual_detected && second_saved && fallback_recovered && cleared;
   PrintFormat(
      "G14_POSITION_PERSISTENCE passed=%s missing=%s saved=%s loaded=%s "
      "geometry=%s manual=%s restart_fallback=%s cleared=%s reason=%s "
      "order_authority=DISABLED",
      passed ? "true" : "false",missing ? "true" : "false",
      saved ? "true" : "false",loaded_valid ? "true" : "false",
      geometry_matches ? "true" : "false",manual_detected ? "true" : "false",
      fallback_recovered ? "true" : "false",cleared ? "true" : "false",
      intervention_reason);
   return passed;
  }

int OnInit(void)
  {
   HarnessPassed=RunHarness();
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
