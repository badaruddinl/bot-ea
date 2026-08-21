#ifndef GOLD_ENGINE_EXECUTION_BROKER_MQH
#define GOLD_ENGINE_EXECUTION_BROKER_MQH

#include <Trade/Trade.mqh>
#include "GoldEngineBrokerContext.mqh"

enum ExecutionSubmitState
  {
   EXECUTION_SUBMIT_NONE=0,
   EXECUTION_SUBMIT_DISABLED=1,
   EXECUTION_SUBMIT_REJECTED=2,
   EXECUTION_SUBMIT_SENT=3,
   EXECUTION_SUBMIT_FAILED=4,
   EXECUTION_SUBMIT_RECONCILED=5
  };

struct ExecutionReceipt
  {
   ExecutionSubmitState state;
   string               signal_id;
   bool                 validation_allowed;
   bool                 sent;
   ulong                reject_mask;
   uint                 retcode;
   ulong                order_ticket;
   ulong                deal_ticket;
   double               executed_price;
   double               executed_volume;
   string               reason;
  };

enum PositionActionState
  {
   POSITION_ACTION_NONE=0,
   POSITION_ACTION_DISABLED=1,
   POSITION_ACTION_REJECTED=2,
   POSITION_ACTION_DONE=3,
   POSITION_ACTION_FAILED=4
  };

struct PositionActionReceipt
  {
   PositionActionState state;
   ulong               position_ticket;
   bool                sent;
   uint                retcode;
   string              reason;
  };

void ExecutionResetReceipt(ExecutionReceipt &receipt)
  {
   receipt.state=EXECUTION_SUBMIT_NONE;
   receipt.signal_id="";
   receipt.validation_allowed=false;
   receipt.sent=false;
   receipt.reject_mask=0;
   receipt.retcode=0;
   receipt.order_ticket=0;
   receipt.deal_ticket=0;
   receipt.executed_price=0.0;
   receipt.executed_volume=0.0;
   receipt.reason="";
  }

bool ExecutionRetcodeSuccess(const uint retcode)
  {
   return retcode==TRADE_RETCODE_DONE ||
          retcode==TRADE_RETCODE_PLACED ||
          retcode==TRADE_RETCODE_DONE_PARTIAL;
  }

bool ExecutionRetcodeAmbiguous(const uint retcode)
  {
   return retcode==0 ||
          retcode==TRADE_RETCODE_ERROR ||
          retcode==TRADE_RETCODE_TIMEOUT ||
          retcode==TRADE_RETCODE_CONNECTION;
  }

void ExecutionResetPositionReceipt(PositionActionReceipt &receipt)
  {
   receipt.state=POSITION_ACTION_NONE;
   receipt.position_ticket=0;
   receipt.sent=false;
   receipt.retcode=0;
   receipt.reason="";
  }

