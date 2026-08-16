#property copyright "bot-ea"
#property version   "1.72"
#property strict
#property description "Signal-only parity backtester for HTF-aligned GOLD breakout-retest continuation."

#define SNIPER_STRATEGY_ID      "GOLDM_SNIPER_PARITY"
#define SNIPER_STRATEGY_VERSION "1.72"
#define GOLDM_PRODUCTION_INPUT_CONTRACT_SHA256 "fe3af5d9299c16c31d3c23ff84de1dffdb49d738fd961bc3450b85b3bfe2f800"
#define GOLDM_RUNTIME_SESSION_FILE "goldm_runtime_session.txt"
#define GOLDM_MIN_RESEARCH_RUN_ID_LENGTH 8
#define GOLDM_MIN_RUNTIME_SESSION_ID_LENGTH 16
#define GOLDM_MAX_RUN_ID_LENGTH 96

enum SetupSide
{
   SETUP_NONE = 0,
   SETUP_BUY  = 1,
   SETUP_SELL = -1
};

enum SetupPhase
{
   PHASE_SCANNING = 0,
   PHASE_WAITING_RETEST = 1,
   PHASE_WAITING_M5_TRIGGER = 2,
   PHASE_WAITING_M1_TRIGGER = 3
};

input string InpExpectedSymbol = "GOLD.i#";
input int    InpEmaContextFast = 50;
input int    InpEmaContextSlow = 200;
input int    InpATRPeriod = 14;
input int    InpRSIPeriod = 14;
input int    InpStochK = 14;
input int    InpStochD = 3;
input int    InpStochSlowing = 3;
input int    InpBollingerPeriod = 20;
input double InpBollingerDeviation = 2.0;
input double InpDojiMaximumBodyRatio = 0.20;
input int    InpFibonacciLookbackM15 = 24;
input double InpFibonacciTolerance = 0.06;
input int    InpMaximumFibonacciDelayBars = 1;
input double InpMaximumSpreadATR = 0.10;
input double InpMinimumATRRegimeRatio = 0.50;
input double InpMaximumATRRegimeRatio = 2.00;
input double InpMinimumBreakoutBody = 0.40;
input double InpMinimumBreakoutATR = 0.05;
input double InpMaximumBreakoutATR = 0.90;
input double InpMaximumBreakoutWick = 0.55;
input double InpMinimumRelativeTickVolume = 0.60;
input int    InpMaximumRetestBars = 12;
input double InpMaximumRetestDistanceATR = 0.35;
input double InpMaximumRetestPenetrationATR = 0.35;
input int    InpMaximumM5TriggerBars = 4;
input int    InpMaximumM1EntryBars = 5;
input int    InpM1RSIPeriod = 7;
input int    InpM1ManagementEMA = 9;
input double InpPost1RLockR = 0.25;
input double InpPost2RLockR = 1.00;
input double InpMaximumEntryDistanceATR = 0.60;
input double InpM15StructuralStopBufferATR = 0.05;
input double InpPsychologicalStep = 10.0;
input double InpMinimumProjectedR = 1.50;
input int    InpMinimumSetupScore = 70;
input int    InpOutcomeHorizonM15Bars = 96;
input int    InpSignalValidityMinutes = 5;
input int    InpTradeWindowStartMinute = 62;
input int    InpTradeWindowEndMinute = 1438;
input int    InpMinimumContextVotes = 2;
input int    InpMinimumM5ConfluenceVotes = 2;
input int    InpMaximumM5ConfluenceVotes = 5;
input bool   InpUseFibonacciConfluenceVote = true;
input bool   InpUseFibonacciScore = true;
input bool   InpUseFibonacciEntryDelay = true;
input bool   InpRequireIntradayVwapAlignment = false;
input bool   InpEnablePre1RAdverseExit = false;
input int    InpPre1RAdverseBars = 2;
input double InpPre1RAdverseThresholdR = 0.25;
input int    InpStrategyMode = 0;
input string InpResearchRunId = "";
input double InpM15ReversalRSIThreshold = 42.0;
input double InpM15ReversalStochThreshold = 30.0;
input double InpMinimumM15TrendSeparationATR = 0.0;
input double InpMinimumM15SlowSlopeATR = 0.0;
input bool   InpEnablePartialTake = false;
input double InpPartialTakeR = 0.50;
input double InpPartialFraction = 0.50;
input int    InpBreakoutChannelBars = 8;
input bool   InpEnableEarlyCandidateAlerts = true;
input double InpMinimumEarlyCandidateConfidence = 60.0;

int g_d1EmaFast = INVALID_HANDLE;
int g_h4EmaFast = INVALID_HANDLE;
int g_h4EmaSlow = INVALID_HANDLE;
int g_h1EmaFast = INVALID_HANDLE;
int g_h1EmaSlow = INVALID_HANDLE;
int g_m15Atr = INVALID_HANDLE;
int g_m15EmaFast = INVALID_HANDLE;
int g_m15EmaSlow = INVALID_HANDLE;
int g_m15Rsi = INVALID_HANDLE;
int g_m15Stoch = INVALID_HANDLE;
int g_m15Bands = INVALID_HANDLE;
int g_m5Rsi = INVALID_HANDLE;
int g_m5Stoch = INVALID_HANDLE;
int g_m5Bands = INVALID_HANDLE;
int g_m1Rsi = INVALID_HANDLE;
int g_m1Ema = INVALID_HANDLE;

SetupPhase g_phase = PHASE_SCANNING;
SetupSide g_side = SETUP_NONE;
double g_level = 0.0;
double g_breakoutAtr = 0.0;
datetime g_breakoutTime = 0;
int g_retestBars = 0;
double g_retestExtreme = 0.0;
int g_triggerBars = 0;
int g_m1EntryBars = 0;
bool g_m5StrongPattern = false;
bool g_m5StarPattern = false;
int g_m5ConfluenceVotes = 0;
int g_contextVotes = 0;
string g_m5PatternName = "NONE";
double g_breakoutBodyRatio = 0.0;
double g_breakoutDisplacementAtr = 0.0;
double g_breakoutWickRatio = 0.0;
double g_breakoutRelativeVolume = 0.0;
double g_fibImpulseStart = 0.0;
double g_fibImpulseEnd = 0.0;
string g_candidateId = "";
string g_candidateAccountScope = "unknown";
long g_candidateAccountLogin = 0;
string g_candidateServerB64 = "";
long g_candidateSetupUtcEpoch = 0;
bool g_earlyCandidateAlerted = false;
bool g_earlyCandidatePromoted = false;
int g_earlyCandidateConfidence = 0;

bool g_active = false;
string g_activeCandidateId = "";
string g_activeAccountScope = "unknown";
long g_activeAccountLogin = 0;
string g_activeServerB64 = "";
long g_activeSetupUtcEpoch = 0;
SetupSide g_activeSide = SETUP_NONE;
double g_entry = 0.0;
double g_stop = 0.0;
double g_risk = 0.0;
double g_target = 0.0;
double g_activeProjectedR = 0.0;
double g_activeFibReaction = 0.0;
datetime g_signalTime = 0;
bool g_hit1R = false;
bool g_hit2R = false;
bool g_hit3R = false;
bool g_partialTaken = false;
double g_realizedPartialR = 0.0;
double g_remainingPositionFraction = 1.0;
double g_activeMfeR = 0.0;
double g_activeMaeR = 0.0;
int g_m1AgainstBars = 0;

datetime g_lastM15Open = 0;
datetime g_lastM5Open = 0;
datetime g_lastM1Open = 0;
bool g_summaryPrinted = false;
string g_effectiveRunId = "UNSET";

long g_ticks = 0;
int g_breakouts = 0;
int g_contextRejects = 0;
int g_healthRejects = 0;
int g_retests = 0;
int g_invalidated = 0;
int g_retestExpired = 0;
int g_triggerExpired = 0;
int g_m1EntryExpired = 0;
int g_entryDistanceRejects = 0;
int g_triggerCandidates = 0;
int g_m5ConfluenceRejects = 0;
int g_m1FallbackEntries = 0;
int g_fibDelayedBars = 0;
int g_fibAlignedSignals = 0;
int g_roomRejects = 0;
int g_roomBelow2 = 0;
int g_roomWatch = 0;
int g_roomStrong = 0;
int g_roomAPlus = 0;
double g_roomCandidateTotalR = 0.0;
double g_roomCandidateMinimumR = DBL_MAX;
double g_roomCandidateMaximumR = 0.0;
int g_scoreRejects = 0;
int g_signals = 0;
int g_buySignals = 0;
int g_sellSignals = 0;
int g_earlyCandidateAlerts = 0;
int g_earlyCandidatePromotions = 0;
int g_earlyCandidateCancellations = 0;
int g_resolved = 0;
int g_oneR = 0;
int g_twoR = 0;
int g_threeR = 0;
int g_stopped = 0;
int g_protectedStops = 0;
int g_timedOut = 0;
int g_m1ManagedExits = 0;
double g_totalOutcomeR = 0.0;
double g_totalMfeR = 0.0;
double g_totalMaeR = 0.0;
double g_totalProjectedR = 0.0;
double g_totalScore = 0.0;

string EngineLineageProfile()
{
   // Protocol compatibility field only. The production strategy engine is
   // immutable and never filters BUY/SELL candidates inside the EA.
   return "ALL";
}

string ResearchRunId()
{
   return g_effectiveRunId;
}

