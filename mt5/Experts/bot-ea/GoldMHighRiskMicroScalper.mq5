#property copyright "bot-ea"
#property version   "1.00"
#property strict
#property description "GoldM High-Risk Micro Scalper Revisi for GOLDm#."

#include <Trade/Trade.mqh>

enum CapitalMode
{
   CAPITAL_MIN_BALANCE_EQUITY = 0
};

enum MarketRegime
{
   REGIME_NO_TRADE = 0,
   REGIME_TREND    = 1,
   REGIME_RANGE    = 2
};

enum TradeSide
{
   SIDE_BUY  = 0,
   SIDE_SELL = 1
};

enum TrendEntryMode
{
   TREND_ENTRY_DONCHIAN_BREAK = 0,
   TREND_ENTRY_PULLBACK       = 1,
   TREND_ENTRY_BREAK_OR_PULL  = 2
};

enum SignalModel
{
   SIGNAL_MODEL_SCORE_REVISED    = 0,
   SIGNAL_MODEL_EMA_RSI_ATR_MOMO = 1
};

input string          InpExpectedSymbol                  = "GOLDm#";
input ulong           InpMagicNumber                     = 26050501;
input int             InpDeviationPoints                 = 20;

input bool            InpAutoEquitySizing                = true;
input CapitalMode     InpCapitalMode                     = CAPITAL_MIN_BALANCE_EQUITY;
input double          InpEquityPerLotStep                = 100.0;
input double          InpLotIncrement                    = 0.10;
input double          InpMaxLotCap                       = 2.0;
input double          InpMinimumCapitalToTrade           = 0.0;

input int             InpMaxPositions                    = 3;
input bool            InpAllowBuySellSameTime            = false;
input bool            InpAllowAveraging                  = true;
input double          InpMinDistanceBetweenEntryMin      = 0.10;
input double          InpMinDistanceBetweenEntryATRMult  = 0.25;
input double          InpMaxTotalOpenLot                 = 2.0;

input ENUM_TIMEFRAMES InpTimeframeEntry                  = PERIOD_M1;
input ENUM_TIMEFRAMES InpConfirmTimeframe                = PERIOD_M5;
input int             InpEMAFast                         = 8;
input int             InpEMASlow                         = 21;
input int             InpEMAFilterM5                     = 50;
input int             InpRSIPeriod                       = 2;
input double          InpRSIOversold                     = 30.0;
input double          InpRSIOverbought                   = 70.0;
input int             InpATRPeriod                       = 14;
input int             InpADXPeriod                       = 7;
input int             InpDonchianPeriod                  = 5;
input int             InpBollingerPeriod                 = 20;
input double          InpBollingerDeviation              = 2.0;

input SignalModel     InpSignalModel                     = SIGNAL_MODEL_SCORE_REVISED;
input ENUM_TIMEFRAMES InpTrendMATimeframe                = PERIOD_M1;
input int             InpTrendMAFast                     = 50;
input int             InpTrendMASlow                     = 200;
input double          InpRSIMomentumBuy                  = 52.0;
input double          InpRSIMomentumSell                 = 48.0;
input bool            InpUseClosedBarBreakout            = false;
input int             InpMicroStructureBars              = 8;
input bool            InpUseSessionFilter                = false;
input int             InpSession1StartHour               = 7;
input int             InpSession1EndHour                 = 11;
input int             InpSession2StartHour               = 13;
input int             InpSession2EndHour                 = 17;

input double          InpTrendADXOn                      = 22.0;
input double          InpRangeADXOn                      = 16.0;
input bool            InpUseDIDirectionFilter            = false;
input double          InpMinDIDifference                 = 0.0;
input bool            InpUseAdxRisingFilter              = false;
input double          InpBandProximityATRMult            = 0.0;
input TrendEntryMode  InpTrendEntryMode                  = TREND_ENTRY_DONCHIAN_BREAK;
input double          InpTrendPullbackATRMult            = 0.15;
input int             InpTrendThreshold                  = 70;
input int             InpRangeThreshold                  = 75;
input int             InpTrendAddThreshold               = 75;
input int             InpRangeAddThreshold               = 80;

input double          InpMaxSpread                       = 0.30;
input double          InpHardMaxSpread                   = 0.50;
input bool            InpUseSpreadAtrGate                = false;
input double          InpMaxSpreadATRMult                = 0.20;
input double          InpMinAtrSpreadRatio               = 5.0;

input bool            InpUseDynamicProfitLock            = true;
input double          InpLockStartMin                    = 0.08;
input double          InpLockStartMax                    = 0.20;
input double          InpLockStartATRMult                = 0.20;
input double          InpTrailBackMin                    = 0.03;
input double          InpTrailBackMax                    = 0.08;
input double          InpTrailBackATRMult                = 0.08;
input bool            InpUseCostAwareProfitLock          = false;
input double          InpLockStartSpreadMult             = 1.20;
input double          InpTrailBackSpreadMult             = 0.60;

input double          InpEmergencySLMin                  = 0.80;
input double          InpEmergencySLMax                  = 1.50;
input double          InpEmergencySLATRMult              = 1.50;
input bool            InpUseAtrTakeProfit                = false;
input double          InpTakeProfitMin                   = 0.10;
input double          InpTakeProfitMax                   = 0.60;
input double          InpTakeProfitATRMult               = 1.20;

input int             InpMaxHoldSeconds                  = 90;
input int             InpCooldownAfterEntrySeconds       = 5;
input int             InpCooldownAfterCloseSeconds       = 3;
input int             InpReverseCloseMinSeconds          = 0;
input int             InpReverseCloseOppositeScore       = 65;
input int             InpWeakSignalCloseScore            = 45;

input double          InpMaxDailyLossPercent             = 5.0;
input double          InpMaxEquityDrawdownStop           = 10.0;
input int             InpMaxConsecutiveLoss              = 3;
input int             InpPauseAfterLossMinutes           = 10;
input bool            InpNoTradeDuringRollover           = true;
input int             InpRolloverStartHour               = 23;
input int             InpRolloverStartMinute             = 55;
input int             InpRolloverEndHour                 = 0;
input int             InpRolloverEndMinute               = 10;
input bool            InpFreeMarginCheck                 = true;
input double          InpMaxBasketFloatingLossPercent    = 1.5;

struct IndicatorSnapshot
{
   bool   ready;
   double emaFast1;
   double emaFast2;
   double emaSlow1;
   double emaFilterM5;
   double rsi1;
   double rsi2;
   double atr1;
   double atrAverage;
   double adx1;
   double adx2;
   double plusDI1;
   double minusDI1;
   double bbUpper1;
   double bbMiddle1;
   double bbLower1;
   double trendMAFast1;
   double trendMASlow1;
   double close1;
   double open1;
   double high1;
   double low1;
   double close2;
   double open2;
};

struct TicketState
{
   ulong    ticket;
   bool     lockActive;
   double   peakNetMove;
   datetime openTime;
};

CTrade        g_trade;
MarketRegime  g_lastRegime = REGIME_NO_TRADE;
TicketState   g_states[];

int g_emaFastHandle = INVALID_HANDLE;
int g_emaSlowHandle = INVALID_HANDLE;
int g_emaFilterHandle = INVALID_HANDLE;
int g_rsiHandle = INVALID_HANDLE;
int g_atrHandle = INVALID_HANDLE;
int g_adxHandle = INVALID_HANDLE;
int g_bandsHandle = INVALID_HANDLE;
int g_trendMAFastHandle = INVALID_HANDLE;
int g_trendMASlowHandle = INVALID_HANDLE;

