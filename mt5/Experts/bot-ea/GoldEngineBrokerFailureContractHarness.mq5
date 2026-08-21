#property strict
#property tester_everytick_calculate

#include "../../Include/bot-ea/GoldEngineExecutionBroker.mqh"

bool HarnessPassed=false;

int OnInit(void)
  {
   const bool done=ExecutionRetcodeSuccess(TRADE_RETCODE_DONE);
   const bool placed=ExecutionRetcodeSuccess(TRADE_RETCODE_PLACED);
   const bool partial=ExecutionRetcodeSuccess(TRADE_RETCODE_DONE_PARTIAL);
   const bool timeout=ExecutionRetcodeAmbiguous(TRADE_RETCODE_TIMEOUT);
   const bool connection=ExecutionRetcodeAmbiguous(TRADE_RETCODE_CONNECTION);
   const bool generic=ExecutionRetcodeAmbiguous(TRADE_RETCODE_ERROR);
   const bool funds_rejected=!ExecutionRetcodeAmbiguous(TRADE_RETCODE_NO_MONEY) &&
      !ExecutionRetcodeSuccess(TRADE_RETCODE_NO_MONEY);
   const bool invalid_rejected=!ExecutionRetcodeAmbiguous(TRADE_RETCODE_INVALID) &&
      !ExecutionRetcodeSuccess(TRADE_RETCODE_INVALID);
   HarnessPassed=done && placed && partial && timeout && connection && generic &&
      funds_rejected && invalid_rejected;
   Print("G18_BROKER_FAILURE_CONTRACT passed=",HarnessPassed,
         " partial=",partial,
         " timeout_ambiguous=",timeout,
         " connection_ambiguous=",connection,
         " funds_rejected=",funds_rejected,
         " invalid_rejected=",invalid_rejected,
         " blind_retry=false order_authority=DISABLED");
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }

void OnTick(void)
  {
  }