string CurrentAccountScope()
{
   const ENUM_ACCOUNT_TRADE_MODE tradeMode =
      (ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(tradeMode == ACCOUNT_TRADE_MODE_DEMO)
      return "demo";
   if(tradeMode == ACCOUNT_TRADE_MODE_REAL)
      return "live";
   if(tradeMode == ACCOUNT_TRADE_MODE_CONTEST)
      return "contest";
   return "unknown";
}

string CurrentAccountServerB64()
{
   string server = AccountInfoString(ACCOUNT_SERVER);
   StringTrimLeft(server);
   StringTrimRight(server);
   if(StringLen(server) == 0)
      return "";

   uchar bytes[];
   const int copied = StringToCharArray(server, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   const int length = copied > 0 ? copied - 1 : 0;
   if(length <= 0)
      return "";

   const string alphabet =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
   string encoded = "";
   for(int index = 0; index < length; index += 3)
   {
      const int first = (int)bytes[index];
      const bool hasSecond = index + 1 < length;
      const bool hasThird = index + 2 < length;
      const int second = hasSecond ? (int)bytes[index + 1] : 0;
      const int third = hasThird ? (int)bytes[index + 2] : 0;
      encoded += StringSubstr(alphabet, first >> 2, 1);
      encoded += StringSubstr(alphabet, ((first & 3) << 4) | (second >> 4), 1);
      if(hasSecond)
         encoded += StringSubstr(alphabet, ((second & 15) << 2) | (third >> 6), 1);
      if(hasThird)
         encoded += StringSubstr(alphabet, third & 63, 1);
   }
   return encoded;
}

void CaptureCandidateAccountOrigin()
{
   g_candidateAccountScope = CurrentAccountScope();
   g_candidateAccountLogin = AccountInfoInteger(ACCOUNT_LOGIN);
   g_candidateServerB64 = CurrentAccountServerB64();
   // Freeze the complete setup lineage at candidate creation. Recomputing the
   // UTC epoch after a server/account/DST offset change would make later events
   // with the same setup id fail immutable identity validation.
   g_candidateSetupUtcEpoch = ServerTimeToUtcEpoch(g_breakoutTime);
}

bool IsStructuredToken(const string value)
{
   for(int index = 0; index < StringLen(value); index++)
   {
      const ushort character = StringGetCharacter(value, index);
      if(character <= 32 || character == '=')
         return false;
   }
   return true;
}

bool InitializeRunId()
{
   string value = "";
   const bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(tester)
   {
      value = InpResearchRunId;
   }
   else
   {
      ResetLastError();
      const int handle = FileOpen(
         GOLDM_RUNTIME_SESSION_FILE,
         FILE_READ | FILE_TXT | FILE_ANSI
      );
      if(handle == INVALID_HANDLE)
      {
         PrintFormat(
            "SNIPER_SESSION_ERROR reason=RUNTIME_SESSION_FILE_UNAVAILABLE file=%s error=%d",
            GOLDM_RUNTIME_SESSION_FILE,
            GetLastError()
         );
         return false;
      }
      value = FileReadString(handle);
      FileClose(handle);
      StringTrimLeft(value);
      StringTrimRight(value);
   }

   const int minimumLength = tester
      ? GOLDM_MIN_RESEARCH_RUN_ID_LENGTH
      : GOLDM_MIN_RUNTIME_SESSION_ID_LENGTH;
   const int length = StringLen(value);
   if(length < minimumLength || length > GOLDM_MAX_RUN_ID_LENGTH ||
      !IsStructuredToken(value))
   {
      PrintFormat(
         "SNIPER_SESSION_ERROR reason=INVALID_%s_SESSION length=%d",
         tester ? "RESEARCH" : "RUNTIME",
         length
      );
      return false;
   }
   g_effectiveRunId = value;
   return true;
}

int OnInit()
{
   if(_Symbol != InpExpectedSymbol)
   {
      PrintFormat("Sniper parity expected %s but tester symbol is %s", InpExpectedSymbol, _Symbol);
      return INIT_FAILED;
   }
   if(InpMaximumRetestBars <= 0 || InpMaximumM5TriggerBars <= 0 || InpMaximumM1EntryBars <= 0 ||
      InpOutcomeHorizonM15Bars <= 0 || InpSignalValidityMinutes <= 0 ||
      InpPsychologicalStep <= 0.0 ||
      InpBollingerPeriod <= 1 || InpBollingerDeviation <= 0.0 ||
      InpDojiMaximumBodyRatio <= 0.0 || InpDojiMaximumBodyRatio >= 1.0 ||
      InpFibonacciLookbackM15 < 3 || InpFibonacciTolerance <= 0.0 ||
      InpFibonacciTolerance >= 0.20 ||
      InpMaximumFibonacciDelayBars < 0 ||
      InpPost1RLockR < 0.0 || InpPost1RLockR >= 1.0 ||
      InpPost2RLockR < 1.0 || InpPost2RLockR >= 2.0 ||
      InpMaximumEntryDistanceATR <= 0.0 || InpM15StructuralStopBufferATR < 0.0 ||
      InpTradeWindowStartMinute < 0 || InpTradeWindowStartMinute > 1439 ||
      InpTradeWindowEndMinute < 0 || InpTradeWindowEndMinute > 1439 ||
      InpTradeWindowStartMinute > InpTradeWindowEndMinute ||
      InpMinimumContextVotes < 1 || InpMinimumContextVotes > 3 ||
      InpMinimumM5ConfluenceVotes < 1 || InpMinimumM5ConfluenceVotes > 5 ||
      InpMaximumM5ConfluenceVotes < InpMinimumM5ConfluenceVotes ||
      InpMaximumM5ConfluenceVotes > 5 || InpPre1RAdverseBars < 1 ||
      InpPre1RAdverseThresholdR <= 0.0 || InpPre1RAdverseThresholdR >= 1.0 ||
      InpStrategyMode < 0 || InpStrategyMode > 3 ||
      InpM15ReversalRSIThreshold <= 0.0 || InpM15ReversalRSIThreshold >= 50.0 ||
      InpM15ReversalStochThreshold <= 0.0 || InpM15ReversalStochThreshold >= 50.0 ||
      InpMinimumM15TrendSeparationATR < 0.0 ||
      InpMinimumM15SlowSlopeATR < 0.0 || InpPartialTakeR <= 0.0 ||
      InpPartialTakeR >= 1.0 || InpPartialFraction <= 0.0 || InpPartialFraction >= 1.0)
      return INIT_PARAMETERS_INCORRECT;
   if(InpBreakoutChannelBars < 2 || InpBreakoutChannelBars > 96)
      return INIT_PARAMETERS_INCORRECT;
   if(InpMinimumEarlyCandidateConfidence < 0.0 || InpMinimumEarlyCandidateConfidence >= 100.0)
      return INIT_PARAMETERS_INCORRECT;
   if(!InitializeRunId())
      return INIT_PARAMETERS_INCORRECT;

   g_d1EmaFast = iMA(_Symbol, PERIOD_D1, InpEmaContextFast, 0, MODE_EMA, PRICE_CLOSE);
   g_h4EmaFast = iMA(_Symbol, PERIOD_H4, InpEmaContextFast, 0, MODE_EMA, PRICE_CLOSE);
   g_h4EmaSlow = iMA(_Symbol, PERIOD_H4, InpEmaContextSlow, 0, MODE_EMA, PRICE_CLOSE);
   g_h1EmaFast = iMA(_Symbol, PERIOD_H1, InpEmaContextFast, 0, MODE_EMA, PRICE_CLOSE);
   g_h1EmaSlow = iMA(_Symbol, PERIOD_H1, InpEmaContextSlow, 0, MODE_EMA, PRICE_CLOSE);
   g_m15Atr = iATR(_Symbol, PERIOD_M15, InpATRPeriod);
   g_m15EmaFast = iMA(_Symbol, PERIOD_M15, InpEmaContextFast, 0, MODE_EMA, PRICE_CLOSE);
   g_m15EmaSlow = iMA(_Symbol, PERIOD_M15, InpEmaContextSlow, 0, MODE_EMA, PRICE_CLOSE);
   g_m15Rsi = iRSI(_Symbol, PERIOD_M15, InpRSIPeriod, PRICE_CLOSE);
   g_m15Stoch = iStochastic(
      _Symbol, PERIOD_M15, InpStochK, InpStochD, InpStochSlowing, MODE_SMA, STO_LOWHIGH
   );
   g_m15Bands = iBands(
      _Symbol, PERIOD_M15, InpBollingerPeriod, 0, InpBollingerDeviation, PRICE_CLOSE
   );
   g_m5Rsi = iRSI(_Symbol, PERIOD_M5, InpRSIPeriod, PRICE_CLOSE);
   g_m5Stoch = iStochastic(
      _Symbol, PERIOD_M5, InpStochK, InpStochD, InpStochSlowing, MODE_SMA, STO_LOWHIGH
   );
   g_m5Bands = iBands(
      _Symbol, PERIOD_M5, InpBollingerPeriod, 0, InpBollingerDeviation, PRICE_CLOSE
   );
   g_m1Rsi = iRSI(_Symbol, PERIOD_M1, InpM1RSIPeriod, PRICE_CLOSE);
   g_m1Ema = iMA(_Symbol, PERIOD_M1, InpM1ManagementEMA, 0, MODE_EMA, PRICE_CLOSE);

   if(g_d1EmaFast == INVALID_HANDLE || g_h4EmaFast == INVALID_HANDLE ||
      g_h4EmaSlow == INVALID_HANDLE || g_h1EmaFast == INVALID_HANDLE ||
      g_h1EmaSlow == INVALID_HANDLE || g_m15Atr == INVALID_HANDLE ||
      g_m15EmaFast == INVALID_HANDLE || g_m15EmaSlow == INVALID_HANDLE ||
      g_m15Rsi == INVALID_HANDLE || g_m15Stoch == INVALID_HANDLE ||
      g_m15Bands == INVALID_HANDLE ||
      g_m5Rsi == INVALID_HANDLE || g_m5Stoch == INVALID_HANDLE ||
      g_m5Bands == INVALID_HANDLE ||
      g_m1Rsi == INVALID_HANDLE || g_m1Ema == INVALID_HANDLE)
   {
      Print("Sniper parity failed to create indicator handles");
      return INIT_FAILED;
   }

   PrintFormat(
      "SNIPER_PRODUCTION_INPUTS schema=1 part=1/2 contractSha256=%s InpExpectedSymbol=%s InpEmaContextFast=%d InpEmaContextSlow=%d InpATRPeriod=%d InpRSIPeriod=%d InpStochK=%d InpStochD=%d InpStochSlowing=%d InpBollingerPeriod=%d InpBollingerDeviation=%.8f InpDojiMaximumBodyRatio=%.8f InpFibonacciLookbackM15=%d InpFibonacciTolerance=%.8f InpMaximumFibonacciDelayBars=%d InpMaximumSpreadATR=%.8f InpMinimumATRRegimeRatio=%.8f InpMaximumATRRegimeRatio=%.8f InpMinimumBreakoutBody=%.8f InpMinimumBreakoutATR=%.8f InpMaximumBreakoutATR=%.8f InpMaximumBreakoutWick=%.8f InpMinimumRelativeTickVolume=%.8f InpMaximumRetestBars=%d InpMaximumRetestDistanceATR=%.8f InpMaximumRetestPenetrationATR=%.8f InpMaximumM5TriggerBars=%d InpMaximumM1EntryBars=%d InpM1RSIPeriod=%d InpM1ManagementEMA=%d InpPost1RLockR=%.8f InpPost2RLockR=%.8f",
      GOLDM_PRODUCTION_INPUT_CONTRACT_SHA256,
      InpExpectedSymbol, InpEmaContextFast, InpEmaContextSlow, InpATRPeriod,
      InpRSIPeriod, InpStochK, InpStochD, InpStochSlowing,
      InpBollingerPeriod, InpBollingerDeviation, InpDojiMaximumBodyRatio,
      InpFibonacciLookbackM15, InpFibonacciTolerance,
      InpMaximumFibonacciDelayBars, InpMaximumSpreadATR,
      InpMinimumATRRegimeRatio, InpMaximumATRRegimeRatio,
      InpMinimumBreakoutBody, InpMinimumBreakoutATR,
      InpMaximumBreakoutATR, InpMaximumBreakoutWick,
      InpMinimumRelativeTickVolume, InpMaximumRetestBars,
      InpMaximumRetestDistanceATR, InpMaximumRetestPenetrationATR,
      InpMaximumM5TriggerBars, InpMaximumM1EntryBars, InpM1RSIPeriod,
      InpM1ManagementEMA, InpPost1RLockR, InpPost2RLockR
   );
   PrintFormat(
      "SNIPER_PRODUCTION_INPUTS schema=1 part=2/2 contractSha256=%s InpMaximumEntryDistanceATR=%.8f InpM15StructuralStopBufferATR=%.8f InpPsychologicalStep=%.8f InpMinimumProjectedR=%.8f InpMinimumSetupScore=%d InpOutcomeHorizonM15Bars=%d InpSignalValidityMinutes=%d InpTradeWindowStartMinute=%d InpTradeWindowEndMinute=%d InpMinimumContextVotes=%d InpMinimumM5ConfluenceVotes=%d InpMaximumM5ConfluenceVotes=%d InpUseFibonacciConfluenceVote=%s InpUseFibonacciScore=%s InpUseFibonacciEntryDelay=%s InpRequireIntradayVwapAlignment=%s InpEnablePre1RAdverseExit=%s InpPre1RAdverseBars=%d InpPre1RAdverseThresholdR=%.8f InpStrategyMode=%d InpM15ReversalRSIThreshold=%.8f InpM15ReversalStochThreshold=%.8f InpMinimumM15TrendSeparationATR=%.8f InpMinimumM15SlowSlopeATR=%.8f InpEnablePartialTake=%s InpPartialTakeR=%.8f InpPartialFraction=%.8f InpBreakoutChannelBars=%d InpEnableEarlyCandidateAlerts=%s InpMinimumEarlyCandidateConfidence=%.8f",
      GOLDM_PRODUCTION_INPUT_CONTRACT_SHA256,
      InpMaximumEntryDistanceATR, InpM15StructuralStopBufferATR,
      InpPsychologicalStep, InpMinimumProjectedR, InpMinimumSetupScore,
      InpOutcomeHorizonM15Bars, InpSignalValidityMinutes,
      InpTradeWindowStartMinute, InpTradeWindowEndMinute,
      InpMinimumContextVotes, InpMinimumM5ConfluenceVotes,
      InpMaximumM5ConfluenceVotes,
      InpUseFibonacciConfluenceVote ? "true" : "false",
      InpUseFibonacciScore ? "true" : "false",
      InpUseFibonacciEntryDelay ? "true" : "false",
      InpRequireIntradayVwapAlignment ? "true" : "false",
      InpEnablePre1RAdverseExit ? "true" : "false",
      InpPre1RAdverseBars, InpPre1RAdverseThresholdR, InpStrategyMode,
      InpM15ReversalRSIThreshold,
      InpM15ReversalStochThreshold, InpMinimumM15TrendSeparationATR,
      InpMinimumM15SlowSlopeATR,
      InpEnablePartialTake ? "true" : "false", InpPartialTakeR,
      InpPartialFraction, InpBreakoutChannelBars,
      InpEnableEarlyCandidateAlerts ? "true" : "false",
      InpMinimumEarlyCandidateConfidence
   );
   PrintFormat(
      "SNIPER_CONFIG symbol=%s strategy=%s strategyVersion=%s productionContractVersion=1 productionContractSha256=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s signalOnly=true level=PDH_PDL_PWH_PWL_H1_M15_PSYCH setupTF=M15 riskTF=M15 confirmTF=M5 refineTF=M1 RSI=%d STOCH=%d,%d,%d BB=%d,%.1f dojiRatio=%.2f FIB=23.6,38.2,50,61.8,78.6_EXT=127.2,161.8,200 lookback=%d tolerance=%.2f maxFibDelayM1=%d fibVote=%s fibScore=%s fibDelay=%s minM5Votes=%d maxM5Votes=%d minContextVotes=%d vwap=%s tradeWindow=%d-%d pre1RExit=%s,%d,%.2f strategyMode=%d channelBars=%d earlyAlert=%s,>%.1f reversalRSI=%.1f reversalStoch=%.1f trendSepATR=%.2f slowSlopeATR=%.2f partial=%s,%.2f,%.2f post1RLock=%.2f post2RLock=%.2f maxRetestBars=%d maxEntryDistanceATR=%.2f structuralStopBufferATR=%.2f minProjectedR=%.2f score=%d outcomeHorizonM15=%d signalValidityMinutes=%d",
      _Symbol, SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
      GOLDM_PRODUCTION_INPUT_CONTRACT_SHA256, EngineLineageProfile(), ResearchRunId(),
      CurrentAccountScope(), AccountInfoInteger(ACCOUNT_LOGIN),
      CurrentAccountServerB64(),
      InpRSIPeriod, InpStochK, InpStochD, InpStochSlowing,
      InpBollingerPeriod, InpBollingerDeviation, InpDojiMaximumBodyRatio,
      InpFibonacciLookbackM15, InpFibonacciTolerance, InpMaximumFibonacciDelayBars,
      InpUseFibonacciConfluenceVote ? "true" : "false",
      InpUseFibonacciScore ? "true" : "false",
      InpUseFibonacciEntryDelay ? "true" : "false",
      InpMinimumM5ConfluenceVotes, InpMaximumM5ConfluenceVotes,
      InpMinimumContextVotes,
      InpRequireIntradayVwapAlignment ? "true" : "false",
      InpTradeWindowStartMinute, InpTradeWindowEndMinute,
      InpEnablePre1RAdverseExit ? "true" : "false",
      InpPre1RAdverseBars, InpPre1RAdverseThresholdR,
      InpStrategyMode, InpBreakoutChannelBars,
      InpEnableEarlyCandidateAlerts ? "true" : "false",
      InpMinimumEarlyCandidateConfidence,
      InpM15ReversalRSIThreshold, InpM15ReversalStochThreshold,
      InpMinimumM15TrendSeparationATR, InpMinimumM15SlowSlopeATR,
      InpEnablePartialTake ? "true" : "false", InpPartialTakeR, InpPartialFraction,
      InpPost1RLockR, InpPost2RLockR,
      InpMaximumRetestBars, InpMaximumEntryDistanceATR,
      InpM15StructuralStopBufferATR, InpMinimumProjectedR, InpMinimumSetupScore,
      InpOutcomeHorizonM15Bars, InpSignalValidityMinutes
   );
   PrintFormat(
      "SNIPER_SYMBOL accountScope=%s accountLogin=%I64d originServerB64=%s minLot=%.4f maxLot=%.4f lotStep=%.4f contract=%.2f tickSize=%.5f tickValue=%.5f point=%.5f stops=%d",
      CurrentAccountScope(), AccountInfoInteger(ACCOUNT_LOGIN),
      CurrentAccountServerB64(),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE),
      SymbolInfoDouble(_Symbol, SYMBOL_POINT),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL)
   );
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(!g_summaryPrinted)
   {
      FinalizeOpenSignalAtMarket();
      PrintSummary();
   }
   ReleaseHandle(g_d1EmaFast);
   ReleaseHandle(g_h4EmaFast);
   ReleaseHandle(g_h4EmaSlow);
   ReleaseHandle(g_h1EmaFast);
   ReleaseHandle(g_h1EmaSlow);
   ReleaseHandle(g_m15Atr);
   ReleaseHandle(g_m15EmaFast);
   ReleaseHandle(g_m15EmaSlow);
   ReleaseHandle(g_m15Rsi);
   ReleaseHandle(g_m15Stoch);
   ReleaseHandle(g_m15Bands);
   ReleaseHandle(g_m5Rsi);
   ReleaseHandle(g_m5Stoch);
   ReleaseHandle(g_m5Bands);
   ReleaseHandle(g_m1Rsi);
   ReleaseHandle(g_m1Ema);
}