class CExecutionBroker
  {
private:
   ProfileConfig m_profile;
   CTrade        m_trade;
   bool          m_initialized;
   bool          m_authority_enabled;

   bool ReconcileSignalPosition(const SignalPlan &plan,
                                ExecutionReceipt &receipt,
                                string &reason)
     {
      const string expected_comment=ExecutionSignalComment(
         plan.profile_id,plan.signal_id);
      int matches=0;
      ulong matched_ticket=0;
      double matched_price=0.0;
      double matched_volume=0.0;
      const int total=PositionsTotal();
      for(int index=0;index<total;index++)
        {
         const ulong ticket=PositionGetTicket(index);
         if(ticket==0 || !PositionSelectByTicket(ticket))
            continue;
         if(PositionGetString(POSITION_SYMBOL)!=m_profile.symbol ||
            PositionGetInteger(POSITION_MAGIC)!=m_profile.magic ||
            PositionGetString(POSITION_COMMENT)!=expected_comment)
            continue;
         matches++;
         matched_ticket=ticket;
         matched_price=PositionGetDouble(POSITION_PRICE_OPEN);
         matched_volume=PositionGetDouble(POSITION_VOLUME);
        }
      if(matches!=1)
        {
         reason=(matches==0 ? "AMBIGUOUS_RESULT_NO_POSITION" :
                 "AMBIGUOUS_RESULT_MULTIPLE_POSITIONS");
         return false;
        }
      receipt.state=EXECUTION_SUBMIT_RECONCILED;
      receipt.sent=true;
      receipt.order_ticket=matched_ticket;
      receipt.executed_price=matched_price;
      receipt.executed_volume=matched_volume;
      receipt.reason="ORDER_RECONCILED_AFTER_AMBIGUOUS_RESULT";
      reason=receipt.reason;
      return true;
     }

   bool SelectOwnedPosition(const ulong ticket,string &reason)
     {
      if(ticket==0 || !PositionSelectByTicket(ticket))
        {
         reason="POSITION_NOT_FOUND";
         return false;
        }
      if(PositionGetString(POSITION_SYMBOL)!=m_profile.symbol ||
         PositionGetInteger(POSITION_MAGIC)!=m_profile.magic)
        {
         reason="POSITION_OWNERSHIP_MISMATCH";
         return false;
        }
      const string prefix="GE|"+m_profile.profile_id+"|";
      if(StringFind(PositionGetString(POSITION_COMMENT),prefix)!=0)
        {
         reason="POSITION_COMMENT_MISMATCH";
         return false;
        }
      reason="OK";
      return true;
     }

public:
   CExecutionBroker(void)
     {
      m_initialized=false;
      m_authority_enabled=false;
     }

   bool Initialize(const ProfileConfig &profile,
                   const bool authority_requested,
                   string &reason)
     {
      m_profile=profile;
      m_initialized=false;
      m_authority_enabled=false;
      if(profile.order_authority_default)
        {
         reason="PROFILE_AUTHORITY_DEFAULT_UNSAFE";
         return false;
        }
      if(profile.magic<=0 || profile.symbol=="" ||
         StringLen(profile.profile_fingerprint)!=64)
        {
         reason="EXECUTION_PROFILE_INVALID";
         return false;
        }
      m_trade.SetExpertMagicNumber((ulong)profile.magic);
      m_trade.SetDeviationInPoints((ulong)profile.deviation_points);
      m_trade.SetAsyncMode(false);
      if(!m_trade.SetTypeFillingBySymbol(profile.symbol))
        {
         reason="EXECUTION_FILLING_UNAVAILABLE";
         return false;
        }
      m_authority_enabled=authority_requested;
      m_initialized=true;
      reason=(m_authority_enabled ? "ORDER_AUTHORITY_ENABLED" :
              "ORDER_AUTHORITY_DISABLED");
      return true;
     }

   bool AuthorityEnabled(void) const
     {
      return m_initialized && m_authority_enabled;
     }

   void DisableAuthority(void)
     {
      m_authority_enabled=false;
     }

   bool Submit(const SignalPlan &plan,
               ExecutionReceipt &receipt,
               string &reason)
     {
      ExecutionResetReceipt(receipt);
      receipt.signal_id=plan.signal_id;
      if(!m_initialized)
        {
         receipt.state=EXECUTION_SUBMIT_FAILED;
         receipt.reason="EXECUTION_BROKER_NOT_INITIALIZED";
         reason=receipt.reason;
         return false;
        }

      ExecutionContext context;
      BrokerPreflight preflight;
      if(!ExecutionCollectBrokerContext(plan,m_profile,context,preflight,reason))
        {
         receipt.state=EXECUTION_SUBMIT_REJECTED;
         receipt.retcode=preflight.check_result.retcode;
         receipt.reason=reason;
         return false;
        }
      ExecutionValidation validation;
      if(!ValidateExecution(plan,m_profile,context,validation))
        {
         receipt.state=EXECUTION_SUBMIT_REJECTED;
         receipt.reject_mask=validation.reject_mask;
         receipt.retcode=preflight.check_result.retcode;
         receipt.reason=validation.primary_reason;
         reason=receipt.reason;
         return false;
        }
      receipt.validation_allowed=true;
      receipt.reject_mask=validation.reject_mask;
      receipt.retcode=preflight.check_result.retcode;
      if(!m_authority_enabled)
        {
         receipt.state=EXECUTION_SUBMIT_DISABLED;
         receipt.reason="ORDER_AUTHORITY_DISABLED";
         reason=receipt.reason;
         return false;
        }

      const string comment=ExecutionSignalComment(plan.profile_id,plan.signal_id);
      const bool sent=m_trade.PositionOpen(
         validation.order.symbol,
         validation.order.side==ENGINE_SIDE_BUY ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
         validation.order.volume,
         validation.order.price,
         validation.order.stop_loss,
         validation.order.take_profit,
         comment);
      receipt.sent=sent;
      receipt.retcode=m_trade.ResultRetcode();
      receipt.order_ticket=m_trade.ResultOrder();
      receipt.deal_ticket=m_trade.ResultDeal();
      receipt.executed_price=m_trade.ResultPrice();
      receipt.executed_volume=m_trade.ResultVolume();
      if(sent && ExecutionRetcodeSuccess(receipt.retcode))
        {
         receipt.state=EXECUTION_SUBMIT_SENT;
         receipt.reason="ORDER_SENT";
         reason=receipt.reason;
         return true;
        }
      if(ExecutionRetcodeAmbiguous(receipt.retcode) &&
         ReconcileSignalPosition(plan,receipt,reason))
         return true;
      receipt.state=EXECUTION_SUBMIT_FAILED;
      receipt.reason="ORDER_SEND_FAILED:"+m_trade.ResultRetcodeDescription();
      reason=receipt.reason;
      return false;
     }

   bool DiscoverOwnedPositions(ManagedPosition &positions[],
                               bool &foreign_symbol_position,
                               bool &manual_intervention,
                               string &reason)
     {
      ArrayResize(positions,0);
      foreign_symbol_position=false;
      manual_intervention=false;
      if(!m_initialized)
        {
         reason="EXECUTION_BROKER_NOT_INITIALIZED";
         return false;
        }
      const string prefix="GE|"+m_profile.profile_id+"|";
      const int total=PositionsTotal();
      if(total<0)
        {
         reason="POSITIONS_TOTAL_INVALID";
         return false;
        }
      for(int index=0;index<total;index++)
        {
         const ulong ticket=PositionGetTicket(index);
         if(ticket==0 || !PositionSelectByTicket(ticket))
           {
            reason="POSITION_DISCOVERY_FAILED";
            return false;
           }
         if(PositionGetString(POSITION_SYMBOL)!=m_profile.symbol)
            continue;
         if(PositionGetInteger(POSITION_MAGIC)!=m_profile.magic)
           {
            foreign_symbol_position=true;
            continue;
           }
         const int count=ArraySize(positions);
         ArrayResize(positions,count+1);
         positions[count].ticket=ticket;
         positions[count].profile_id=m_profile.profile_id;
         positions[count].magic=PositionGetInteger(POSITION_MAGIC);
         positions[count].side=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ?
            ENGINE_SIDE_BUY : ENGINE_SIDE_SELL);
         positions[count].opened_at=(datetime)PositionGetInteger(POSITION_TIME);
         positions[count].volume=PositionGetDouble(POSITION_VOLUME);
         positions[count].entry_price=PositionGetDouble(POSITION_PRICE_OPEN);
         positions[count].stop_loss=PositionGetDouble(POSITION_SL);
         positions[count].take_profit=PositionGetDouble(POSITION_TP);
         positions[count].comment=PositionGetString(POSITION_COMMENT);
         positions[count].owned=StringFind(positions[count].comment,prefix)==0;
         if(!positions[count].owned)
            manual_intervention=true;
        }
      reason="OK";
      return true;
     }

   bool ModifyOwnedPosition(const ulong ticket,
                            const double stop_loss,
                            const double take_profit,
                            PositionActionReceipt &receipt,
                            string &reason)
     {
      ExecutionResetPositionReceipt(receipt);
      receipt.position_ticket=ticket;
      if(!m_initialized || !SelectOwnedPosition(ticket,reason))
        {
         receipt.state=POSITION_ACTION_REJECTED;
         receipt.reason=reason;
         return false;
        }
      if(!m_authority_enabled)
        {
         receipt.state=POSITION_ACTION_DISABLED;
         receipt.reason="ORDER_AUTHORITY_DISABLED";
         reason=receipt.reason;
         return false;
        }
      if(!ExecutionAligned(stop_loss,m_profile.tick_size) ||
         !ExecutionAligned(take_profit,m_profile.tick_size))
        {
         receipt.state=POSITION_ACTION_REJECTED;
         receipt.reason="POSITION_GEOMETRY_UNALIGNED";
         reason=receipt.reason;
         return false;
        }
      const bool sent=m_trade.PositionModify(ticket,stop_loss,take_profit);
      receipt.sent=sent;
      receipt.retcode=m_trade.ResultRetcode();
      if(sent && ExecutionRetcodeSuccess(receipt.retcode))
        {
         receipt.state=POSITION_ACTION_DONE;
         receipt.reason="POSITION_MODIFIED";
         reason=receipt.reason;
         return true;
        }
      receipt.state=POSITION_ACTION_FAILED;
      receipt.reason="POSITION_MODIFY_FAILED:"+m_trade.ResultRetcodeDescription();
      reason=receipt.reason;
      return false;
     }

   bool CloseOwnedPosition(const ulong ticket,
                           PositionActionReceipt &receipt,
                           string &reason)
     {
      ExecutionResetPositionReceipt(receipt);
      receipt.position_ticket=ticket;
      if(!m_initialized || !SelectOwnedPosition(ticket,reason))
        {
         receipt.state=POSITION_ACTION_REJECTED;
         receipt.reason=reason;
         return false;
        }
      if(!m_authority_enabled)
        {
         receipt.state=POSITION_ACTION_DISABLED;
         receipt.reason="ORDER_AUTHORITY_DISABLED";
         reason=receipt.reason;
         return false;
        }
      const bool sent=m_trade.PositionClose(ticket,(ulong)m_profile.deviation_points);
      receipt.sent=sent;
      receipt.retcode=m_trade.ResultRetcode();
      if(sent && ExecutionRetcodeSuccess(receipt.retcode))
        {
         receipt.state=POSITION_ACTION_DONE;
         receipt.reason="POSITION_CLOSED";
         reason=receipt.reason;
         return true;
        }
      receipt.state=POSITION_ACTION_FAILED;
      receipt.reason="POSITION_CLOSE_FAILED:"+m_trade.ResultRetcodeDescription();
      reason=receipt.reason;
      return false;
     }
  };

#endif
