#property strict
#property tester_everytick_calculate

#include "../../Include/bot-ea/GoldEnginePositionLifecycle.mqh"

bool HarnessPassed=false;

int OnInit(void)
  {
   ExpectedPositionState expected;
   PositionStateReset(expected);
   expected.active=true;
   expected.ticket=7001;
   expected.identifier=9001;
   expected.signal_id="GOLDI:REVISED:1";
   expected.volume=0.02;
   expected.entry_price=4400.0;
   expected.stop_loss=4390.0;
   expected.take_profit=4420.0;

   const long manual_close_magic=0;
   const bool manual_by_ticket=manual_close_magic==0 &&
      PositionExitBelongsToExpected(expected,7001,0);
   const bool manual_by_identifier=manual_close_magic==0 &&
      PositionExitBelongsToExpected(expected,0,9001);
   const bool unrelated_manual_ignored=manual_close_magic==0 &&
      !PositionExitBelongsToExpected(expected,8001,8001);
   const bool reasons=
      PositionCloseReasonCode(DEAL_REASON_CLIENT)=="MANUAL_DESKTOP" &&
      PositionCloseReasonCode(DEAL_REASON_MOBILE)=="MANUAL_MOBILE" &&
      PositionCloseReasonCode(DEAL_REASON_WEB)=="MANUAL_WEB" &&
      PositionCloseReasonCode(DEAL_REASON_SL)=="STOP_LOSS" &&
      PositionCloseReasonCode(DEAL_REASON_TP)=="TAKE_PROFIT" &&
      PositionCloseReasonCode(DEAL_REASON_EXPERT)=="EA" &&
      PositionCloseReasonCode(DEAL_REASON_SO)=="STOP_OUT" &&
      PositionCloseEventReason("MANUAL_MOBILE",false)==
         "POSITION_CLOSED_MANUAL_MOBILE" &&
      PositionCloseEventReason("MANUAL_DESKTOP",true)==
         "POSITION_PARTIALLY_CLOSED_MANUAL_DESKTOP";

   HarnessPassed=manual_by_ticket && manual_by_identifier &&
      unrelated_manual_ignored && reasons;
   PrintFormat(
      "POSITION_LIFECYCLE passed=%s manual_ticket=%s manual_identifier=%s "
      "unrelated_manual_ignored=%s reasons=%s order_authority=DISABLED",
      HarnessPassed ? "true" : "false",manual_by_ticket ? "true" : "false",
      manual_by_identifier ? "true" : "false",
      unrelated_manual_ignored ? "true" : "false",reasons ? "true" : "false");
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