void OnTick()
{
   g_ticks++;
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   UpdateActiveSignal(tick);

   const datetime m15Open = iTime(_Symbol, PERIOD_M15, 0);
   if(m15Open > 0 && m15Open != g_lastM15Open)
   {
      g_lastM15Open = m15Open;
      ProcessClosedM15();
   }

   const datetime m5Open = iTime(_Symbol, PERIOD_M5, 0);
   if(m5Open > 0 && m5Open != g_lastM5Open)
   {
      g_lastM5Open = m5Open;
      ProcessClosedM5(tick);
   }

   const datetime m1Open = iTime(_Symbol, PERIOD_M1, 0);
   if(m1Open > 0 && m1Open != g_lastM1Open)
   {
      g_lastM1Open = m1Open;
      ProcessClosedM1(tick);
   }
}

double OnTester()
{
   FinalizeOpenSignalAtMarket();
   PrintSummary();
   g_summaryPrinted = true;
   if(g_resolved <= 0)
      return -999.0;
   return g_totalOutcomeR / g_resolved;
}

void ProcessClosedM15()
{
   if(g_active)
      return;

   const datetime closedBarEnd = iTime(_Symbol, PERIOD_M15, 1) + PeriodSeconds(PERIOD_M15);
   if(!IsConfiguredTradeWindow(closedBarEnd))
   {
      if(g_phase != PHASE_SCANNING)
         ResetSetup("OUTSIDE_TRADE_WINDOW");
      return;
   }

   const double atr = IndicatorValue(g_m15Atr, 0, 1);
   if(atr <= 0.0)
   {
      g_healthRejects++;
      return;
   }

   if(g_phase == PHASE_WAITING_RETEST)
   {
      ProcessRetest(atr);
      return;
   }
   if(g_phase == PHASE_WAITING_M5_TRIGGER || g_phase == PHASE_WAITING_M1_TRIGGER)
   {
      ValidatePendingSetupOnM15(atr);
      return;
   }

   if(InpStrategyMode == 3)
      DetectChannelBreakout(atr);
   else if(InpStrategyMode == 2)
      DetectM15VwapPullback(atr);
   else if(InpStrategyMode == 1)
      DetectM15Reversal(atr);
   else
      DetectBreakout(atr);
}

void DetectM15Reversal(const double atr)
{
   if(!HealthyMarket(atr))
   {
      g_healthRejects++;
      return;
   }

   const double open = iOpen(_Symbol, PERIOD_M15, 1);
   const double high = iHigh(_Symbol, PERIOD_M15, 1);
   const double low = iLow(_Symbol, PERIOD_M15, 1);
   const double close = iClose(_Symbol, PERIOD_M15, 1);
   const double range = high - low;
   const double rsi = IndicatorValue(g_m15Rsi, 0, 1);
   const double stochK = IndicatorValue(g_m15Stoch, 0, 1);
   const double upperBand = IndicatorValue(g_m15Bands, 1, 1);
   const double lowerBand = IndicatorValue(g_m15Bands, 2, 1);
   if(range <= 0.0 || rsi <= 0.0 || stochK <= 0.0 ||
      upperBand <= 0.0 || lowerBand <= 0.0)
      return;

   const bool morningStar = IsMorningDojiStar(PERIOD_M15);
   const bool eveningStar = IsEveningDojiStar(PERIOD_M15);
   const bool buyReclaim = low <= lowerBand && close > lowerBand;
   const bool sellReclaim = high >= upperBand && close < upperBand;
   const bool buyOscillator = rsi <= InpM15ReversalRSIThreshold ||
      stochK <= InpM15ReversalStochThreshold;
   const bool sellOscillator = rsi >= 100.0 - InpM15ReversalRSIThreshold ||
      stochK >= 100.0 - InpM15ReversalStochThreshold;

   SetupSide candidate = SETUP_NONE;
   double level = 0.0;
   bool starPattern = false;
   if(buyReclaim && buyOscillator && (close > open || morningStar))
   {
      candidate = SETUP_BUY;
      level = lowerBand;
      starPattern = morningStar;
   }
   else if(sellReclaim && sellOscillator && (close < open || eveningStar))
   {
      candidate = SETUP_SELL;
      level = upperBand;
      starPattern = eveningStar;
   }
   else
      return;

   if(!ContextAligned(candidate))
   {
      g_contextRejects++;
      return;
   }
   if(InpRequireIntradayVwapAlignment && !IntradayVwapAligned(candidate, close, 1))
   {
      g_contextRejects++;
      return;
   }

   g_breakouts++;
   g_retests++;
   g_phase = PHASE_WAITING_M5_TRIGGER;
   g_side = candidate;
   g_level = level;
   g_breakoutAtr = atr;
   g_breakoutBodyRatio = MathAbs(close - open) / range;
   g_breakoutDisplacementAtr = MathAbs(close - level) / atr;
   g_breakoutWickRatio = candidate == SETUP_BUY
      ? (MathMin(open, close) - low) / range
      : (high - MathMax(open, close)) / range;
   g_breakoutRelativeVolume = RelativeTickVolume(PERIOD_M15, 1, 20);
   BuildReversalFibonacciImpulse(candidate, high, low);
   g_breakoutTime = iTime(_Symbol, PERIOD_M15, 1);
   g_retestBars = 1;
   g_retestExtreme = candidate == SETUP_BUY ? low : high;
   g_triggerBars = 0;
   g_m5StarPattern = starPattern;
}

void DetectM15VwapPullback(const double atr)
{
   if(!HealthyMarket(atr))
   {
      g_healthRejects++;
      return;
   }

   const double open = iOpen(_Symbol, PERIOD_M15, 1);
   const double high = iHigh(_Symbol, PERIOD_M15, 1);
   const double low = iLow(_Symbol, PERIOD_M15, 1);
   const double close = iClose(_Symbol, PERIOD_M15, 1);
   const double range = high - low;
   const double emaFast = IndicatorValue(g_m15EmaFast, 0, 1);
   const double emaSlow = IndicatorValue(g_m15EmaSlow, 0, 1);
   const double emaSlowPrevious = IndicatorValue(g_m15EmaSlow, 0, 9);
   const double vwap = IntradayVwapValue(1);
   const double rsi = IndicatorValue(g_m15Rsi, 0, 1);
   const double stochK = IndicatorValue(g_m15Stoch, 0, 1);
   const double stochD = IndicatorValue(g_m15Stoch, 1, 1);
   const double bandMiddle = IndicatorValue(g_m15Bands, 0, 1);
   if(range <= 0.0 || emaFast <= 0.0 || emaSlow <= 0.0 || emaSlowPrevious <= 0.0 ||
      vwap <= 0.0 ||
      rsi <= 0.0 || stochK <= 0.0 || stochD <= 0.0 || bandMiddle <= 0.0)
      return;

   const bool morningStar = IsMorningDojiStar(PERIOD_M15);
   const bool eveningStar = IsEveningDojiStar(PERIOD_M15);
   const double trendSeparationAtr = MathAbs(emaFast - emaSlow) / atr;
   const double slowSlopeAtr = (emaSlow - emaSlowPrevious) / atr;
   const bool trendSeparationOk = trendSeparationAtr >= InpMinimumM15TrendSeparationATR;
   const bool buySlopeOk = InpMinimumM15SlowSlopeATR <= 0.0 ||
      slowSlopeAtr >= InpMinimumM15SlowSlopeATR;
   const bool sellSlopeOk = InpMinimumM15SlowSlopeATR <= 0.0 ||
      slowSlopeAtr <= -InpMinimumM15SlowSlopeATR;
   const bool buyRegime = trendSeparationOk && buySlopeOk &&
      emaFast > emaSlow && close > emaSlow && close >= vwap;
   const bool sellRegime = trendSeparationOk && sellSlopeOk &&
      emaFast < emaSlow && close < emaSlow && close <= vwap;
   const bool buyPullback = low <= emaFast + 0.10 * atr && close >= emaFast;
   const bool sellPullback = high >= emaFast - 0.10 * atr && close <= emaFast;
   const bool buyIndicatorEvidence = rsi >= 50.0 || stochK >= stochD || close >= bandMiddle;
   const bool sellIndicatorEvidence = rsi <= 50.0 || stochK <= stochD || close <= bandMiddle;

   SetupSide candidate = SETUP_NONE;
   bool starPattern = false;
   if(buyRegime && buyPullback && buyIndicatorEvidence && (close > open || morningStar))
   {
      candidate = SETUP_BUY;
      starPattern = morningStar;
   }
   else if(sellRegime && sellPullback && sellIndicatorEvidence && (close < open || eveningStar))
   {
      candidate = SETUP_SELL;
      starPattern = eveningStar;
   }
   else
      return;

   if(!ContextAligned(candidate))
   {
      g_contextRejects++;
      return;
   }

   g_breakouts++;
   g_retests++;
   g_phase = PHASE_WAITING_M5_TRIGGER;
   g_side = candidate;
   g_level = emaFast;
   g_breakoutAtr = atr;
   g_breakoutBodyRatio = MathAbs(close - open) / range;
   g_breakoutDisplacementAtr = MathAbs(close - emaFast) / atr;
   g_breakoutWickRatio = candidate == SETUP_BUY
      ? (MathMin(open, close) - low) / range
      : (high - MathMax(open, close)) / range;
   g_breakoutRelativeVolume = RelativeTickVolume(PERIOD_M15, 1, 20);
   BuildFibonacciImpulse(candidate, high, low);
   g_breakoutTime = iTime(_Symbol, PERIOD_M15, 1);
   g_retestBars = 1;
   g_retestExtreme = candidate == SETUP_BUY ? low : high;
   g_triggerBars = 0;
   g_m5StarPattern = starPattern;
}