double   g_lastBid = 0.0;
double   g_lastAsk = 0.0;
datetime g_lastEntryTime = 0;
datetime g_lastCloseTime = 0;
bool     g_closeFailureActive = false;
double   g_peakEquity = 0.0;
double   g_dayStartEquity = 0.0;
int      g_currentDayOfYear = -1;
int      g_consecutiveLosses = 0;
datetime g_lastLossTime = 0;

long g_diagTicks = 0;
long g_diagIndicatorReady = 0;
long g_diagSpreadOk = 0;
long g_diagRegimeTrend = 0;
long g_diagRegimeRange = 0;
long g_diagRegimeNoTrade = 0;
long g_diagTrendBuyCandidate = 0;
long g_diagTrendSellCandidate = 0;
long g_diagRangeBuyCandidate = 0;
long g_diagRangeSellCandidate = 0;
long g_diagCanOpenOk = 0;
long g_diagCanOpenBlocked = 0;
long g_diagDirectionBlocked = 0;
long g_diagOpenedBuy = 0;
long g_diagOpenedSell = 0;
long g_diagClosed = 0;

const double ATR_SPIKE_MULTIPLIER = 2.0;
const double ATR_DEAD_TICKS = 2.0;
const double TREND_ADX_KEEP = 18.0;
const double RANGE_ADX_KEEP = 20.0;

int OnInit()
{
   if(_Symbol != InpExpectedSymbol)
   {
      PrintFormat("EA is configured for %s but chart/test symbol is %s", InpExpectedSymbol, _Symbol);
      return INIT_FAILED;
   }

   g_trade.SetExpertMagicNumber((long)InpMagicNumber);
   g_trade.SetDeviationInPoints(InpDeviationPoints);

   g_emaFastHandle = iMA(_Symbol, InpTimeframeEntry, InpEMAFast, 0, MODE_EMA, PRICE_CLOSE);
   g_emaSlowHandle = iMA(_Symbol, InpTimeframeEntry, InpEMASlow, 0, MODE_EMA, PRICE_CLOSE);
   g_emaFilterHandle = iMA(_Symbol, InpConfirmTimeframe, InpEMAFilterM5, 0, MODE_EMA, PRICE_CLOSE);
   g_rsiHandle = iRSI(_Symbol, InpTimeframeEntry, InpRSIPeriod, PRICE_CLOSE);
   g_atrHandle = iATR(_Symbol, InpTimeframeEntry, InpATRPeriod);
   g_adxHandle = iADX(_Symbol, InpTimeframeEntry, InpADXPeriod);
   g_bandsHandle = iBands(_Symbol, InpTimeframeEntry, InpBollingerPeriod, 0, InpBollingerDeviation, PRICE_CLOSE);
   g_trendMAFastHandle = iMA(_Symbol, InpTrendMATimeframe, InpTrendMAFast, 0, MODE_EMA, PRICE_CLOSE);
   g_trendMASlowHandle = iMA(_Symbol, InpTrendMATimeframe, InpTrendMASlow, 0, MODE_EMA, PRICE_CLOSE);

   if(g_emaFastHandle == INVALID_HANDLE || g_emaSlowHandle == INVALID_HANDLE ||
      g_emaFilterHandle == INVALID_HANDLE || g_rsiHandle == INVALID_HANDLE ||
      g_atrHandle == INVALID_HANDLE || g_adxHandle == INVALID_HANDLE ||
      g_bandsHandle == INVALID_HANDLE || g_trendMAFastHandle == INVALID_HANDLE ||
      g_trendMASlowHandle == INVALID_HANDLE)
   {
      Print("Failed to create one or more indicator handles");
      return INIT_FAILED;
   }

   PrintSymbolInfo();
   g_peakEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   ResetDailyStateIfNeeded();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   PrintDiagnosticSummary();
   PrintPerformanceSummary();
   if(g_emaFastHandle != INVALID_HANDLE) IndicatorRelease(g_emaFastHandle);
   if(g_emaSlowHandle != INVALID_HANDLE) IndicatorRelease(g_emaSlowHandle);
   if(g_emaFilterHandle != INVALID_HANDLE) IndicatorRelease(g_emaFilterHandle);
   if(g_rsiHandle != INVALID_HANDLE) IndicatorRelease(g_rsiHandle);
   if(g_atrHandle != INVALID_HANDLE) IndicatorRelease(g_atrHandle);
   if(g_adxHandle != INVALID_HANDLE) IndicatorRelease(g_adxHandle);
   if(g_bandsHandle != INVALID_HANDLE) IndicatorRelease(g_bandsHandle);
   if(g_trendMAFastHandle != INVALID_HANDLE) IndicatorRelease(g_trendMAFastHandle);
   if(g_trendMASlowHandle != INVALID_HANDLE) IndicatorRelease(g_trendMASlowHandle);
}

void OnTick()
{
   g_diagTicks++;
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   ResetDailyStateIfNeeded();
   UpdateClosedTradeStats();
   SyncTicketStates();

   const double bid = tick.bid;
   const double ask = tick.ask;
   const double spread = ask - bid;
   const bool tickUp = (g_lastBid > 0.0 && bid > g_lastBid);
   const bool tickDown = (g_lastAsk > 0.0 && ask < g_lastAsk);

   IndicatorSnapshot snap;
   ZeroMemory(snap);
   snap.ready = LoadIndicators(snap);
   if(!snap.ready)
   {
      g_lastBid = bid;
      g_lastAsk = ask;
      return;
   }
   g_diagIndicatorReady++;
   if(spread <= InpMaxSpread)
      g_diagSpreadOk++;

   MarketRegime regime = DetectRegime(snap, bid, ask, spread);
   CountRegime(regime);
   const int trendBuyScore = ScoreTrendBuy(snap, ask, spread, tickUp);
   const int trendSellScore = ScoreTrendSell(snap, bid, spread, tickDown);
   const int rangeBuyScore = ScoreRangeBuy(snap, bid, spread, tickUp);
   const int rangeSellScore = ScoreRangeSell(snap, ask, spread, tickDown);

   ManageOpenPositions(snap, bid, ask, trendBuyScore, trendSellScore, rangeBuyScore, rangeSellScore);

   string reason = "";
   const double lot = CalculateAutoLot();
   if(!CanOpenNewTrade(lot, spread, snap, reason))
   {
      g_diagCanOpenBlocked++;
      g_lastRegime = regime;
      g_lastBid = bid;
      g_lastAsk = ask;
      return;
   }
   g_diagCanOpenOk++;

   bool opened = false;
   if(regime == REGIME_TREND)
   {
      const int buyThreshold = DirectionPositionCount(SIDE_BUY) > 0 ? InpTrendAddThreshold : InpTrendThreshold;
      const int sellThreshold = DirectionPositionCount(SIDE_SELL) > 0 ? InpTrendAddThreshold : InpTrendThreshold;
      const bool buyValid = (trendBuyScore >= buyThreshold && trendSellScore < 60);
      const bool sellValid = (trendSellScore >= sellThreshold && trendBuyScore < 60);
      if(buyValid) g_diagTrendBuyCandidate++;
      if(sellValid) g_diagTrendSellCandidate++;

      if(buyValid && !sellValid && CanOpenDirection(SIDE_BUY, lot, ask, snap, reason))
         opened = OpenMarketPosition(SIDE_BUY, lot, snap, "trend-buy");
      else if(buyValid && !sellValid)
         g_diagDirectionBlocked++;
      else if(sellValid && !buyValid && CanOpenDirection(SIDE_SELL, lot, bid, snap, reason))
         opened = OpenMarketPosition(SIDE_SELL, lot, snap, "trend-sell");
      else if(sellValid && !buyValid)
         g_diagDirectionBlocked++;
   }
   else if(regime == REGIME_RANGE)
   {
      const int buyThreshold = DirectionPositionCount(SIDE_BUY) > 0 ? InpRangeAddThreshold : InpRangeThreshold;
      const int sellThreshold = DirectionPositionCount(SIDE_SELL) > 0 ? InpRangeAddThreshold : InpRangeThreshold;
      const bool buyValid = (rangeBuyScore >= buyThreshold && rangeSellScore < 65);
      const bool sellValid = (rangeSellScore >= sellThreshold && rangeBuyScore < 65);
      if(buyValid) g_diagRangeBuyCandidate++;
      if(sellValid) g_diagRangeSellCandidate++;

      if(buyValid && !sellValid && CanOpenDirection(SIDE_BUY, lot, ask, snap, reason))
         opened = OpenMarketPosition(SIDE_BUY, lot, snap, "range-buy");
      else if(buyValid && !sellValid)
         g_diagDirectionBlocked++;
      else if(sellValid && !buyValid && CanOpenDirection(SIDE_SELL, lot, bid, snap, reason))
         opened = OpenMarketPosition(SIDE_SELL, lot, snap, "range-sell");
      else if(sellValid && !buyValid)
         g_diagDirectionBlocked++;
   }

   if(opened)
      SyncTicketStates();

   g_lastRegime = regime;
   g_lastBid = bid;
   g_lastAsk = ask;
}

