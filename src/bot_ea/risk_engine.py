from __future__ import annotations

import math

from .models import (
    CapitalAllocationMode,
    OperatingMode,
    PositionSizeRequest,
    PositionSizeResult,
    RiskPolicy,
    SuitabilityAssessment,
    TradingStyle,
)


class RiskEngine:
    """Pure risk logic that stays testable outside MT5."""

    _STYLE_RISK_FLOOR = {
        TradingStyle.SCALPING: 0.75,
        TradingStyle.INTRADAY: 0.50,
        TradingStyle.SWING: 1.00,
    }

    _CLASS_MINIMUM_ALLOCATION = {
        "forex_major": {
            TradingStyle.SCALPING: 100.0,
            TradingStyle.INTRADAY: 75.0,
            TradingStyle.SWING: 125.0,
        },
        "metal": {
            TradingStyle.SCALPING: 250.0,
            TradingStyle.INTRADAY: 150.0,
            TradingStyle.SWING: 300.0,
        },
        "index_cfd": {
            TradingStyle.SCALPING: 300.0,
            TradingStyle.INTRADAY: 200.0,
            TradingStyle.SWING: 350.0,
        },
        "unknown": {
            TradingStyle.SCALPING: 150.0,
            TradingStyle.INTRADAY: 100.0,
            TradingStyle.SWING: 200.0,
        },
    }

    def assess_suitability(
        self,
        account,
        symbol,
        policy: RiskPolicy,
        *,
        trading_style: TradingStyle = TradingStyle.INTRADAY,
        capital_base_cash: float | None = None,
        force_symbol: bool = False,
        requested_mode: OperatingMode | None = None,
    ) -> SuitabilityAssessment:
        reasons: list[str] = []
        warnings: list[str] = []
        working_capital = capital_base_cash if capital_base_cash is not None else account.equity
        recommended_minimum = self.recommended_minimum_allocation(symbol.instrument_class, trading_style)

        if requested_mode is not None:
            reasons.append(f"requested mode override: {requested_mode.value}")
            return SuitabilityAssessment(mode=requested_mode, reasons=reasons, warnings=warnings)

        if force_symbol:
            warnings.append("user forced symbol despite risk pressure")
            return SuitabilityAssessment(
                mode=OperatingMode.STRICT,
                reasons=["forced-risk override"],
                warnings=warnings,
            )

        if not symbol.trade_allowed:
            return SuitabilityAssessment(
                mode=OperatingMode.STRICT,
                reasons=["symbol not trade-allowed"],
                warnings=warnings,
            )

        if not symbol.quote_session_active or not symbol.trade_session_active:
            return SuitabilityAssessment(
                mode=OperatingMode.STRICT,
                reasons=["symbol session inactive"],
                warnings=warnings,
            )

        spread_ratio = self._spread_to_volatility_ratio(symbol)
        margin_buffer_ratio = self._margin_buffer_ratio(account)
        daily_loss_pressure = self._ratio(
            account.daily_realized_loss_pct,
            policy.daily_loss_limit_pct,
        )
        open_risk_pressure = self._ratio(
            account.current_open_risk_pct,
            policy.max_total_open_risk_pct,
        )

        if working_capital < policy.min_allocated_capital_cash:
            reasons.append("allocated capital below practical minimum")
            return SuitabilityAssessment(mode=OperatingMode.STRICT, reasons=reasons, warnings=warnings)

        if working_capital < recommended_minimum:
            warnings.append(
                f"recommended minimum allocation for {symbol.name} {trading_style.value} is about {recommended_minimum:.2f}"
            )

        if working_capital <= policy.small_equity_threshold and symbol.risk_weight >= policy.strict_risk_weight:
            reasons.append("small equity against high-risk symbol")
            return SuitabilityAssessment(mode=OperatingMode.STRICT, reasons=reasons, warnings=warnings)

        if (
            spread_ratio >= policy.strict_spread_to_volatility_ratio
            or margin_buffer_ratio <= policy.strict_margin_buffer_ratio
            or daily_loss_pressure >= 0.80
            or open_risk_pressure >= 0.80
        ):
            reasons.append("high friction or account pressure")
            return SuitabilityAssessment(mode=OperatingMode.STRICT, reasons=reasons, warnings=warnings)

        if working_capital <= policy.small_equity_threshold and symbol.risk_weight >= policy.caution_risk_weight:
            reasons.append("small equity against elevated symbol risk")
            return SuitabilityAssessment(mode=OperatingMode.CAUTION, reasons=reasons, warnings=warnings)

        if (
            spread_ratio >= policy.caution_spread_to_volatility_ratio
            or margin_buffer_ratio <= policy.caution_margin_buffer_ratio
            or daily_loss_pressure >= 0.50
            or open_risk_pressure >= 0.50
        ):
            reasons.append("borderline friction or account pressure")
            return SuitabilityAssessment(mode=OperatingMode.CAUTION, reasons=reasons, warnings=warnings)

        reasons.append("account and symbol conditions acceptable")
        return SuitabilityAssessment(mode=OperatingMode.RECOMMEND, reasons=reasons, warnings=warnings)

    def compute_position_size(self, request: PositionSizeRequest) -> PositionSizeResult:
        capital_base_cash = self._capital_base_cash(request)
        recommended_minimum = self.recommended_minimum_allocation(request.symbol.instrument_class, request.trading_style)
        if capital_base_cash <= 0:
            return PositionSizeResult(
                accepted=False,
                mode=OperatingMode.STRICT,
                capital_base_cash=0.0,
                recommended_minimum_allocation_cash=recommended_minimum,
                effective_risk_pct=0.0,
                risk_cash_budget=0.0,
                normalized_volume=0.0,
                estimated_loss_cash=0.0,
                stop_distance_points=request.stop_distance_points,
                rejection_reason="allocated capital must be positive",
            )

        if request.stop_distance_points <= 0:
            return PositionSizeResult(
                accepted=False,
                mode=OperatingMode.STRICT,
                capital_base_cash=capital_base_cash,
                recommended_minimum_allocation_cash=recommended_minimum,
                effective_risk_pct=0.0,
                risk_cash_budget=0.0,
                normalized_volume=0.0,
                estimated_loss_cash=0.0,
                stop_distance_points=request.stop_distance_points,
                rejection_reason="stop distance must be positive",
            )

        if request.stop_distance_points < request.symbol.stops_level_points:
            return PositionSizeResult(
                accepted=False,
                mode=OperatingMode.STRICT,
                capital_base_cash=capital_base_cash,
                recommended_minimum_allocation_cash=recommended_minimum,
                effective_risk_pct=0.0,
                risk_cash_budget=0.0,
                normalized_volume=0.0,
                estimated_loss_cash=0.0,
                stop_distance_points=request.stop_distance_points,
                rejection_reason="stop distance below broker stop level",
            )

        suitability = self.assess_suitability(
            request.account,
            request.symbol,
            request.policy,
            trading_style=request.trading_style,
            capital_base_cash=capital_base_cash,
            force_symbol=request.force_symbol,
            requested_mode=request.requested_mode,
        )
        effective_risk_pct = self._effective_risk_pct(request.policy, suitability.mode)
        risk_cash_budget = self._risk_cash_budget(request, effective_risk_pct, capital_base_cash)
        if risk_cash_budget <= 0:
            return PositionSizeResult(
                accepted=False,
                mode=suitability.mode,
                capital_base_cash=capital_base_cash,
                recommended_minimum_allocation_cash=recommended_minimum,
                effective_risk_pct=effective_risk_pct,
                risk_cash_budget=0.0,
                normalized_volume=0.0,
                estimated_loss_cash=0.0,
                stop_distance_points=request.stop_distance_points,
                rejection_reason="no remaining risk budget",
                warnings=suitability.warnings,
            )

        loss_per_lot = self._loss_per_lot(request)
        if loss_per_lot <= 0:
            return PositionSizeResult(
                accepted=False,
                mode=suitability.mode,
                capital_base_cash=capital_base_cash,
                recommended_minimum_allocation_cash=recommended_minimum,
                effective_risk_pct=effective_risk_pct,
                risk_cash_budget=risk_cash_budget,
                normalized_volume=0.0,
                estimated_loss_cash=0.0,
                stop_distance_points=request.stop_distance_points,
                rejection_reason="invalid symbol tick configuration",
                warnings=suitability.warnings,
            )

        style_floor = self.minimum_practical_risk_cash(request.trading_style)
        effective_risk_floor = max(request.policy.min_effective_risk_cash, style_floor)
        if risk_cash_budget < effective_risk_floor:
            return PositionSizeResult(
                accepted=False,
                mode=suitability.mode,
                capital_base_cash=capital_base_cash,
                recommended_minimum_allocation_cash=recommended_minimum,
                effective_risk_pct=effective_risk_pct,
                risk_cash_budget=risk_cash_budget,
                normalized_volume=0.0,
                estimated_loss_cash=0.0,
                stop_distance_points=request.stop_distance_points,
                rejection_reason=f"allocated risk cash below practical minimum for {request.trading_style.value} setup",
                warnings=suitability.warnings,
            )

        raw_volume = risk_cash_budget / loss_per_lot
        normalized_volume = self._normalize_volume(raw_volume, request.symbol.volume_min, request.symbol.volume_max, request.symbol.volume_step)

        if normalized_volume < request.symbol.volume_min:
            return PositionSizeResult(
                accepted=False,
                mode=suitability.mode,
                capital_base_cash=capital_base_cash,
                recommended_minimum_allocation_cash=recommended_minimum,
                effective_risk_pct=effective_risk_pct,
                risk_cash_budget=risk_cash_budget,
                normalized_volume=0.0,
                estimated_loss_cash=0.0,
                stop_distance_points=request.stop_distance_points,
                rejection_reason="allocated capital too small for minimum volume and stop distance",
                warnings=suitability.warnings,
            )

        estimated_loss_cash = normalized_volume * loss_per_lot
        warnings = list(suitability.warnings)
        if capital_base_cash < recommended_minimum:
            warnings.append(
                f"{request.symbol.name} may be impractical with allocated capital {capital_base_cash:.2f}; recommended minimum is about {recommended_minimum:.2f}"
            )
        if suitability.mode is not OperatingMode.RECOMMEND:
            warnings.append(f"operating mode downgraded to {suitability.mode.value}")

        return PositionSizeResult(
            accepted=True,
            mode=suitability.mode,
            capital_base_cash=capital_base_cash,
            recommended_minimum_allocation_cash=recommended_minimum,
            effective_risk_pct=effective_risk_pct,
            risk_cash_budget=risk_cash_budget,
            normalized_volume=normalized_volume,
            estimated_loss_cash=estimated_loss_cash,
            stop_distance_points=request.stop_distance_points,
            warnings=warnings,
        )

    @staticmethod
    def _normalize_volume(volume: float, volume_min: float, volume_max: float, volume_step: float) -> float:
        if volume_step <= 0:
            return 0.0
        clamped = min(max(volume, 0.0), volume_max)
        steps = math.floor((clamped + 1e-12) / volume_step)
        normalized = steps * volume_step
        if 0.0 < normalized < volume_min:
            return 0.0
        return round(normalized, 8)

    @staticmethod
    def _effective_risk_pct(policy: RiskPolicy, mode: OperatingMode) -> float:
        if mode is OperatingMode.CAUTION:
            return policy.base_risk_pct * policy.caution_risk_multiplier
        if mode is OperatingMode.STRICT:
            return policy.base_risk_pct * policy.strict_risk_multiplier
        return policy.base_risk_pct

    @staticmethod
    def _ratio(numerator: float, denominator: float) -> float:
        if denominator <= 0:
            return 1.0
        return numerator / denominator

    @staticmethod
    def _margin_buffer_ratio(account) -> float:
        if account.equity <= 0:
            return 0.0
        return max(account.free_margin, 0.0) / account.equity

    @staticmethod
    def _spread_to_volatility_ratio(symbol) -> float:
        if not symbol.volatility_points or symbol.volatility_points <= 0:
            return 0.0
        return symbol.spread_points / symbol.volatility_points

    def _risk_cash_budget(self, request: PositionSizeRequest, effective_risk_pct: float, capital_base_cash: float) -> float:
        base_budget = capital_base_cash * (effective_risk_pct / 100.0)
        remaining_daily = capital_base_cash * (
            max(request.policy.daily_loss_limit_pct - request.account.daily_realized_loss_pct, 0.0) / 100.0
        )
        remaining_open = capital_base_cash * (
            max(request.policy.max_total_open_risk_pct - request.account.current_open_risk_pct, 0.0) / 100.0
        )
        return max(min(base_budget, remaining_daily, remaining_open), 0.0)

    @staticmethod
    def _capital_base_cash(request: PositionSizeRequest) -> float:
        account_equity = max(request.account.equity, 0.0)
        allocation = request.capital_allocation
        if allocation is None or allocation.mode is CapitalAllocationMode.FULL_EQUITY:
            return account_equity
        if allocation.mode is CapitalAllocationMode.PERCENT_EQUITY:
            pct = min(max(allocation.value, 0.0), 100.0)
            return account_equity * (pct / 100.0)
        if allocation.mode is CapitalAllocationMode.FIXED_CASH:
            return min(max(allocation.value, 0.0), account_equity)
        return account_equity

    @classmethod
    def recommended_minimum_allocation(cls, instrument_class: str, trading_style: TradingStyle) -> float:
        class_table = cls._CLASS_MINIMUM_ALLOCATION.get(instrument_class, cls._CLASS_MINIMUM_ALLOCATION["unknown"])
        return class_table[trading_style]

    @classmethod
    def minimum_practical_risk_cash(cls, trading_style: TradingStyle) -> float:
        return cls._STYLE_RISK_FLOOR[trading_style]

    @staticmethod
    def _loss_per_lot(request: PositionSizeRequest) -> float:
        symbol = request.symbol
        if symbol.tick_size <= 0 or symbol.tick_value <= 0 or symbol.point <= 0:
            return 0.0
        stop_distance_price = request.stop_distance_points * symbol.point
        adverse_ticks = stop_distance_price / symbol.tick_size
        return adverse_ticks * symbol.tick_value