void BuildReversalFibonacciImpulse(
   const SetupSide side,
   const double signalHigh,
   const double signalLow
)
{
   if(side == SETUP_BUY)
   {
      g_fibImpulseStart = signalLow;
      g_fibImpulseEnd = signalHigh;
      for(int shift = 2; shift <= InpFibonacciLookbackM15 + 1; shift++)
      {
         g_fibImpulseStart = MathMin(g_fibImpulseStart, iLow(_Symbol, PERIOD_M15, shift));
         g_fibImpulseEnd = MathMax(g_fibImpulseEnd, iHigh(_Symbol, PERIOD_M15, shift));
      }
   }
   else
   {
      g_fibImpulseStart = signalHigh;
      g_fibImpulseEnd = signalLow;
      for(int shift = 2; shift <= InpFibonacciLookbackM15 + 1; shift++)
      {
         g_fibImpulseStart = MathMax(g_fibImpulseStart, iHigh(_Symbol, PERIOD_M15, shift));
         g_fibImpulseEnd = MathMin(g_fibImpulseEnd, iLow(_Symbol, PERIOD_M15, shift));
      }
   }
}

void DetectBreakout(const double atr)
{
   if(!IsConfiguredTradeWindow(iTime(_Symbol, PERIOD_M15, 1) + PeriodSeconds(PERIOD_M15)))
      return;
   if(!HealthyMarket(atr))
   {
      g_healthRejects++;
      return;
   }

   const double open = iOpen(_Symbol, PERIOD_M15, 1);
   const double high = iHigh(_Symbol, PERIOD_M15, 1);
   const double low = iLow(_Symbol, PERIOD_M15, 1);
   const double close = iClose(_Symbol, PERIOD_M15, 1);
   const double range = high - low;
   if(range <= 0.0)
      return;

   const double bodyRatio = MathAbs(close - open) / range;
   if(bodyRatio < InpMinimumBreakoutBody)
      return;
   const double relativeVolume = RelativeTickVolume(PERIOD_M15, 1, 20);
   if(relativeVolume < InpMinimumRelativeTickVolume)
      return;

   SetupSide candidate = SETUP_NONE;
   double level = 0.0;
   double displacement = 0.0;
   double wickRatio = 1.0;

   if(close > open && FindCrossedKeyLevel(SETUP_BUY, open, close, level))
   {
      candidate = SETUP_BUY;
      displacement = (close - level) / atr;
      wickRatio = (high - close) / range;
   }
   else if(close < open && FindCrossedKeyLevel(SETUP_SELL, open, close, level))
   {
      candidate = SETUP_SELL;
      displacement = (level - close) / atr;
      wickRatio = (close - low) / range;
   }
   else
      return;

   if(displacement < InpMinimumBreakoutATR || displacement > InpMaximumBreakoutATR ||
      wickRatio > InpMaximumBreakoutWick)
      return;

   if(!ContextAligned(candidate))
   {
      g_contextRejects++;
      return;
   }
   if(InpRequireIntradayVwapAlignment && !IntradayVwapAligned(candidate, close, 1))
   {
      g_contextRejects++;
      return;
   }

   g_breakouts++;
   g_phase = PHASE_WAITING_RETEST;
   g_side = candidate;
   g_level = level;
   g_breakoutAtr = atr;
   g_breakoutBodyRatio = bodyRatio;
   g_breakoutDisplacementAtr = displacement;
   g_breakoutWickRatio = wickRatio;
   g_breakoutRelativeVolume = relativeVolume;
   BuildFibonacciImpulse(candidate, high, low);
   g_breakoutTime = iTime(_Symbol, PERIOD_M15, 1);
   g_retestBars = 0;
   g_retestExtreme = candidate == SETUP_BUY ? DBL_MAX : -DBL_MAX;
}

void DetectChannelBreakout(const double atr)
{
   if(!HealthyMarket(atr))
   {
      g_healthRejects++;
      return;
   }

   const double open = iOpen(_Symbol, PERIOD_M15, 1);
   const double high = iHigh(_Symbol, PERIOD_M15, 1);
   const double low = iLow(_Symbol, PERIOD_M15, 1);
   const double close = iClose(_Symbol, PERIOD_M15, 1);
   const double range = high - low;
   if(range <= 0.0)
      return;
   const double bodyRatio = MathAbs(close - open) / range;
   if(bodyRatio < InpMinimumBreakoutBody)
      return;
   const double relativeVolume = RelativeTickVolume(PERIOD_M15, 1, 20);
   if(relativeVolume < InpMinimumRelativeTickVolume)
      return;

   double channelHigh = -DBL_MAX;
   double channelLow = DBL_MAX;
   for(int shift = 2; shift <= InpBreakoutChannelBars + 1; shift++)
   {
      channelHigh = MathMax(channelHigh, iHigh(_Symbol, PERIOD_M15, shift));
      channelLow = MathMin(channelLow, iLow(_Symbol, PERIOD_M15, shift));
   }

   SetupSide candidate = SETUP_NONE;
   double level = 0.0;
   double displacement = 0.0;
   double wickRatio = 1.0;
   if(open <= channelHigh && close > channelHigh)
   {
      candidate = SETUP_BUY;
      level = channelHigh;
      displacement = (close - level) / atr;
      wickRatio = (high - close) / range;
   }
   else if(open >= channelLow && close < channelLow)
   {
      candidate = SETUP_SELL;
      level = channelLow;
      displacement = (level - close) / atr;
      wickRatio = (close - low) / range;
   }
   else
      return;

   if(displacement < InpMinimumBreakoutATR || displacement > InpMaximumBreakoutATR ||
      wickRatio > InpMaximumBreakoutWick)
      return;
   if(!ContextAligned(candidate))
   {
      g_contextRejects++;
      return;
   }
   if(InpRequireIntradayVwapAlignment && !IntradayVwapAligned(candidate, close, 1))
   {
      g_contextRejects++;
      return;
   }

   g_breakouts++;
   g_phase = PHASE_WAITING_RETEST;
   g_side = candidate;
   g_level = level;
   g_breakoutAtr = atr;
   g_breakoutBodyRatio = bodyRatio;
   g_breakoutDisplacementAtr = displacement;
   g_breakoutWickRatio = wickRatio;
   g_breakoutRelativeVolume = relativeVolume;
   BuildFibonacciImpulse(candidate, high, low);
   g_breakoutTime = iTime(_Symbol, PERIOD_M15, 1);
   g_retestBars = 0;
   g_retestExtreme = candidate == SETUP_BUY ? DBL_MAX : -DBL_MAX;
}

void BuildFibonacciImpulse(
   const SetupSide side,
   const double breakoutHigh,
   const double breakoutLow
)
{
   if(side == SETUP_BUY)
   {
      g_fibImpulseStart = DBL_MAX;
      for(int shift = 2; shift <= InpFibonacciLookbackM15 + 1; shift++)
         g_fibImpulseStart = MathMin(g_fibImpulseStart, iLow(_Symbol, PERIOD_M15, shift));
      g_fibImpulseEnd = breakoutHigh;
   }
   else
   {
      g_fibImpulseStart = -DBL_MAX;
      for(int shift = 2; shift <= InpFibonacciLookbackM15 + 1; shift++)
         g_fibImpulseStart = MathMax(g_fibImpulseStart, iHigh(_Symbol, PERIOD_M15, shift));
      g_fibImpulseEnd = breakoutLow;
   }
}

bool FibonacciRetracementAligned(const SetupSide side, const double price)
{
   const double range = side == SETUP_BUY
      ? g_fibImpulseEnd - g_fibImpulseStart
      : g_fibImpulseStart - g_fibImpulseEnd;
   if(range <= 0.0)
      return false;
   const double retracement = side == SETUP_BUY
      ? (g_fibImpulseEnd - price) / range
      : (price - g_fibImpulseEnd) / range;
   const double levels[5] = {0.236, 0.382, 0.500, 0.618, 0.786};
   for(int i = 0; i < 5; i++)
   {
      if(MathAbs(retracement - levels[i]) <= InpFibonacciTolerance)
         return true;
   }
   return false;
}

double NearestFibonacciExtension(const SetupSide side, const double entry)
{
   const double range = side == SETUP_BUY
      ? g_fibImpulseEnd - g_fibImpulseStart
      : g_fibImpulseStart - g_fibImpulseEnd;
   if(range <= 0.0)
      return 0.0;
   double nearest = side == SETUP_BUY ? DBL_MAX : -DBL_MAX;
   const double extensions[3] = {1.272, 1.618, 2.000};
   for(int i = 0; i < 3; i++)
   {
      const double value = side == SETUP_BUY
         ? g_fibImpulseStart + extensions[i] * range
         : g_fibImpulseStart - extensions[i] * range;
      if(side == SETUP_BUY && value > entry && value < nearest) nearest = value;
      if(side == SETUP_SELL && value < entry && value > nearest) nearest = value;
   }
   if(nearest == DBL_MAX || nearest == -DBL_MAX)
      return 0.0;
   return nearest;
}

bool FindCrossedKeyLevel(
   const SetupSide side,
   const double open,
   const double close,
   double &selected
)
{
   selected = side == SETUP_BUY ? -DBL_MAX : DBL_MAX;
   if(side == SETUP_BUY)
   {
      ConsiderCrossedLevel(side, open, close, iHigh(_Symbol, PERIOD_D1, 1), selected);
      ConsiderCrossedLevel(side, open, close, iHigh(_Symbol, PERIOD_W1, 1), selected);
   }
   else
   {
      ConsiderCrossedLevel(side, open, close, iLow(_Symbol, PERIOD_D1, 1), selected);
      ConsiderCrossedLevel(side, open, close, iLow(_Symbol, PERIOD_W1, 1), selected);
   }

   for(int shift = 3; shift <= 48; shift++)
   {
      if(side == SETUP_BUY)
      {
         const double high = iHigh(_Symbol, PERIOD_H1, shift);
         if(high > iHigh(_Symbol, PERIOD_H1, shift + 1) &&
            high > iHigh(_Symbol, PERIOD_H1, shift - 1))
            ConsiderCrossedLevel(side, open, close, high, selected);
      }
      else
      {
         const double low = iLow(_Symbol, PERIOD_H1, shift);
         if(low < iLow(_Symbol, PERIOD_H1, shift + 1) &&
            low < iLow(_Symbol, PERIOD_H1, shift - 1))
            ConsiderCrossedLevel(side, open, close, low, selected);
      }
   }

   for(int shift = 3; shift <= 96; shift++)
   {
      if(side == SETUP_BUY)
      {
         const double high = iHigh(_Symbol, PERIOD_M15, shift);
         if(high > iHigh(_Symbol, PERIOD_M15, shift + 1) &&
            high > iHigh(_Symbol, PERIOD_M15, shift - 1))
            ConsiderCrossedLevel(side, open, close, high, selected);
      }
      else
      {
         const double low = iLow(_Symbol, PERIOD_M15, shift);
         if(low < iLow(_Symbol, PERIOD_M15, shift + 1) &&
            low < iLow(_Symbol, PERIOD_M15, shift - 1))
            ConsiderCrossedLevel(side, open, close, low, selected);
      }
   }

   double psychological = 0.0;
   if(side == SETUP_BUY)
      psychological = MathFloor(close / InpPsychologicalStep) * InpPsychologicalStep;
   else
      psychological = MathCeil(close / InpPsychologicalStep) * InpPsychologicalStep;
   ConsiderCrossedLevel(side, open, close, psychological, selected);

   return side == SETUP_BUY ? selected > -DBL_MAX : selected < DBL_MAX;
}