double OnTester()
{
   return TesterStatistics(STAT_PROFIT_FACTOR);
}

bool LoadIndicators(IndicatorSnapshot &snap)
{
   double emaFast[], emaSlow[], emaFilter[], trendMAFast[], trendMASlow[], rsi[], atr[], adx[], plusDI[], minusDI[];
   double bbMiddle[], bbUpper[], bbLower[];
   ArrayResize(emaFast, 4);
   ArrayResize(emaSlow, 4);
   ArrayResize(emaFilter, 3);
   ArrayResize(trendMAFast, 3);
   ArrayResize(trendMASlow, 3);
   ArrayResize(rsi, 4);
   ArrayResize(atr, 32);
   ArrayResize(adx, 4);
   ArrayResize(plusDI, 4);
   ArrayResize(minusDI, 4);
   ArrayResize(bbMiddle, 4);
   ArrayResize(bbUpper, 4);
   ArrayResize(bbLower, 4);
   ArraySetAsSeries(emaFast, true);
   ArraySetAsSeries(emaSlow, true);
   ArraySetAsSeries(emaFilter, true);
   ArraySetAsSeries(trendMAFast, true);
   ArraySetAsSeries(trendMASlow, true);
   ArraySetAsSeries(rsi, true);
   ArraySetAsSeries(atr, true);
   ArraySetAsSeries(adx, true);
   ArraySetAsSeries(plusDI, true);
   ArraySetAsSeries(minusDI, true);
   ArraySetAsSeries(bbMiddle, true);
   ArraySetAsSeries(bbUpper, true);
   ArraySetAsSeries(bbLower, true);

   if(CopyBuffer(g_emaFastHandle, 0, 0, 4, emaFast) < 4) return false;
   if(CopyBuffer(g_emaSlowHandle, 0, 0, 4, emaSlow) < 4) return false;
   if(CopyBuffer(g_emaFilterHandle, 0, 0, 3, emaFilter) < 3) return false;
   if(CopyBuffer(g_trendMAFastHandle, 0, 0, 3, trendMAFast) < 3) return false;
   if(CopyBuffer(g_trendMASlowHandle, 0, 0, 3, trendMASlow) < 3) return false;
   if(CopyBuffer(g_rsiHandle, 0, 0, 4, rsi) < 4) return false;
   if(CopyBuffer(g_atrHandle, 0, 0, 32, atr) < 16) return false;
   if(CopyBuffer(g_adxHandle, 0, 0, 4, adx) < 4) return false;
   if(CopyBuffer(g_adxHandle, 1, 0, 4, plusDI) < 4) return false;
   if(CopyBuffer(g_adxHandle, 2, 0, 4, minusDI) < 4) return false;
   if(CopyBuffer(g_bandsHandle, 0, 0, 4, bbMiddle) < 4) return false;
   if(CopyBuffer(g_bandsHandle, 1, 0, 4, bbUpper) < 4) return false;
   if(CopyBuffer(g_bandsHandle, 2, 0, 4, bbLower) < 4) return false;

   snap.emaFast1 = emaFast[1];
   snap.emaFast2 = emaFast[2];
   snap.emaSlow1 = emaSlow[1];
   snap.emaFilterM5 = emaFilter[1];
   snap.rsi1 = rsi[1];
   snap.rsi2 = rsi[2];
   snap.atr1 = atr[1];
   snap.atrAverage = AverageAtrFromBuffer(atr, 31);
   snap.adx1 = adx[1];
   snap.adx2 = adx[2];
   snap.plusDI1 = plusDI[1];
   snap.minusDI1 = minusDI[1];
   snap.bbMiddle1 = bbMiddle[1];
   snap.bbUpper1 = bbUpper[1];
   snap.bbLower1 = bbLower[1];
   snap.trendMAFast1 = trendMAFast[1];
   snap.trendMASlow1 = trendMASlow[1];
   snap.open1 = iOpen(_Symbol, InpTimeframeEntry, 1);
   snap.close1 = iClose(_Symbol, InpTimeframeEntry, 1);
   snap.high1 = iHigh(_Symbol, InpTimeframeEntry, 1);
   snap.low1 = iLow(_Symbol, InpTimeframeEntry, 1);
   snap.open2 = iOpen(_Symbol, InpTimeframeEntry, 2);
   snap.close2 = iClose(_Symbol, InpTimeframeEntry, 2);
   return true;
}

double AverageAtrFromBuffer(const double &atr[], const int maxIndex)
{
   double total = 0.0;
   int count = 0;
   for(int i = 1; i <= maxIndex && i <= 20; i++)
   {
      if(atr[i] > 0.0)
      {
         total += atr[i];
         count++;
      }
   }
   if(count <= 0)
      return 0.0;
   return total / count;
}

