#ifndef GOLD_ENGINE_POSITION_LIFECYCLE_MQH
#define GOLD_ENGINE_POSITION_LIFECYCLE_MQH

#include "GoldEnginePositionPersistence.mqh"

string PositionCloseReasonCode(const ENUM_DEAL_REASON reason)
  {
   if(reason==DEAL_REASON_SL) return "STOP_LOSS";
   if(reason==DEAL_REASON_TP) return "TAKE_PROFIT";
   if(reason==DEAL_REASON_CLIENT) return "MANUAL_DESKTOP";
   if(reason==DEAL_REASON_MOBILE) return "MANUAL_MOBILE";
   if(reason==DEAL_REASON_WEB) return "MANUAL_WEB";
   if(reason==DEAL_REASON_EXPERT) return "EA";
   if(reason==DEAL_REASON_SO) return "STOP_OUT";
   return "BROKER_OTHER";
  }

string PositionCloseEventReason(const string code,const bool partial)
  {
   return (partial ? "POSITION_PARTIALLY_CLOSED_" : "POSITION_CLOSED_")+code;
  }

bool PositionExitBelongsToExpected(const ExpectedPositionState &expected,
                                   const ulong transaction_position,
                                   const ulong deal_position_identifier)
  {
   if(!expected.active)
      return false;
   return (transaction_position>0 && transaction_position==expected.ticket) ||
          (deal_position_identifier>0 &&
           deal_position_identifier==expected.identifier);
  }

#endif