void ConsiderCrossedLevel(
   const SetupSide side,
   const double open,
   const double close,
   const double candidate,
   double &selected
)
{
   if(candidate <= 0.0)
      return;
   if(side == SETUP_BUY && open <= candidate && close > candidate && candidate > selected)
      selected = candidate;
   if(side == SETUP_SELL && open >= candidate && close < candidate && candidate < selected)
      selected = candidate;
}

void ProcessRetest(const double currentAtr)
{
   g_retestBars++;
   const double high = iHigh(_Symbol, PERIOD_M15, 1);
   const double low = iLow(_Symbol, PERIOD_M15, 1);
   const double close = iClose(_Symbol, PERIOD_M15, 1);
   const double atr = g_breakoutAtr > 0.0 ? g_breakoutAtr : currentAtr;

   if(g_side == SETUP_BUY)
   {
      if(close < g_level - InpMaximumRetestPenetrationATR * atr)
      {
         g_invalidated++;
         ResetSetup("M15_RETEST_INVALIDATED");
         return;
      }
      const bool approached = low <= g_level + InpMaximumRetestDistanceATR * atr;
      const bool penetrationOk = low >= g_level - InpMaximumRetestPenetrationATR * atr;
      if(approached && penetrationOk && close >= g_level)
      {
         g_retestExtreme = low;
         AcceptRetest();
         return;
      }
   }
   else if(g_side == SETUP_SELL)
   {
      if(close > g_level + InpMaximumRetestPenetrationATR * atr)
      {
         g_invalidated++;
         ResetSetup("M15_RETEST_INVALIDATED");
         return;
      }
      const bool approached = high >= g_level - InpMaximumRetestDistanceATR * atr;
      const bool penetrationOk = high <= g_level + InpMaximumRetestPenetrationATR * atr;
      if(approached && penetrationOk && close <= g_level)
      {
         g_retestExtreme = high;
         AcceptRetest();
         return;
      }
   }

   if(g_retestBars >= InpMaximumRetestBars)
   {
      g_retestExpired++;
      ResetSetup("RETEST_EXPIRED");
   }
}

void AcceptRetest()
{
   g_retests++;
   g_phase = PHASE_WAITING_M5_TRIGGER;
   g_triggerBars = 0;
}

void ValidatePendingSetupOnM15(const double currentAtr)
{
   const double atr = currentAtr > 0.0 ? currentAtr : g_breakoutAtr;
   const double close = iClose(_Symbol, PERIOD_M15, 1);
   const bool invalidated = g_side == SETUP_BUY
      ? close < g_level - InpMaximumRetestPenetrationATR * atr
      : close > g_level + InpMaximumRetestPenetrationATR * atr;
   if(invalidated)
   {
      g_invalidated++;
      ResetSetup("M15_PENDING_INVALIDATED");
   }
}

void ProcessClosedM5(const MqlTick &tick)
{
   if(g_active || g_phase != PHASE_WAITING_M5_TRIGGER)
      return;

   g_triggerBars++;
   const double open1 = iOpen(_Symbol, PERIOD_M5, 1);
   const double high1 = iHigh(_Symbol, PERIOD_M5, 1);
   const double low1 = iLow(_Symbol, PERIOD_M5, 1);
   const double close1 = iClose(_Symbol, PERIOD_M5, 1);
   const double open2 = iOpen(_Symbol, PERIOD_M5, 2);
   const double high2 = iHigh(_Symbol, PERIOD_M5, 2);
   const double low2 = iLow(_Symbol, PERIOD_M5, 2);
   const double close2 = iClose(_Symbol, PERIOD_M5, 2);
   const double body = MathAbs(close1 - open1);
   const double rsi1 = IndicatorValue(g_m5Rsi, 0, 1);
   const double rsi2 = IndicatorValue(g_m5Rsi, 0, 2);
   const double stochK1 = IndicatorValue(g_m5Stoch, 0, 1);
   const double stochK2 = IndicatorValue(g_m5Stoch, 0, 2);
   const double stochD1 = IndicatorValue(g_m5Stoch, 1, 1);
   const double stochD2 = IndicatorValue(g_m5Stoch, 1, 2);
   const double bandMiddle1 = IndicatorValue(g_m5Bands, 0, 1);
   const double bandUpper1 = IndicatorValue(g_m5Bands, 1, 1);
   const double bandLower1 = IndicatorValue(g_m5Bands, 2, 1);

   bool trigger = false;
   bool strongPattern = false;
   bool starPattern = false;
   bool priceAction = false;
   bool rsiEvidence = false;
   bool stochEvidence = false;
   bool bollingerEvidence = false;
   const bool fibonacciEvidence = FibonacciRetracementAligned(g_side, close1);
   string patternName = "NONE";
   if(g_side == SETUP_BUY)
   {
      const bool rejection = close1 > open1 && (open1 - low1) >= body * 0.50;
      const bool engulfing = close1 > open1 && close2 < open2 && close1 >= open2 && open1 <= close2;
      const bool microBreak = close1 > high2;
      starPattern = IsMorningDojiStar(PERIOD_M5);
      priceAction = rejection || engulfing || microBreak || starPattern;
      rsiEvidence = rsi1 >= 48.0 || (rsi2 <= 40.0 && rsi1 > rsi2);
      stochEvidence = stochK1 >= stochD1 ||
         (stochK2 <= 30.0 && stochK1 > stochK2 && stochD1 >= stochD2);
      bollingerEvidence = (low1 <= bandLower1 && close1 > bandLower1) ||
         (close2 <= bandMiddle1 && close1 > bandMiddle1);
      strongPattern = rejection || engulfing || starPattern;
      if(starPattern) patternName = "MORNING_DOJI_STAR";
      else if(engulfing) patternName = "BULL_ENGULFING";
      else if(rejection) patternName = "BULL_REJECTION";
      else if(microBreak) patternName = "BULL_MICRO_BREAK";
   }
   else if(g_side == SETUP_SELL)
   {
      const bool rejection = close1 < open1 && (high1 - open1) >= body * 0.50;
      const bool engulfing = close1 < open1 && close2 > open2 && close1 <= open2 && open1 >= close2;
      const bool microBreak = close1 < low2;
      starPattern = IsEveningDojiStar(PERIOD_M5);
      priceAction = rejection || engulfing || microBreak || starPattern;
      rsiEvidence = rsi1 <= 52.0 || (rsi2 >= 60.0 && rsi1 < rsi2);
      stochEvidence = stochK1 <= stochD1 ||
         (stochK2 >= 70.0 && stochK1 < stochK2 && stochD1 <= stochD2);
      bollingerEvidence = (high1 >= bandUpper1 && close1 < bandUpper1) ||
         (close2 >= bandMiddle1 && close1 < bandMiddle1);
      strongPattern = rejection || engulfing || starPattern;
      if(starPattern) patternName = "EVENING_DOJI_STAR";
      else if(engulfing) patternName = "BEAR_ENGULFING";
      else if(rejection) patternName = "BEAR_REJECTION";
      else if(microBreak) patternName = "BEAR_MICRO_BREAK";
   }

   const int confluenceVotes = (priceAction ? 1 : 0) + (rsiEvidence ? 1 : 0) +
      (stochEvidence ? 1 : 0) + (bollingerEvidence ? 1 : 0) +
      (InpUseFibonacciConfluenceVote && fibonacciEvidence ? 1 : 0);
   const bool anchoredEvidence = priceAction || bollingerEvidence ||
      (InpUseFibonacciConfluenceVote && fibonacciEvidence);
   trigger = confluenceVotes >= InpMinimumM5ConfluenceVotes &&
      confluenceVotes <= InpMaximumM5ConfluenceVotes && anchoredEvidence;

   if(trigger)
   {
      g_triggerCandidates++;
      g_m5StrongPattern = strongPattern;
      g_m5StarPattern = starPattern;
      g_m5ConfluenceVotes = confluenceVotes;
      g_m5PatternName = patternName;
      g_candidateId = BuildCandidateId();
      CaptureCandidateAccountOrigin();
      EmitEarlyCandidateIfEligible(tick, strongPattern, starPattern);
      g_phase = PHASE_WAITING_M1_TRIGGER;
      g_m1EntryBars = 0;
      return;
   }

   g_m5ConfluenceRejects++;

   if(g_triggerBars >= InpMaximumM5TriggerBars)
   {
      g_triggerExpired++;
      ResetSetup("M5_TRIGGER_EXPIRED");
   }
}

int EarlyCandidateConfidenceScore(const bool strongPattern, const bool starPattern)
{
   int score = MathMin(g_contextVotes, 3) * 5;
   score += g_breakoutBodyRatio >= 0.65 ? 10 : 7;
   score += g_breakoutDisplacementAtr >= 0.10 && g_breakoutDisplacementAtr <= 0.60 ? 10 : 6;
   score += g_breakoutWickRatio <= 0.35 ? 8 : 5;
   score += g_breakoutRelativeVolume >= 1.00 ? 7 : 4;
   const double retestDistanceAtr = g_breakoutAtr > 0.0
      ? MathAbs(g_retestExtreme - g_level) / g_breakoutAtr
      : DBL_MAX;
   score += retestDistanceAtr <= 0.15 ? 15 : (retestDistanceAtr <= 0.30 ? 11 : 7);
   score += MathMin(g_m5ConfluenceVotes, 4) * 8;
   score += starPattern ? 8 : (strongPattern ? 6 : 3);
   return MathMin(score, 100);
}

string BuildCandidateId()
{
   const datetime referenceTime = g_breakoutTime > 0 ? g_breakoutTime : TimeCurrent();
   return StringFormat(
      "%s-%s-%.2f-%s",
      _Symbol,
      g_side == SETUP_BUY ? "BUY" : "SELL",
      g_level,
      TimeToString(referenceTime, TIME_DATE|TIME_MINUTES)
   );
}

long ServerUtcOffsetSeconds()
{
   const datetime serverNow = TimeTradeServer() > 0 ? TimeTradeServer() : TimeCurrent();
   return (long)serverNow - (long)TimeGMT();
}

long ServerTimeToUtcEpoch(const datetime serverTime)
{
   return (long)serverTime - ServerUtcOffsetSeconds();
}

long GeneratedUtcEpoch()
{
   const datetime serverNow = TimeTradeServer() > 0 ? TimeTradeServer() : TimeCurrent();
   return ServerTimeToUtcEpoch(serverNow);
}

void EmitEarlyCandidateIfEligible(
   const MqlTick &tick,
   const bool strongPattern,
   const bool starPattern
)
{
   g_earlyCandidateConfidence = EarlyCandidateConfidenceScore(strongPattern, starPattern);
   if(!InpEnableEarlyCandidateAlerts || g_earlyCandidateAlerted ||
      (double)g_earlyCandidateConfidence <= InpMinimumEarlyCandidateConfidence)
      return;

   const double watchPrice = g_side == SETUP_BUY ? tick.ask : tick.bid;
   const double invalidation = g_side == SETUP_BUY
      ? g_level - InpMaximumRetestPenetrationATR * g_breakoutAtr
      : g_level + InpMaximumRetestPenetrationATR * g_breakoutAtr;
   const double fibonacciReaction = NearestFibonacciExtension(g_side, watchPrice);
   g_earlyCandidateAlerted = true;
   g_earlyCandidateAlerts++;
   PrintFormat(
      "SNIPER_EARLY_CANDIDATE id=%s status=WATCH_ONLY strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d autoEntry=false side=%s level=%.2f watchPrice=%.2f invalidation=%.2f confidence=%d threshold=>%.1f m5Votes=%d pattern=%s fibonacciReaction=%.2f next=M1_AND_FINAL_RISK_CHECK setupUtcEpoch=%I64d generatedUtcEpoch=%I64d serverUtcOffsetMinutes=%d",
      g_candidateId,
      SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
      EngineLineageProfile(), ResearchRunId(),
      g_candidateAccountScope, g_candidateAccountLogin,
      g_candidateServerB64, InpStrategyMode,
      g_side == SETUP_BUY ? "BUY" : "SELL",
      g_level, watchPrice, invalidation, g_earlyCandidateConfidence,
      InpMinimumEarlyCandidateConfidence, g_m5ConfluenceVotes,
      g_m5PatternName, fibonacciReaction,
      g_candidateSetupUtcEpoch, GeneratedUtcEpoch(),
      (int)(ServerUtcOffsetSeconds() / 60)
   );
}