MarketRegime DetectRegime(const IndicatorSnapshot &snap, const double bid, const double ask, const double spread)
{
   if(spread > InpHardMaxSpread)
      return REGIME_NO_TRADE;
   if(!AtrActiveAndNormal(snap))
      return REGIME_NO_TRADE;

   const double mid = (bid + ask) * 0.5;
   const bool emaUp = snap.emaFast1 > snap.emaSlow1 && snap.emaFast1 > snap.emaFast2;
   const bool emaDown = snap.emaFast1 < snap.emaSlow1 && snap.emaFast1 < snap.emaFast2;
   const bool diBuyOk = !InpUseDIDirectionFilter || snap.plusDI1 > snap.minusDI1 + InpMinDIDifference;
   const bool diSellOk = !InpUseDIDirectionFilter || snap.minusDI1 > snap.plusDI1 + InpMinDIDifference;
   const bool adxTrendOk = !InpUseAdxRisingFilter || snap.adx1 >= snap.adx2;
   const bool alignedUp = emaUp && mid > snap.emaFilterM5 && diBuyOk;
   const bool alignedDown = emaDown && mid < snap.emaFilterM5 && diSellOk;
   const bool alignedTrend = alignedUp || alignedDown;
   const bool insideBands = mid <= snap.bbUpper1 && mid >= snap.bbLower1;
   const bool breakoutSpike = IsBreakoutSpike(snap);

   if(InpSignalModel == SIGNAL_MODEL_EMA_RSI_ATR_MOMO)
   {
      const bool trendUp = snap.trendMAFast1 > snap.trendMASlow1 && mid > snap.trendMAFast1;
      const bool trendDown = snap.trendMAFast1 < snap.trendMASlow1 && mid < snap.trendMAFast1;
      if((trendUp || trendDown) && AtrActiveAndNormal(snap))
         return REGIME_TREND;
      return REGIME_NO_TRADE;
   }

   if(snap.adx1 > InpTrendADXOn && alignedTrend && adxTrendOk)
      return REGIME_TREND;

   if(snap.adx1 < InpRangeADXOn && insideBands && !breakoutSpike)
      return REGIME_RANGE;

   if(g_lastRegime == REGIME_TREND && snap.adx1 > TREND_ADX_KEEP && alignedTrend)
      return REGIME_TREND;

   if(g_lastRegime == REGIME_RANGE && snap.adx1 < RANGE_ADX_KEEP && insideBands && !breakoutSpike)
      return REGIME_RANGE;

   return REGIME_NO_TRADE;
}

int ScoreTrendBuy(const IndicatorSnapshot &snap, const double ask, const double spread, const bool tickUp)
{
   if(InpSignalModel == SIGNAL_MODEL_EMA_RSI_ATR_MOMO)
      return ScoreMomentumBuy(snap, ask, spread, tickUp);

   int score = 0;
   if(snap.emaFast1 > snap.emaSlow1) score += 20;
   if(snap.emaFast1 > snap.emaFast2) score += 15;
   if(ask > snap.emaFilterM5) score += 20;
   if(snap.adx1 > InpTrendADXOn) score += 15;
   if(InpUseDIDirectionFilter && snap.plusDI1 > snap.minusDI1 + InpMinDIDifference) score += 10;
   if(AtrActiveAndNormal(snap)) score += 10;
   if(TrendBuyTrigger(snap, ask, spread)) score += 15;
   if(tickUp) score += 10;
   if(RsiReboundBuy(snap)) score += 10;
   if(spread > InpMaxSpread) score -= 40;
   if(spread > InpHardMaxSpread) score -= 100;
   return score;
}

int ScoreTrendSell(const IndicatorSnapshot &snap, const double bid, const double spread, const bool tickDown)
{
   if(InpSignalModel == SIGNAL_MODEL_EMA_RSI_ATR_MOMO)
      return ScoreMomentumSell(snap, bid, spread, tickDown);

   int score = 0;
   if(snap.emaFast1 < snap.emaSlow1) score += 20;
   if(snap.emaFast1 < snap.emaFast2) score += 15;
   if(bid < snap.emaFilterM5) score += 20;
   if(snap.adx1 > InpTrendADXOn) score += 15;
   if(InpUseDIDirectionFilter && snap.minusDI1 > snap.plusDI1 + InpMinDIDifference) score += 10;
   if(AtrActiveAndNormal(snap)) score += 10;
   if(TrendSellTrigger(snap, bid, spread)) score += 15;
   if(tickDown) score += 10;
   if(RsiReboundSell(snap)) score += 10;
   if(spread > InpMaxSpread) score -= 40;
   if(spread > InpHardMaxSpread) score -= 100;
   return score;
}

int ScoreRangeBuy(const IndicatorSnapshot &snap, const double bid, const double spread, const bool tickUp)
{
   if(InpSignalModel == SIGNAL_MODEL_EMA_RSI_ATR_MOMO)
      return 0;

   int score = 0;
   if(snap.adx1 < InpRangeADXOn) score += 20;
   if(AtrActiveAndNormal(snap)) score += 15;
   if(NearLowerBand(snap, bid, spread)) score += 20;
   if(RsiReboundBuy(snap)) score += 20;
   if(RejectionFromBelow(snap)) score += 15;
   if(tickUp) score += 10;
   if(spread > InpMaxSpread) score -= 40;
   if(spread > InpHardMaxSpread) score -= 100;
   return score;
}

int ScoreRangeSell(const IndicatorSnapshot &snap, const double ask, const double spread, const bool tickDown)
{
   if(InpSignalModel == SIGNAL_MODEL_EMA_RSI_ATR_MOMO)
      return 0;

   int score = 0;
   if(snap.adx1 < InpRangeADXOn) score += 20;
   if(AtrActiveAndNormal(snap)) score += 15;
   if(NearUpperBand(snap, ask, spread)) score += 20;
   if(RsiReboundSell(snap)) score += 20;
   if(RejectionFromAbove(snap)) score += 15;
   if(tickDown) score += 10;
   if(spread > InpMaxSpread) score -= 40;
   if(spread > InpHardMaxSpread) score -= 100;
   return score;
}

int ScoreMomentumBuy(const IndicatorSnapshot &snap, const double ask, const double spread, const bool tickUp)
{
   int score = 0;
   if(snap.trendMAFast1 > snap.trendMASlow1) score += 25;
   if(snap.close1 > snap.trendMAFast1) score += 15;
   if(snap.emaFast1 > snap.emaSlow1) score += 10;
   if(snap.rsi1 >= InpRSIMomentumBuy) score += 15;
   if(AtrActiveAndNormal(snap)) score += 10;
   if(snap.close1 > snap.open1) score += 10;
   if(MomentumBreakoutBuy(snap, ask) || TrendPullbackBuy(snap, ask, spread)) score += 15;
   if(tickUp) score += 5;
   if(spread > InpMaxSpread) score -= 40;
   if(spread > InpHardMaxSpread) score -= 100;
   return score;
}

int ScoreMomentumSell(const IndicatorSnapshot &snap, const double bid, const double spread, const bool tickDown)
{
   int score = 0;
   if(snap.trendMAFast1 < snap.trendMASlow1) score += 25;
   if(snap.close1 < snap.trendMAFast1) score += 15;
   if(snap.emaFast1 < snap.emaSlow1) score += 10;
   if(snap.rsi1 <= InpRSIMomentumSell) score += 15;
   if(AtrActiveAndNormal(snap)) score += 10;
   if(snap.close1 < snap.open1) score += 10;
   if(MomentumBreakoutSell(snap, bid) || TrendPullbackSell(snap, bid, spread)) score += 15;
   if(tickDown) score += 5;
   if(spread > InpMaxSpread) score -= 40;
   if(spread > InpHardMaxSpread) score -= 100;
   return score;
}

