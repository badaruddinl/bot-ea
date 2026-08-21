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
   EXECUTION_SUBMIT_FAILED=4
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

class CExecutionBroker
  {
private:
   ProfileConfig m_profile;
   CTrade        m_trade;
   bool          m_initialized;
   bool          m_authority_enabled;

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
      receipt.state=EXECUTION_SUBMIT_FAILED;
      receipt.reason="ORDER_SEND_FAILED:"+m_trade.ResultRetcodeDescription();
      reason=receipt.reason;
      return false;
     }
  };

#endif