bool IsDojiCandle(const ENUM_TIMEFRAMES timeframe, const int shift)
{
   const double open = iOpen(_Symbol, timeframe, shift);
   const double high = iHigh(_Symbol, timeframe, shift);
   const double low = iLow(_Symbol, timeframe, shift);
   const double close = iClose(_Symbol, timeframe, shift);
   const double range = high - low;
   if(range <= 0.0)
      return false;
   return MathAbs(close - open) / range <= InpDojiMaximumBodyRatio;
}

bool IsMorningDojiStar(const ENUM_TIMEFRAMES timeframe)
{
   const double open3 = iOpen(_Symbol, timeframe, 3);
   const double high3 = iHigh(_Symbol, timeframe, 3);
   const double low3 = iLow(_Symbol, timeframe, 3);
   const double close3 = iClose(_Symbol, timeframe, 3);
   const double open2 = iOpen(_Symbol, timeframe, 2);
   const double close2 = iClose(_Symbol, timeframe, 2);
   const double open1 = iOpen(_Symbol, timeframe, 1);
   const double close1 = iClose(_Symbol, timeframe, 1);
   const double firstRange = high3 - low3;
   if(firstRange <= 0.0)
      return false;
   const bool bearishFirst = close3 < open3 && MathAbs(close3 - open3) / firstRange >= 0.45;
   const bool dojiMiddle = IsDojiCandle(timeframe, 2);
   const bool bullishThird = close1 > open1 && close1 >= (open3 + close3) / 2.0;
   const bool starLocatedLow = MathMax(open2, close2) <= MathMax(open3, close3);
   return bearishFirst && dojiMiddle && bullishThird && starLocatedLow;
}

bool IsEveningDojiStar(const ENUM_TIMEFRAMES timeframe)
{
   const double open3 = iOpen(_Symbol, timeframe, 3);
   const double high3 = iHigh(_Symbol, timeframe, 3);
   const double low3 = iLow(_Symbol, timeframe, 3);
   const double close3 = iClose(_Symbol, timeframe, 3);
   const double open2 = iOpen(_Symbol, timeframe, 2);
   const double close2 = iClose(_Symbol, timeframe, 2);
   const double open1 = iOpen(_Symbol, timeframe, 1);
   const double close1 = iClose(_Symbol, timeframe, 1);
   const double firstRange = high3 - low3;
   if(firstRange <= 0.0)
      return false;
   const bool bullishFirst = close3 > open3 && MathAbs(close3 - open3) / firstRange >= 0.45;
   const bool dojiMiddle = IsDojiCandle(timeframe, 2);
   const bool bearishThird = close1 < open1 && close1 <= (open3 + close3) / 2.0;
   const bool starLocatedHigh = MathMin(open2, close2) >= MathMin(open3, close3);
   return bullishFirst && dojiMiddle && bearishThird && starLocatedHigh;
}

void ProcessClosedM1(const MqlTick &tick)
{
   if(g_active)
   {
      ManageActiveSignalFromM1(tick);
      return;
   }
   if(g_phase != PHASE_WAITING_M1_TRIGGER)
      return;

   g_m1EntryBars++;
   const double open1 = iOpen(_Symbol, PERIOD_M1, 1);
   const double high1 = iHigh(_Symbol, PERIOD_M1, 1);
   const double low1 = iLow(_Symbol, PERIOD_M1, 1);
   const double close1 = iClose(_Symbol, PERIOD_M1, 1);
   const double high2 = iHigh(_Symbol, PERIOD_M1, 2);
   const double low2 = iLow(_Symbol, PERIOD_M1, 2);
   const double rsi = IndicatorValue(g_m1Rsi, 0, 1);
   bool heldInvalidation = false;
   bool directionalCandle = false;
   bool microBreak = false;
   bool rsiEvidence = false;
   if(g_side == SETUP_BUY)
   {
      heldInvalidation = low1 >= g_level - InpMaximumRetestPenetrationATR * g_breakoutAtr;
      directionalCandle = close1 > open1;
      microBreak = close1 > high2;
      rsiEvidence = rsi >= 50.0;
   }
   else if(g_side == SETUP_SELL)
   {
      heldInvalidation = high1 <= g_level + InpMaximumRetestPenetrationATR * g_breakoutAtr;
      directionalCandle = close1 < open1;
      microBreak = close1 < low2;
      rsiEvidence = rsi <= 50.0;
   }

   const int m1Votes = (directionalCandle ? 1 : 0) + (microBreak ? 1 : 0) +
      (rsiEvidence ? 1 : 0);
   const bool refined = heldInvalidation && m1Votes >= 2;
   const bool fibonacciAligned = FibonacciRetracementAligned(g_side, close1);

   if(refined)
   {
      if(InpUseFibonacciEntryDelay && !fibonacciAligned &&
         g_m1EntryBars <= InpMaximumFibonacciDelayBars)
      {
         g_fibDelayedBars++;
         return;
      }
      CreateTechnicalSignal(tick, g_m5StrongPattern, true);
      return;
   }
   if(g_m1EntryBars >= InpMaximumM1EntryBars)
   {
      if(heldInvalidation && (g_m5ConfluenceVotes >= 3 || fibonacciAligned))
      {
         g_m1FallbackEntries++;
         CreateTechnicalSignal(tick, g_m5StrongPattern, false);
         return;
      }
      g_m1EntryExpired++;
      ResetSetup("M1_CONFIRMATION_EXPIRED");
   }
}

void ManageActiveSignalFromM1(const MqlTick &tick)
{
   if(g_risk <= 0.0)
      return;
   const double open1 = iOpen(_Symbol, PERIOD_M1, 1);
   const double close1 = iClose(_Symbol, PERIOD_M1, 1);
   const double low2 = iLow(_Symbol, PERIOD_M1, 2);
   const double high2 = iHigh(_Symbol, PERIOD_M1, 2);
   const double ema = IndicatorValue(g_m1Ema, 0, 1);
   bool against = false;
   if(g_activeSide == SETUP_BUY)
      against = close1 < open1 && close1 < ema && close1 < low2;
   else if(g_activeSide == SETUP_SELL)
      against = close1 > open1 && close1 > ema && close1 > high2;

   if(against)
      g_m1AgainstBars++;
   else
      g_m1AgainstBars = 0;

   const double exitPrice = g_activeSide == SETUP_BUY ? tick.bid : tick.ask;
   const double currentR = g_activeSide == SETUP_BUY
      ? (exitPrice - g_entry) / g_risk
      : (g_entry - exitPrice) / g_risk;
   if(!g_hit1R)
   {
      if(InpEnablePre1RAdverseExit && g_m1AgainstBars >= InpPre1RAdverseBars &&
         currentR <= -InpPre1RAdverseThresholdR)
      {
         g_m1ManagedExits++;
         CompleteSignal(NetOutcomeR(MathMax(-1.0, MathMin(3.0, currentR))), "M1_DEFENSIVE");
      }
      return;
   }

   const double currentPrice = g_activeSide == SETUP_BUY ? tick.bid : tick.ask;
   const bool fibonacciReactionReached = g_activeFibReaction > 0.0 &&
      (g_activeSide == SETUP_BUY
         ? currentPrice >= g_activeFibReaction
         : currentPrice <= g_activeFibReaction);
   const int barsRequired = g_hit2R || fibonacciReactionReached ? 1 : 2;
   if(g_m1AgainstBars < barsRequired)
      return;
   g_m1ManagedExits++;
   CompleteSignal(NetOutcomeR(MathMax(-1.0, MathMin(3.0, currentR))), "M1_MANAGEMENT");
}

void CreateTechnicalSignal(
   const MqlTick &tick,
   const bool strongPattern,
   const bool m1Confirmed
)
{
   const double entry = g_side == SETUP_BUY ? tick.ask : tick.bid;
   const bool fibonacciAligned = FibonacciRetracementAligned(g_side, entry);
   const double currentM15Atr = IndicatorValue(g_m15Atr, 0, 1);
   const double atr = currentM15Atr > 0.0 ? currentM15Atr : g_breakoutAtr;
   if(atr <= 0.0)
   {
      g_healthRejects++;
      ResetSetup("ATR_UNAVAILABLE");
      return;
   }

   const double entryDistanceAtr = g_side == SETUP_BUY
      ? (entry - g_level) / atr
      : (g_level - entry) / atr;
   if(entryDistanceAtr < 0.0 || entryDistanceAtr > InpMaximumEntryDistanceATR)
   {
      g_entryDistanceRejects++;
      ResetSetup("ENTRY_DISTANCE_REJECTED");
      return;
   }

   double stop = 0.0;
   const double m15Invalidation = g_side == SETUP_BUY
      ? g_level - InpMaximumRetestPenetrationATR * atr
      : g_level + InpMaximumRetestPenetrationATR * atr;
   if(g_side == SETUP_BUY)
      stop = MathMin(g_retestExtreme, m15Invalidation) - InpM15StructuralStopBufferATR * atr;
   else
      stop = MathMax(g_retestExtreme, m15Invalidation) + InpM15StructuralStopBufferATR * atr;
   stop = NormalizeDouble(stop, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));

   const double risk = g_side == SETUP_BUY ? entry - stop : stop - entry;
   if(risk <= SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE))
   {
      g_roomRejects++;
      ResetSetup("INVALID_STOP_GEOMETRY");
      return;
   }

   const double target = NearestObjectiveTarget(g_side, entry, risk * InpMinimumProjectedR);
   const double reward = g_side == SETUP_BUY ? target - entry : entry - target;
   const double projectedR = reward > 0.0 ? reward / risk : 0.0;
   RecordRoomCandidate(projectedR);
   if(projectedR < InpMinimumProjectedR)
   {
      g_roomRejects++;
      ResetSetup("PROJECTED_R_REJECTED");
      return;
   }

   const int score = TechnicalScore(
      strongPattern, m1Confirmed, fibonacciAligned, projectedR, atr
   );
   if(score < InpMinimumSetupScore)
   {
      g_scoreRejects++;
      ResetSetup("FINAL_SCORE_REJECTED");
      return;
   }

   if(g_candidateId == "")
   {
      g_candidateId = BuildCandidateId();
      CaptureCandidateAccountOrigin();
   }
   g_active = true;
   g_activeCandidateId = g_candidateId;
   g_activeAccountScope = g_candidateAccountScope;
   g_activeAccountLogin = g_candidateAccountLogin;
   g_activeServerB64 = g_candidateServerB64;
   g_activeSetupUtcEpoch = g_candidateSetupUtcEpoch;
   g_activeSide = g_side;
   g_entry = entry;
   g_stop = stop;
   g_risk = risk;
   g_target = target;
   g_activeProjectedR = projectedR;
   g_activeFibReaction = NearestFibonacciExtension(g_side, entry);
   g_signalTime = TimeCurrent();
   g_hit1R = false;
   g_hit2R = false;
   g_hit3R = false;
   g_partialTaken = false;
   g_realizedPartialR = 0.0;
   g_remainingPositionFraction = 1.0;
   g_activeMfeR = 0.0;
   g_activeMaeR = 0.0;
   g_m1AgainstBars = 0;
   g_signals++;
   if(fibonacciAligned) g_fibAlignedSignals++;
   if(g_side == SETUP_BUY) g_buySignals++;
   if(g_side == SETUP_SELL) g_sellSignals++;
   g_totalProjectedR += projectedR;
   g_totalScore += score;

   if(g_earlyCandidateAlerted)
   {
      g_earlyCandidatePromoted = true;
      g_earlyCandidatePromotions++;
      PrintFormat(
         "SNIPER_EARLY_PROMOTED id=%s status=ENTRY_READY strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d confidenceEarly=%d scoreFinal=%d setupUtcEpoch=%I64d generatedUtcEpoch=%I64d serverUtcOffsetMinutes=%d",
         g_candidateId, SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
         EngineLineageProfile(), ResearchRunId(),
         g_candidateAccountScope, g_candidateAccountLogin,
         g_candidateServerB64, InpStrategyMode,
         g_earlyCandidateConfidence, score,
         g_candidateSetupUtcEpoch, GeneratedUtcEpoch(),
         (int)(ServerUtcOffsetSeconds() / 60)
      );
   }

   PrintFormat(
      "SNIPER_SIGNAL id=%s status=ENTRY_READY strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d autoEntryEligible=true side=%s level=%.2f entry=%.2f stop=%.2f target=%.2f riskTF=M15 entryDistanceATR=%.3f stopDistanceATR=%.3f projectedR=%.3f score=%d m5Votes=%d pattern=%s fibonacciAligned=%s fibonacciReaction=%.2f m1Confirmed=%s retestBars=%d setupUtcEpoch=%I64d generatedUtcEpoch=%I64d serverUtcOffsetMinutes=%d validUntilUtcEpoch=%I64d maxHoldingMinutes=%d",
      g_candidateId,
      SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
      EngineLineageProfile(), ResearchRunId(),
      g_activeAccountScope, g_activeAccountLogin,
      g_activeServerB64, InpStrategyMode,
      g_side == SETUP_BUY ? "BUY" : "SELL",
      g_level, g_entry, g_stop, g_target, entryDistanceAtr, risk / atr,
      projectedR, score, g_m5ConfluenceVotes, g_m5PatternName,
      fibonacciAligned ? "true" : "false", g_activeFibReaction,
      m1Confirmed ? "true" : "false", g_retestBars,
      g_activeSetupUtcEpoch, GeneratedUtcEpoch(),
      (int)(ServerUtcOffsetSeconds() / 60),
      GeneratedUtcEpoch() + (long)InpSignalValidityMinutes * 60,
      InpOutcomeHorizonM15Bars * 15
   );
   ResetSetup("PROMOTED_TO_ENTRY_READY");
}