bool AtrActiveAndNormal(const IndicatorSnapshot &snap)
{
   const double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(snap.atr1 <= MathMax(tickSize * ATR_DEAD_TICKS, 0.0))
      return false;
   if(snap.atrAverage > 0.0 && snap.atr1 > snap.atrAverage * ATR_SPIKE_MULTIPLIER)
      return false;
   return true;
}

bool IsBreakoutSpike(const IndicatorSnapshot &snap)
{
   const double candleRange = snap.high1 - snap.low1;
   if(snap.atr1 > 0.0 && candleRange > snap.atr1 * 1.5)
      return true;
   if(snap.close1 > snap.bbUpper1 || snap.close1 < snap.bbLower1)
      return true;
   return false;
}

bool RsiReboundBuy(const IndicatorSnapshot &snap)
{
   return (snap.rsi2 <= InpRSIOversold && snap.rsi1 > snap.rsi2);
}

bool RsiReboundSell(const IndicatorSnapshot &snap)
{
   return (snap.rsi2 >= InpRSIOverbought && snap.rsi1 < snap.rsi2);
}

bool TrendBuyTrigger(const IndicatorSnapshot &snap, const double ask, const double spread)
{
   if(InpTrendEntryMode == TREND_ENTRY_DONCHIAN_BREAK)
      return BreaksDonchianHigh(ask);
   if(InpTrendEntryMode == TREND_ENTRY_PULLBACK)
      return TrendPullbackBuy(snap, ask, spread);
   return BreaksDonchianHigh(ask) || TrendPullbackBuy(snap, ask, spread);
}

bool TrendSellTrigger(const IndicatorSnapshot &snap, const double bid, const double spread)
{
   if(InpTrendEntryMode == TREND_ENTRY_DONCHIAN_BREAK)
      return BreaksDonchianLow(bid);
   if(InpTrendEntryMode == TREND_ENTRY_PULLBACK)
      return TrendPullbackSell(snap, bid, spread);
   return BreaksDonchianLow(bid) || TrendPullbackSell(snap, bid, spread);
}

bool TrendPullbackBuy(const IndicatorSnapshot &snap, const double ask, const double spread)
{
   const double tolerance = MathMax(spread, snap.atr1 * InpTrendPullbackATRMult);
   const bool touchedFast = snap.low1 <= snap.emaFast1 + tolerance;
   const bool touchedSlow = snap.low1 <= snap.emaSlow1 + tolerance;
   const bool reclaimed = ask > snap.emaFast1 && snap.close1 >= snap.emaFast1;
   return (touchedFast || touchedSlow) && reclaimed;
}

bool TrendPullbackSell(const IndicatorSnapshot &snap, const double bid, const double spread)
{
   const double tolerance = MathMax(spread, snap.atr1 * InpTrendPullbackATRMult);
   const bool touchedFast = snap.high1 >= snap.emaFast1 - tolerance;
   const bool touchedSlow = snap.high1 >= snap.emaSlow1 - tolerance;
   const bool reclaimed = bid < snap.emaFast1 && snap.close1 <= snap.emaFast1;
   return (touchedFast || touchedSlow) && reclaimed;
}

bool NearLowerBand(const IndicatorSnapshot &snap, const double bid, const double spread)
{
   const double tolerance = MathMax(MathMax(spread, SymbolPoint()), snap.atr1 * InpBandProximityATRMult);
   return bid <= snap.bbLower1 + tolerance;
}

bool NearUpperBand(const IndicatorSnapshot &snap, const double ask, const double spread)
{
   const double tolerance = MathMax(MathMax(spread, SymbolPoint()), snap.atr1 * InpBandProximityATRMult);
   return ask >= snap.bbUpper1 - tolerance;
}

bool RejectionFromBelow(const IndicatorSnapshot &snap)
{
   const double body = MathAbs(snap.close1 - snap.open1);
   const double lowerWick = MathMin(snap.close1, snap.open1) - snap.low1;
   return snap.close1 > snap.open1 && lowerWick > body;
}

bool RejectionFromAbove(const IndicatorSnapshot &snap)
{
   const double body = MathAbs(snap.close1 - snap.open1);
   const double upperWick = snap.high1 - MathMax(snap.close1, snap.open1);
   return snap.close1 < snap.open1 && upperWick > body;
}

bool BreaksDonchianHigh(const double price)
{
   double highest = -DBL_MAX;
   for(int i = 1; i <= InpDonchianPeriod; i++)
      highest = MathMax(highest, iHigh(_Symbol, InpTimeframeEntry, i));
   return price > highest;
}

bool BreaksDonchianLow(const double price)
{
   double lowest = DBL_MAX;
   for(int i = 1; i <= InpDonchianPeriod; i++)
      lowest = MathMin(lowest, iLow(_Symbol, InpTimeframeEntry, i));
   return price < lowest;
}

bool MomentumBreakoutBuy(const IndicatorSnapshot &snap, const double price)
{
   if(!InpUseClosedBarBreakout)
      return BreaksDonchianHigh(price);

   double highest = -DBL_MAX;
   for(int i = 2; i <= InpMicroStructureBars + 1; i++)
      highest = MathMax(highest, iHigh(_Symbol, InpTimeframeEntry, i));
   return snap.close1 > highest;
}

bool MomentumBreakoutSell(const IndicatorSnapshot &snap, const double price)
{
   if(!InpUseClosedBarBreakout)
      return BreaksDonchianLow(price);

   double lowest = DBL_MAX;
   for(int i = 2; i <= InpMicroStructureBars + 1; i++)
      lowest = MathMin(lowest, iLow(_Symbol, InpTimeframeEntry, i));
   return snap.close1 < lowest;
}

void ManageOpenPositions(
   const IndicatorSnapshot &snap,
   const double bid,
   const double ask,
   const int trendBuyScore,
   const int trendSellScore,
   const int rangeBuyScore,
   const int rangeSellScore
)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsManagedPosition())
         continue;

      const long type = PositionGetInteger(POSITION_TYPE);
      const double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      const double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      const datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);
      const int ageSeconds = (int)(TimeCurrent() - openTime);
      const int stateIndex = EnsureTicketState(ticket, openTime);
      const double netMove = (type == POSITION_TYPE_BUY) ? (bid - openPrice) : (openPrice - ask);
      const double spread = ask - bid;
      const double lockStart = DynamicLockStart(snap.atr1, spread);
      const double trailBack = DynamicTrailBack(snap.atr1, spread);
      const double emergencySL = DynamicEmergencySL(snap.atr1);
      bool shouldClose = false;
      string closeReason = "";

      if(netMove >= lockStart)
         g_states[stateIndex].lockActive = true;

      if(g_states[stateIndex].lockActive)
      {
         if(netMove > g_states[stateIndex].peakNetMove)
            g_states[stateIndex].peakNetMove = netMove;
         if(netMove <= g_states[stateIndex].peakNetMove - trailBack && profit > 0.0)
         {
            shouldClose = true;
            closeReason = "dynamic profit lock";
         }
      }
      else if(netMove > g_states[stateIndex].peakNetMove)
      {
         g_states[stateIndex].peakNetMove = netMove;
      }

      if(!shouldClose && netMove <= -emergencySL)
      {
         shouldClose = true;
         closeReason = "emergency sl";
      }

      if(!shouldClose && ageSeconds >= InpMaxHoldSeconds)
      {
         if(profit > 0.0)
         {
            shouldClose = true;
            closeReason = "max hold profit";
         }
         else if(ReverseOrWeakSignal(type, trendBuyScore, trendSellScore, rangeBuyScore, rangeSellScore))
         {
            shouldClose = true;
            closeReason = "max hold weak or reverse";
         }
      }

      if(!shouldClose && ageSeconds >= InpReverseCloseMinSeconds &&
         ReverseOrWeakSignal(type, trendBuyScore, trendSellScore, rangeBuyScore, rangeSellScore))
      {
         if(netMove > 0.0 || MathAbs(netMove) < DynamicEmergencySL(snap.atr1) * 0.35)
         {
            shouldClose = true;
            closeReason = "reverse signal";
         }
      }

      if(shouldClose)
         ClosePosition(ticket, closeReason);
   }
}

bool ReverseOrWeakSignal(const long positionType, const int trendBuyScore, const int trendSellScore, const int rangeBuyScore, const int rangeSellScore)
{
   const int buyBest = MathMax(trendBuyScore, rangeBuyScore);
   const int sellBest = MathMax(trendSellScore, rangeSellScore);
   if(positionType == POSITION_TYPE_BUY)
      return (sellBest >= InpReverseCloseOppositeScore || buyBest < InpWeakSignalCloseScore);
   return (buyBest >= InpReverseCloseOppositeScore || sellBest < InpWeakSignalCloseScore);
}

double DynamicLockStart(const double atr, const double spread)
{
   double value = InpLockStartMin;
   if(!InpUseDynamicProfitLock)
      value = InpLockStartMin;
   else
      value = Clamp(MathMax(InpLockStartMin, atr * InpLockStartATRMult), InpLockStartMin, InpLockStartMax);
   if(InpUseCostAwareProfitLock)
      value = MathMax(value, spread * InpLockStartSpreadMult);
   return value;
}

double DynamicTrailBack(const double atr, const double spread)
{
   double value = InpTrailBackMin;
   if(!InpUseDynamicProfitLock)
      value = InpTrailBackMin;
   else
      value = Clamp(MathMax(InpTrailBackMin, atr * InpTrailBackATRMult), InpTrailBackMin, InpTrailBackMax);
   if(InpUseCostAwareProfitLock)
      value = MathMax(value, spread * InpTrailBackSpreadMult);
   return value;
}

double DynamicEmergencySL(const double atr)
{
   return Clamp(MathMax(InpEmergencySLMin, atr * InpEmergencySLATRMult), InpEmergencySLMin, InpEmergencySLMax);
}

bool CanOpenNewTrade(const double lot, const double spread, const IndicatorSnapshot &snap, string &reason)
{
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(equity > g_peakEquity)
      g_peakEquity = equity;

   if(g_closeFailureActive)
   {
      reason = "previous close failed";
      return false;
   }
   if(spread > InpMaxSpread)
   {
      reason = "spread above max";
      return false;
   }
   if(spread > InpHardMaxSpread)
   {
      reason = "spread above hard max";
      return false;
   }
   if(InpUseSpreadAtrGate)
   {
      if(snap.atr1 <= 0.0)
      {
         reason = "atr unavailable for spread gate";
         return false;
      }
      if(spread > snap.atr1 * InpMaxSpreadATRMult)
      {
         reason = "spread above atr ratio";
         return false;
      }
      if(spread > 0.0 && snap.atr1 / spread < InpMinAtrSpreadRatio)
      {
         reason = "atr spread ratio too low";
         return false;
      }
   }
   if(lot <= 0.0)
   {
      reason = "lot is zero";
      return false;
   }
   if(InpMinimumCapitalToTrade > 0.0 && MathMin(balance, equity) < InpMinimumCapitalToTrade)
   {
      reason = "capital below minimum";
      return false;
   }
   if(DailyLossPercent() >= InpMaxDailyLossPercent)
   {
      reason = "daily loss limit reached";
      return false;
   }
   if(EquityDrawdownPercent() >= InpMaxEquityDrawdownStop)
   {
      reason = "equity drawdown stop reached";
      return false;
   }
   if(g_consecutiveLosses >= InpMaxConsecutiveLoss && TimeCurrent() < g_lastLossTime + InpPauseAfterLossMinutes * 60)
   {
      reason = "pause after consecutive losses";
      return false;
   }
   if(InpNoTradeDuringRollover && IsRolloverWindow())
   {
      reason = "rollover no-trade window";
      return false;
   }
   if(InpUseSessionFilter && !IsConfiguredSessionWindow())
   {
      reason = "outside configured session";
      return false;
   }
   if(TimeCurrent() < g_lastEntryTime + InpCooldownAfterEntrySeconds)
   {
      reason = "entry cooldown active";
      return false;
   }
   if(TimeCurrent() < g_lastCloseTime + InpCooldownAfterCloseSeconds)
   {
      reason = "close cooldown active";
      return false;
   }
   if(ManagedPositionCount() >= InpMaxPositions)
   {
      reason = "max positions reached";
      return false;
   }
   if(BasketFloatingLossPercent() >= InpMaxBasketFloatingLossPercent)
   {
      reason = "basket loss limit reached";
      return false;
   }
   if(TotalManagedLot() + lot > InpMaxTotalOpenLot + 1e-8)
   {
      reason = "max total open lot reached";
      return false;
   }
   return true;
}

bool CanOpenDirection(const TradeSide side, const double lot, const double price, const IndicatorSnapshot &snap, string &reason)
{
   const int sameCount = DirectionPositionCount(side);
   const int oppositeCount = DirectionPositionCount(side == SIDE_BUY ? SIDE_SELL : SIDE_BUY);

   if(oppositeCount > 0 && !InpAllowBuySellSameTime)
   {
      reason = "opposite direction position exists";
      return false;
   }
   if(sameCount > 0 && !InpAllowAveraging)
   {
      reason = "averaging disabled";
      return false;
   }
   if(sameCount > 0 && !HasMinimumEntryDistance(side, price, snap.atr1))
   {
      reason = "minimum entry distance not met";
      return false;
   }

   if(InpFreeMarginCheck)
   {
      ENUM_ORDER_TYPE orderType = side == SIDE_BUY ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double margin = 0.0;
      if(!OrderCalcMargin(orderType, _Symbol, lot, price, margin))
      {
         reason = "order margin calculation failed";
         return false;
      }
      if(AccountInfoDouble(ACCOUNT_MARGIN_FREE) <= margin)
      {
         reason = "insufficient free margin";
         return false;
      }
   }
   return true;
}

bool OpenMarketPosition(const TradeSide side, const double lot, const IndicatorSnapshot &snap, const string comment)
{
   const double sl = EmergencyStopPrice(side, snap.atr1);
   const double tp = TakeProfitPrice(side, snap.atr1);
   bool sent = false;
   if(side == SIDE_BUY)
      sent = g_trade.Buy(lot, _Symbol, 0.0, sl, tp, comment);
   else
      sent = g_trade.Sell(lot, _Symbol, 0.0, sl, tp, comment);

   const uint retcode = g_trade.ResultRetcode();
   PrintFormat("open %s lot=%.2f sl=%.5f tp=%.5f sent=%s retcode=%u %s order=%I64u deal=%I64u",
      comment, lot, sl, tp, sent ? "true" : "false", retcode, g_trade.ResultRetcodeDescription(),
      g_trade.ResultOrder(), g_trade.ResultDeal());

   if(IsTradeRetcodeSuccess(retcode))
   {
      g_lastEntryTime = TimeCurrent();
      if(side == SIDE_BUY)
         g_diagOpenedBuy++;
      else
         g_diagOpenedSell++;
      return true;
   }
   return false;
}