void UpdateActiveSignal(const MqlTick &tick)
{
   if(!g_active || g_risk <= 0.0)
      return;

   const double exitPrice = g_activeSide == SETUP_BUY ? tick.bid : tick.ask;
   const double currentR = g_activeSide == SETUP_BUY
      ? (exitPrice - g_entry) / g_risk
      : (g_entry - exitPrice) / g_risk;
   g_activeMfeR = MathMax(g_activeMfeR, currentR);
   g_activeMaeR = MathMin(g_activeMaeR, currentR);
   if(currentR >= 1.0) g_hit1R = true;
   if(currentR >= 2.0) g_hit2R = true;
   if(currentR >= 3.0) g_hit3R = true;
   if(InpEnablePartialTake && !g_partialTaken && currentR >= InpPartialTakeR)
   {
      g_partialTaken = true;
      g_realizedPartialR = InpPartialFraction * InpPartialTakeR;
      g_remainingPositionFraction = 1.0 - InpPartialFraction;
   }

   if(g_hit2R)
   {
      const double protectedStop = g_activeSide == SETUP_BUY
         ? g_entry + InpPost2RLockR * g_risk
         : g_entry - InpPost2RLockR * g_risk;
      if(g_activeSide == SETUP_BUY) g_stop = MathMax(g_stop, protectedStop);
      else g_stop = MathMin(g_stop, protectedStop);
   }
   else if(g_hit1R)
   {
      const double protectedStop = g_activeSide == SETUP_BUY
         ? g_entry + InpPost1RLockR * g_risk
         : g_entry - InpPost1RLockR * g_risk;
      if(g_activeSide == SETUP_BUY) g_stop = MathMax(g_stop, protectedStop);
      else g_stop = MathMin(g_stop, protectedStop);
   }

   const bool stopped = g_activeSide == SETUP_BUY ? tick.bid <= g_stop : tick.ask >= g_stop;
   if(stopped)
   {
      const bool protectedExit = g_hit1R;
      const double stoppedR = MathMax(-1.0, MathMin(3.0, currentR));
      CompleteSignal(NetOutcomeR(stoppedR), protectedExit ? "PROTECTED_STOP" : "STOP");
      return;
   }
   if(g_hit3R)
   {
      CompleteSignal(NetOutcomeR(3.0), "THREE_R");
      return;
   }
   const bool targetHit = g_activeSide == SETUP_BUY
      ? tick.bid >= g_target
      : tick.ask <= g_target;
   if(targetHit)
   {
      CompleteSignal(NetOutcomeR(g_activeProjectedR), "TARGET");
      return;
   }

   const int horizonSeconds = InpOutcomeHorizonM15Bars * PeriodSeconds(PERIOD_M15);
   if(TimeCurrent() - g_signalTime >= horizonSeconds)
      CompleteSignal(NetOutcomeR(MathMax(-1.0, MathMin(3.0, currentR))), "TIMEOUT");
}

double NetOutcomeR(const double remainingPositionR)
{
   if(!g_partialTaken)
      return remainingPositionR;
   return g_realizedPartialR + g_remainingPositionFraction * remainingPositionR;
}

void CompleteSignal(const double outcomeR, const string reason)
{
   if(!g_active)
      return;
   g_resolved++;
   if(g_hit1R) g_oneR++;
   if(g_hit2R) g_twoR++;
   if(g_hit3R) g_threeR++;
   if(reason == "STOP") g_stopped++;
   if(reason == "PROTECTED_STOP") g_protectedStops++;
   if(reason == "TIMEOUT" || reason == "END_OF_TEST") g_timedOut++;
   g_totalOutcomeR += outcomeR;
   g_totalMfeR += g_activeMfeR;
   g_totalMaeR += g_activeMaeR;
   PrintFormat(
      "SNIPER_OUTCOME id=%s status=CLOSED strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d side=%s result=%s outcomeR=%.4f entry=%.2f exitPrice=%.2f stop=%.2f target=%.2f projectedR=%.4f hit1R=%s hit2R=%s hit3R=%s mfeR=%.4f maeR=%.4f durationMinutes=%d setupUtcEpoch=%I64d generatedUtcEpoch=%I64d serverUtcOffsetMinutes=%d source=MODEL_SIMULATION",
      g_activeCandidateId,
      SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
      EngineLineageProfile(), ResearchRunId(),
      g_activeAccountScope, g_activeAccountLogin,
      g_activeServerB64, InpStrategyMode,
      g_activeSide == SETUP_BUY ? "BUY" : "SELL", reason, outcomeR,
      g_entry,
      g_activeSide == SETUP_BUY ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK),
      g_stop, g_target, g_activeProjectedR,
      g_hit1R ? "true" : "false", g_hit2R ? "true" : "false",
      g_hit3R ? "true" : "false", g_activeMfeR, g_activeMaeR,
      (int)((TimeCurrent() - g_signalTime) / 60), g_activeSetupUtcEpoch,
      GeneratedUtcEpoch(), (int)(ServerUtcOffsetSeconds() / 60)
   );
   g_active = false;
   g_activeSide = SETUP_NONE;
   g_activeCandidateId = "";
   g_activeAccountScope = "unknown";
   g_activeAccountLogin = 0;
   g_activeServerB64 = "";
   g_activeSetupUtcEpoch = 0;
   g_activeFibReaction = 0.0;
}

void FinalizeOpenSignalAtMarket()
{
   if(!g_active || g_risk <= 0.0)
      return;
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;
   const double exitPrice = g_activeSide == SETUP_BUY ? tick.bid : tick.ask;
   const double currentR = g_activeSide == SETUP_BUY
      ? (exitPrice - g_entry) / g_risk
      : (g_entry - exitPrice) / g_risk;
   CompleteSignal(NetOutcomeR(MathMax(-1.0, MathMin(3.0, currentR))), "END_OF_TEST");
}

bool ContextAligned(const SetupSide side)
{
   g_contextVotes = 0;
   const double d1Close = iClose(_Symbol, PERIOD_D1, 1);
   const double h4Close = iClose(_Symbol, PERIOD_H4, 1);
   const double h1Close = iClose(_Symbol, PERIOD_H1, 1);
   const double d1Fast = IndicatorValue(g_d1EmaFast, 0, 1);
   const double h4Fast = IndicatorValue(g_h4EmaFast, 0, 1);
   const double h4Slow = IndicatorValue(g_h4EmaSlow, 0, 1);
   const double h1Fast = IndicatorValue(g_h1EmaFast, 0, 1);
   const double h1Slow = IndicatorValue(g_h1EmaSlow, 0, 1);
   if(d1Fast <= 0.0 || h4Fast <= 0.0 || h4Slow <= 0.0 || h1Fast <= 0.0 || h1Slow <= 0.0)
      return false;
   if(side == SETUP_BUY)
   {
      if(d1Close >= d1Fast) g_contextVotes++;
      if(h4Fast > h4Slow && h4Close > h4Fast) g_contextVotes++;
      if(h1Fast > h1Slow && h1Close > h1Fast) g_contextVotes++;
      return g_contextVotes >= InpMinimumContextVotes;
   }
   if(side == SETUP_SELL)
   {
      if(d1Close <= d1Fast) g_contextVotes++;
      if(h4Fast < h4Slow && h4Close < h4Fast) g_contextVotes++;
      if(h1Fast < h1Slow && h1Close < h1Fast) g_contextVotes++;
      return g_contextVotes >= InpMinimumContextVotes;
   }
   return false;
}

bool HealthyMarket(const double atr)
{
   const double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   const double spreadPrice = (double)iSpread(_Symbol, PERIOD_M15, 1) * point;
   if(spreadPrice < 0.0 || spreadPrice / atr > InpMaximumSpreadATR)
      return false;
   double averageAtr = 0.0;
   int count = 0;
   for(int shift = 2; shift <= 21; shift++)
   {
      const double value = IndicatorValue(g_m15Atr, 0, shift);
      if(value > 0.0)
      {
         averageAtr += value;
         count++;
      }
   }
   if(count <= 0)
      return false;
   averageAtr /= count;
   const double ratio = atr / averageAtr;
   return ratio >= InpMinimumATRRegimeRatio && ratio <= InpMaximumATRRegimeRatio;
}

double RelativeTickVolume(const ENUM_TIMEFRAMES timeframe, const int shift, const int lookback)
{
   const long current = iVolume(_Symbol, timeframe, shift);
   double average = 0.0;
   for(int i = shift + 1; i <= shift + lookback; i++)
      average += (double)iVolume(_Symbol, timeframe, i);
   average /= lookback;
   if(average <= 0.0)
      return 0.0;
   return (double)current / average;
}

double NearestObjectiveTarget(
   const SetupSide side,
   const double entry,
   const double minimumReward
)
{
   double target = side == SETUP_BUY ? DBL_MAX : -DBL_MAX;
   const double weekly = side == SETUP_BUY
      ? iHigh(_Symbol, PERIOD_W1, 1)
      : iLow(_Symbol, PERIOD_W1, 1);
   AddTargetCandidate(side, entry, weekly, minimumReward, target);
   AddTargetCandidate(side, entry, iHigh(_Symbol, PERIOD_D1, 1), minimumReward, target);
   AddTargetCandidate(side, entry, iLow(_Symbol, PERIOD_D1, 1), minimumReward, target);

   for(int shift = 3; shift <= 96; shift++)
   {
      const double middle = side == SETUP_BUY
         ? iHigh(_Symbol, PERIOD_M15, shift)
         : iLow(_Symbol, PERIOD_M15, shift);
      const double left = side == SETUP_BUY
         ? iHigh(_Symbol, PERIOD_M15, shift + 1)
         : iLow(_Symbol, PERIOD_M15, shift + 1);
      const double right = side == SETUP_BUY
         ? iHigh(_Symbol, PERIOD_M15, shift - 1)
         : iLow(_Symbol, PERIOD_M15, shift - 1);
      const bool swing = side == SETUP_BUY
         ? (middle > left && middle > right)
         : (middle < left && middle < right);
      if(swing)
         AddTargetCandidate(side, entry, middle, minimumReward, target);
   }

   const double fibRange = side == SETUP_BUY
      ? g_fibImpulseEnd - g_fibImpulseStart
      : g_fibImpulseStart - g_fibImpulseEnd;
   if(fibRange > 0.0)
   {
      const double extensions[3] = {1.272, 1.618, 2.000};
      for(int i = 0; i < 3; i++)
      {
         const double candidate = side == SETUP_BUY
            ? g_fibImpulseStart + extensions[i] * fibRange
            : g_fibImpulseStart - extensions[i] * fibRange;
         AddTargetCandidate(side, entry, candidate, minimumReward, target);
      }
   }

   for(int shift = 3; shift <= 48; shift++)
   {
      const double middle = side == SETUP_BUY
         ? iHigh(_Symbol, PERIOD_H1, shift)
         : iLow(_Symbol, PERIOD_H1, shift);
      const double left = side == SETUP_BUY
         ? iHigh(_Symbol, PERIOD_H1, shift + 1)
         : iLow(_Symbol, PERIOD_H1, shift + 1);
      const double right = side == SETUP_BUY
         ? iHigh(_Symbol, PERIOD_H1, shift - 1)
         : iLow(_Symbol, PERIOD_H1, shift - 1);
      const bool swing = side == SETUP_BUY
         ? (middle > left && middle > right)
         : (middle < left && middle < right);
      if(swing)
         AddTargetCandidate(side, entry, middle, minimumReward, target);
   }

   double psychological = 0.0;
   if(side == SETUP_BUY)
   {
      psychological = MathCeil(entry / InpPsychologicalStep) * InpPsychologicalStep;
      if(psychological <= entry + SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE))
         psychological += InpPsychologicalStep;
   }
   else
   {
      psychological = MathFloor(entry / InpPsychologicalStep) * InpPsychologicalStep;
      if(psychological >= entry - SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE))
         psychological -= InpPsychologicalStep;
   }
   AddTargetCandidate(side, entry, psychological, minimumReward, target);

   if(target == DBL_MAX || target == -DBL_MAX)
      return 0.0;
   return target;
}