bool ClosePosition(const ulong ticket, const string reason)
{
   if(!PositionSelectByTicket(ticket))
      return true;
   const bool sent = g_trade.PositionClose(ticket, InpDeviationPoints);
   const uint retcode = g_trade.ResultRetcode();
   PrintFormat("close ticket=%I64u reason=%s sent=%s retcode=%u %s order=%I64u deal=%I64u",
      ticket, reason, sent ? "true" : "false", retcode, g_trade.ResultRetcodeDescription(),
      g_trade.ResultOrder(), g_trade.ResultDeal());

   if(IsTradeRetcodeSuccess(retcode))
   {
      g_lastCloseTime = TimeCurrent();
      g_closeFailureActive = false;
      g_diagClosed++;
      return true;
   }

   g_closeFailureActive = true;
   return false;
}

bool IsTradeRetcodeSuccess(const uint retcode)
{
   return retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_PLACED || retcode == TRADE_RETCODE_DONE_PARTIAL;
}

double CalculateAutoLot()
{
   if(!InpAutoEquitySizing)
      return NormalizeVolume(InpLotIncrement);

   const double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double capitalBase = MathMin(balance, equity);
   if(InpCapitalMode != CAPITAL_MIN_BALANCE_EQUITY)
      capitalBase = equity;

   if(InpMinimumCapitalToTrade > 0.0 && capitalBase < InpMinimumCapitalToTrade)
      return 0.0;
   if(InpEquityPerLotStep <= 0.0)
      return 0.0;

   const double steps = MathFloor(capitalBase / InpEquityPerLotStep);
   double rawLot = steps * InpLotIncrement;
   if(rawLot <= 0.0 && capitalBase > 0.0)
      rawLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   rawLot = MathMin(rawLot, InpMaxLotCap);
   return NormalizeVolume(rawLot);
}

double NormalizeVolume(const double volume)
{
   const double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   const double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   const double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      return 0.0;
   double clamped = MathMin(MathMax(volume, 0.0), MathMin(maxLot, InpMaxLotCap));
   double normalized = MathFloor((clamped + 1e-12) / step) * step;
   if(normalized < minLot)
      return 0.0;
   return NormalizeDouble(normalized, 8);
}

double EmergencyStopPrice(const TradeSide side, const double atr)
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return 0.0;

   const double distance = DynamicEmergencySL(atr);
   const double point = SymbolPoint();
   const long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   const double minStopDistance = stopsLevel * point;
   if(minStopDistance > 0.0 && distance < minStopDistance)
      return 0.0;

   const int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(side == SIDE_BUY)
      return NormalizeDouble(tick.ask - distance, digits);
   return NormalizeDouble(tick.bid + distance, digits);
}

double TakeProfitPrice(const TradeSide side, const double atr)
{
   if(!InpUseAtrTakeProfit)
      return 0.0;

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return 0.0;

   const double distance = Clamp(MathMax(InpTakeProfitMin, atr * InpTakeProfitATRMult), InpTakeProfitMin, InpTakeProfitMax);
   const double point = SymbolPoint();
   const long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   const double minStopDistance = stopsLevel * point;
   if(minStopDistance > 0.0 && distance < minStopDistance)
      return 0.0;

   const int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(side == SIDE_BUY)
      return NormalizeDouble(tick.ask + distance, digits);
   return NormalizeDouble(tick.bid - distance, digits);
}

bool HasMinimumEntryDistance(const TradeSide side, const double price, const double atr)
{
   const double required = MathMax(InpMinDistanceBetweenEntryMin, atr * InpMinDistanceBetweenEntryATRMult);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsManagedPosition())
         continue;
      const long type = PositionGetInteger(POSITION_TYPE);
      if((side == SIDE_BUY && type != POSITION_TYPE_BUY) || (side == SIDE_SELL && type != POSITION_TYPE_SELL))
         continue;
      const double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      if(MathAbs(price - openPrice) < required)
         return false;
   }
   return true;
}

int ManagedPositionCount()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket != 0 && PositionSelectByTicket(ticket) && IsManagedPosition())
         count++;
   }
   return count;
}

int DirectionPositionCount(const TradeSide side)
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsManagedPosition())
         continue;
      const long type = PositionGetInteger(POSITION_TYPE);
      if((side == SIDE_BUY && type == POSITION_TYPE_BUY) || (side == SIDE_SELL && type == POSITION_TYPE_SELL))
         count++;
   }
   return count;
}

double TotalManagedLot()
{
   double total = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket != 0 && PositionSelectByTicket(ticket) && IsManagedPosition())
         total += PositionGetDouble(POSITION_VOLUME);
   }
   return total;
}

double BasketFloatingLossPercent()
{
   double floating = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket != 0 && PositionSelectByTicket(ticket) && IsManagedPosition())
         floating += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   if(floating >= 0.0)
      return 0.0;
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity <= 0.0)
      return 100.0;
   return (-floating / equity) * 100.0;
}

bool IsManagedPosition()
{
   return PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagicNumber;
}

void SyncTicketStates()
{
   for(int s = ArraySize(g_states) - 1; s >= 0; s--)
   {
      if(!PositionSelectByTicket(g_states[s].ticket))
         RemoveStateAt(s);
   }

   if(ManagedPositionCount() == 0)
      g_closeFailureActive = false;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      const ulong ticket = PositionGetTicket(i);
      if(ticket != 0 && PositionSelectByTicket(ticket) && IsManagedPosition())
         EnsureTicketState(ticket, (datetime)PositionGetInteger(POSITION_TIME));
   }
}

int EnsureTicketState(const ulong ticket, const datetime openTime)
{
   for(int i = 0; i < ArraySize(g_states); i++)
   {
      if(g_states[i].ticket == ticket)
         return i;
   }
   const int size = ArraySize(g_states);
   ArrayResize(g_states, size + 1);
   g_states[size].ticket = ticket;
   g_states[size].lockActive = false;
   g_states[size].peakNetMove = 0.0;
   g_states[size].openTime = openTime;
   return size;
}

void RemoveStateAt(const int index)
{
   const int size = ArraySize(g_states);
   if(index < 0 || index >= size)
      return;
   for(int i = index; i < size - 1; i++)
      g_states[i] = g_states[i + 1];
   ArrayResize(g_states, size - 1);
}

void ResetDailyStateIfNeeded()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(g_currentDayOfYear == dt.day_of_year)
      return;
   g_currentDayOfYear = dt.day_of_year;
   g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_consecutiveLosses = 0;
   g_lastLossTime = 0;
}

void UpdateClosedTradeStats()
{
   datetime start = StartOfCurrentDay();
   if(!HistorySelect(start, TimeCurrent()))
      return;

   double lastProfit = 0.0;
   datetime lastTime = 0;
   int consecutive = 0;
   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber)
         continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;

      const double profit = HistoryDealGetDouble(deal, DEAL_PROFIT) +
                            HistoryDealGetDouble(deal, DEAL_SWAP) +
                            HistoryDealGetDouble(deal, DEAL_COMMISSION);
      const datetime closeTime = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
      if(closeTime >= lastTime)
      {
         lastTime = closeTime;
         lastProfit = profit;
      }
   }

   if(lastTime <= 0)
   {
      g_consecutiveLosses = 0;
      return;
   }

   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber)
         continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;

      const double profit = HistoryDealGetDouble(deal, DEAL_PROFIT) +
                            HistoryDealGetDouble(deal, DEAL_SWAP) +
                            HistoryDealGetDouble(deal, DEAL_COMMISSION);
      if(profit < 0.0)
         consecutive++;
      else if(profit > 0.0)
         consecutive = 0;
   }

   g_consecutiveLosses = consecutive;
   if(lastProfit < 0.0)
      g_lastLossTime = lastTime;
}

double DailyLossPercent()
{
   const double dailyProfit = DailyRealizedProfit();
   if(dailyProfit >= 0.0)
      return 0.0;
   if(g_dayStartEquity <= 0.0)
      return 100.0;
   return (-dailyProfit / g_dayStartEquity) * 100.0;
}

double DailyRealizedProfit()
{
   datetime start = StartOfCurrentDay();
   if(!HistorySelect(start, TimeCurrent()))
      return 0.0;

   double total = 0.0;
   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber)
         continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;
      total += HistoryDealGetDouble(deal, DEAL_PROFIT) +
               HistoryDealGetDouble(deal, DEAL_SWAP) +
               HistoryDealGetDouble(deal, DEAL_COMMISSION);
   }
   return total;
}

double EquityDrawdownPercent()
{
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > g_peakEquity)
      g_peakEquity = equity;
   if(g_peakEquity <= 0.0)
      return 0.0;
   return MathMax(0.0, (g_peakEquity - equity) / g_peakEquity * 100.0);
}

bool IsRolloverWindow()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   const int nowMinutes = dt.hour * 60 + dt.min;
   const int startMinutes = InpRolloverStartHour * 60 + InpRolloverStartMinute;
   const int endMinutes = InpRolloverEndHour * 60 + InpRolloverEndMinute;

   if(startMinutes <= endMinutes)
      return nowMinutes >= startMinutes && nowMinutes <= endMinutes;
   return nowMinutes >= startMinutes || nowMinutes <= endMinutes;
}

bool IsConfiguredSessionWindow()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   const int nowMinutes = dt.hour * 60 + dt.min;
   return IsWithinHourWindow(nowMinutes, InpSession1StartHour, InpSession1EndHour) ||
          IsWithinHourWindow(nowMinutes, InpSession2StartHour, InpSession2EndHour);
}

bool IsWithinHourWindow(const int nowMinutes, const int startHour, const int endHour)
{
   const int startMinutes = startHour * 60;
   const int endMinutes = endHour * 60;
   if(startHour == endHour)
      return false;
   if(startMinutes < endMinutes)
      return nowMinutes >= startMinutes && nowMinutes < endMinutes;
   return nowMinutes >= startMinutes || nowMinutes < endMinutes;
}

datetime StartOfCurrentDay()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0;
   dt.min = 0;
   dt.sec = 0;
   return StructToTime(dt);
}

double SymbolPoint()
{
   const double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point > 0.0)
      return point;
   return 0.01;
}

double Clamp(const double value, const double minimum, const double maximum)
{
   return MathMin(MathMax(value, minimum), maximum);
}

void CountRegime(const MarketRegime regime)
{
   if(regime == REGIME_TREND)
      g_diagRegimeTrend++;
   else if(regime == REGIME_RANGE)
      g_diagRegimeRange++;
   else
      g_diagRegimeNoTrade++;
}

void PrintDiagnosticSummary()
{
   PrintFormat(
      "diagnostic summary ticks=%I64d indicatorReady=%I64d spreadOk=%I64d trendRegime=%I64d rangeRegime=%I64d noTradeRegime=%I64d trendBuyCandidates=%I64d trendSellCandidates=%I64d rangeBuyCandidates=%I64d rangeSellCandidates=%I64d canOpenOk=%I64d canOpenBlocked=%I64d directionBlocked=%I64d openedBuy=%I64d openedSell=%I64d closed=%I64d",
      g_diagTicks,
      g_diagIndicatorReady,
      g_diagSpreadOk,
      g_diagRegimeTrend,
      g_diagRegimeRange,
      g_diagRegimeNoTrade,
      g_diagTrendBuyCandidate,
      g_diagTrendSellCandidate,
      g_diagRangeBuyCandidate,
      g_diagRangeSellCandidate,
      g_diagCanOpenOk,
      g_diagCanOpenBlocked,
      g_diagDirectionBlocked,
      g_diagOpenedBuy,
      g_diagOpenedSell,
      g_diagClosed
   );
}

void PrintPerformanceSummary()
{
   if(!HistorySelect(0, TimeCurrent()))
      return;

   int exits = 0;
   int wins = 0;
   int losses = 0;
   int maxConsecutiveLosses = 0;
   int runningLosses = 0;
   double grossProfit = 0.0;
   double grossLoss = 0.0;
   double maxWin = 0.0;
   double maxLoss = 0.0;

   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber)
         continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;

      const double profit = HistoryDealGetDouble(deal, DEAL_PROFIT) +
                            HistoryDealGetDouble(deal, DEAL_SWAP) +
                            HistoryDealGetDouble(deal, DEAL_COMMISSION);
      exits++;
      if(profit > 0.0)
      {
         wins++;
         grossProfit += profit;
         maxWin = MathMax(maxWin, profit);
         runningLosses = 0;
      }
      else if(profit < 0.0)
      {
         losses++;
         grossLoss += profit;
         maxLoss = MathMin(maxLoss, profit);
         runningLosses++;
         maxConsecutiveLosses = MathMax(maxConsecutiveLosses, runningLosses);
      }
   }

   const double net = grossProfit + grossLoss;
   const double expectedPayoff = exits > 0 ? net / exits : 0.0;
   const double averageWin = wins > 0 ? grossProfit / wins : 0.0;
   const double averageLoss = losses > 0 ? grossLoss / losses : 0.0;
   const double profitFactor = grossLoss < 0.0 ? grossProfit / MathAbs(grossLoss) : 0.0;
   const double winRate = exits > 0 ? (double)wins / exits * 100.0 : 0.0;

   PrintFormat(
      "performance summary exits=%d wins=%d losses=%d winRate=%.2f grossProfit=%.2f grossLoss=%.2f net=%.2f profitFactor=%.4f expectedPayoff=%.5f averageWin=%.5f averageLoss=%.5f maxWin=%.5f maxLoss=%.5f maxConsecutiveLosses=%d",
      exits,
      wins,
      losses,
      winRate,
      grossProfit,
      grossLoss,
      net,
      profitFactor,
      expectedPayoff,
      averageWin,
      averageLoss,
      maxWin,
      maxLoss,
      maxConsecutiveLosses
   );
}

void PrintSymbolInfo()
{
   PrintFormat(
      "GOLDm scalper symbol=%s minLot=%.4f maxLot=%.4f lotStep=%.4f contract=%.2f tickSize=%.5f tickValue=%.5f point=%.5f digits=%d stops=%d freeze=%d",
      _Symbol,
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE),
      SymbolInfoDouble(_Symbol, SYMBOL_POINT),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL)
   );
}