void AddTargetCandidate(
   const SetupSide side,
   const double entry,
   const double candidate,
   const double minimumReward,
   double &target
)
{
   if(candidate <= 0.0)
      return;
   if(side == SETUP_BUY && candidate >= entry + minimumReward && candidate < target)
      target = candidate;
   if(side == SETUP_SELL && candidate <= entry - minimumReward && candidate > target)
      target = candidate;
}

int TechnicalScore(
   const bool strongPattern,
   const bool m1Confirmed,
   const bool fibonacciAligned,
   const double projectedR,
   const double atr
)
{
   int score = g_contextVotes >= 3 ? 18 : 14;
   score += g_breakoutBodyRatio >= 0.65 ? 8 : 6;
   score += g_breakoutDisplacementAtr >= 0.10 && g_breakoutDisplacementAtr <= 0.60 ? 8 : 6;
   score += g_breakoutWickRatio <= 0.35 ? 6 : 4;
   score += g_breakoutRelativeVolume >= 1.00 ? 6 : 4;
   const double retestDistanceAtr = atr > 0.0 ? MathAbs(g_retestExtreme - g_level) / atr : DBL_MAX;
   score += retestDistanceAtr <= 0.15 ? 10 : (retestDistanceAtr <= 0.30 ? 8 : 6);
   score += g_m5ConfluenceVotes * 8;
   score += g_m5StarPattern ? 8 : (strongPattern ? 5 : 0);
   score += InpUseFibonacciScore && fibonacciAligned ? 6 : 0;
   score += m1Confirmed ? 8 : 3;
   score += projectedR >= 2.50 ? 10 : (projectedR >= 2.00 ? 8 : 6);
   return MathMin(score, 100);
}

void RecordRoomCandidate(const double projectedR)
{
   g_roomCandidateTotalR += projectedR;
   g_roomCandidateMinimumR = MathMin(g_roomCandidateMinimumR, projectedR);
   g_roomCandidateMaximumR = MathMax(g_roomCandidateMaximumR, projectedR);
   if(projectedR < 2.0)
      g_roomBelow2++;
   else if(projectedR < 2.5)
      g_roomWatch++;
   else if(projectedR < 3.0)
      g_roomStrong++;
   else
      g_roomAPlus++;
}

bool IsConfiguredTradeWindow(const datetime value)
{
   MqlDateTime parts;
   TimeToStruct(value, parts);
   const int minutes = parts.hour * 60 + parts.min;
   return minutes >= InpTradeWindowStartMinute && minutes <= InpTradeWindowEndMinute;
}

bool IntradayVwapAligned(const SetupSide side, const double price, const int shift)
{
   const double vwap = IntradayVwapValue(shift);
   if(vwap <= 0.0)
      return false;
   if(side == SETUP_BUY)
      return price >= vwap;
   if(side == SETUP_SELL)
      return price <= vwap;
   return false;
}

double IntradayVwapValue(const int shift)
{
   const datetime reference = iTime(_Symbol, PERIOD_M15, shift);
   if(reference <= 0)
      return 0.0;

   MqlDateTime referenceParts;
   TimeToStruct(reference, referenceParts);
   double weightedPrice = 0.0;
   double totalVolume = 0.0;
   const int available = Bars(_Symbol, PERIOD_M15);
   const int maximumShift = MathMin(shift + 96, available - 1);
   for(int barShift = shift; barShift <= maximumShift; barShift++)
   {
      const datetime barTime = iTime(_Symbol, PERIOD_M15, barShift);
      if(barTime <= 0)
         break;
      MqlDateTime barParts;
      TimeToStruct(barTime, barParts);
      if(barParts.year != referenceParts.year || barParts.mon != referenceParts.mon ||
         barParts.day != referenceParts.day)
         break;

      const double typicalPrice = (iHigh(_Symbol, PERIOD_M15, barShift) +
         iLow(_Symbol, PERIOD_M15, barShift) + iClose(_Symbol, PERIOD_M15, barShift)) / 3.0;
      const double volume = (double)iVolume(_Symbol, PERIOD_M15, barShift);
      if(typicalPrice > 0.0 && volume > 0.0)
      {
         weightedPrice += typicalPrice * volume;
         totalVolume += volume;
      }
   }
   if(totalVolume <= 0.0)
      return 0.0;
   return weightedPrice / totalVolume;
}

double IndicatorValue(const int handle, const int buffer, const int shift)
{
   if(handle == INVALID_HANDLE || BarsCalculated(handle) <= shift)
      return 0.0;
   double values[1];
   if(CopyBuffer(handle, buffer, shift, 1, values) != 1)
      return 0.0;
   return values[0];
}

void ResetSetup(const string reason = "SETUP_RESET")
{
   if(g_earlyCandidateAlerted && !g_earlyCandidatePromoted)
   {
      g_earlyCandidateCancellations++;
      PrintFormat(
         "SNIPER_EARLY_CANCELLED id=%s status=CANCELLED strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d autoEntry=false confidenceEarly=%d reason=%s setupUtcEpoch=%I64d generatedUtcEpoch=%I64d serverUtcOffsetMinutes=%d",
         g_candidateId, SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
         EngineLineageProfile(), ResearchRunId(),
         g_candidateAccountScope, g_candidateAccountLogin,
         g_candidateServerB64, InpStrategyMode,
         g_earlyCandidateConfidence, reason,
         g_candidateSetupUtcEpoch, GeneratedUtcEpoch(),
         (int)(ServerUtcOffsetSeconds() / 60)
      );
   }
   g_phase = PHASE_SCANNING;
   g_side = SETUP_NONE;
   g_level = 0.0;
   g_breakoutAtr = 0.0;
   g_breakoutTime = 0;
   g_retestBars = 0;
   g_retestExtreme = 0.0;
   g_triggerBars = 0;
   g_m1EntryBars = 0;
   g_m5StrongPattern = false;
   g_m5StarPattern = false;
   g_m5ConfluenceVotes = 0;
   g_contextVotes = 0;
   g_m5PatternName = "NONE";
   g_breakoutBodyRatio = 0.0;
   g_breakoutDisplacementAtr = 0.0;
   g_breakoutWickRatio = 0.0;
   g_breakoutRelativeVolume = 0.0;
   g_fibImpulseStart = 0.0;
   g_fibImpulseEnd = 0.0;
   g_candidateId = "";
   g_candidateAccountScope = "unknown";
   g_candidateAccountLogin = 0;
   g_candidateServerB64 = "";
   g_candidateSetupUtcEpoch = 0;
   g_earlyCandidateAlerted = false;
   g_earlyCandidatePromoted = false;
   g_earlyCandidateConfidence = 0;
}

void PrintSummary()
{
   const double expectancy = g_resolved > 0 ? g_totalOutcomeR / g_resolved : 0.0;
   const double p1 = g_resolved > 0 ? (double)g_oneR / g_resolved * 100.0 : 0.0;
   const double p2 = g_resolved > 0 ? (double)g_twoR / g_resolved * 100.0 : 0.0;
   const double p3 = g_resolved > 0 ? (double)g_threeR / g_resolved * 100.0 : 0.0;
   const double averageMfe = g_resolved > 0 ? g_totalMfeR / g_resolved : 0.0;
   const double averageMae = g_resolved > 0 ? g_totalMaeR / g_resolved : 0.0;
   const double averageProjected = g_signals > 0 ? g_totalProjectedR / g_signals : 0.0;
   const double averageScore = g_signals > 0 ? g_totalScore / g_signals : 0.0;
   const int roomCandidates = g_roomBelow2 + g_roomWatch + g_roomStrong + g_roomAPlus;
   const double averageCandidateRoom = roomCandidates > 0 ? g_roomCandidateTotalR / roomCandidates : 0.0;
   const double minimumCandidateRoom = roomCandidates > 0 ? g_roomCandidateMinimumR : 0.0;
   PrintFormat(
      "SNIPER_DIAGNOSTIC strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d ticks=%I64d breakouts=%d contextRejects=%d healthRejects=%d retests=%d invalidated=%d retestExpired=%d triggerCandidates=%d m5ConfluenceRejects=%d triggerExpired=%d m1EntryExpired=%d m1FallbackEntries=%d fibDelayedBars=%d fibAlignedSignals=%d entryDistanceRejects=%d roomRejects=%d scoreRejects=%d earlyCandidates=%d earlyPromoted=%d earlyCancelled=%d signals=%d buy=%d sell=%d",
      SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
      EngineLineageProfile(), ResearchRunId(),
      CurrentAccountScope(), AccountInfoInteger(ACCOUNT_LOGIN),
      CurrentAccountServerB64(), InpStrategyMode,
      g_ticks, g_breakouts, g_contextRejects, g_healthRejects, g_retests, g_invalidated,
      g_retestExpired, g_triggerCandidates, g_m5ConfluenceRejects, g_triggerExpired,
      g_m1EntryExpired, g_m1FallbackEntries, g_fibDelayedBars, g_fibAlignedSignals,
      g_entryDistanceRejects, g_roomRejects, g_scoreRejects,
      g_earlyCandidateAlerts, g_earlyCandidatePromotions, g_earlyCandidateCancellations,
      g_signals, g_buySignals, g_sellSignals
   );
   PrintFormat(
      "SNIPER_ROOM strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d candidates=%d below2R=%d watch2R=%d strong2_5R=%d aPlus3R=%d minimumR=%.5f averageR=%.5f maximumR=%.5f",
      SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
      EngineLineageProfile(), ResearchRunId(),
      CurrentAccountScope(), AccountInfoInteger(ACCOUNT_LOGIN),
      CurrentAccountServerB64(), InpStrategyMode,
      roomCandidates, g_roomBelow2, g_roomWatch, g_roomStrong, g_roomAPlus,
      minimumCandidateRoom, averageCandidateRoom, g_roomCandidateMaximumR
   );
   PrintFormat(
      "SNIPER_PERFORMANCE strategy=%s strategyVersion=%s directionProfile=%s runId=%s accountScope=%s accountLogin=%I64d originServerB64=%s strategyMode=%d resolved=%d stopped=%d protectedStops=%d timedOut=%d m1ManagedExits=%d hit1R=%d hit2R=%d hit3R=%d P1=%.2f P2=%.2f P3=%.2f expectancyR=%.5f totalR=%.5f averageMFE_R=%.5f averageMAE_R=%.5f averageProjectedR=%.5f averageScore=%.2f",
      SNIPER_STRATEGY_ID, SNIPER_STRATEGY_VERSION,
      EngineLineageProfile(), ResearchRunId(),
      CurrentAccountScope(), AccountInfoInteger(ACCOUNT_LOGIN),
      CurrentAccountServerB64(), InpStrategyMode,
      g_resolved, g_stopped, g_protectedStops, g_timedOut, g_m1ManagedExits,
      g_oneR, g_twoR, g_threeR,
      p1, p2, p3, expectancy, g_totalOutcomeR, averageMfe, averageMae,
      averageProjected, averageScore
   );
}

void ReleaseHandle(int &handle)
{
   if(handle != INVALID_HANDLE)
   {
      IndicatorRelease(handle);
      handle = INVALID_HANDLE;
   }
}
