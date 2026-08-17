from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


_BASELINE_6A_FUNCTION_SHA256 = {
    "AcceptRetest": "6181e556468eec7708beb06319b6a56a906f18d3dd16606a8383bcc73a2209b4",
    "AddTargetCandidate": "210e0c915d2066aa79055cdfc81af6cf54d250aeeae238e87d7022316b6809d2",
    "BuildCandidateId": "60c88f7b475b9a84d60666ffaaafe07fd84c281a10e21481786907ae56c30527",
    "BuildFibonacciImpulse": "7c253b49066592065dd2b1b015c9f7678a7df1413c3821eed342f58ad24a1c1e",
    "BuildReversalFibonacciImpulse": "b414d9f4dbda95e2663ad6471ec62aa8825c3eeee37db10045c90256d04028c3",
    "ConsiderCrossedLevel": "f50cf416b6739cb1d9ab00beb5ad7546ffff832de083a4129607fcf19bac1ed2",
    "ContextAligned": "e691982f51541a04d810028e092e4e6fd5a2ee2bb43af7b2c33f4f97113f97b5",
    "DetectBreakout": "7b1d4147bb1c04f1ad823f465eb2116e17d8458e7e7a4e3cc4e6d279b69c060b",
    "DetectChannelBreakout": "cf012cb07d3f21777e123c0a67583b226fb8de57200364dc311fa607d9d46784",
    "DetectM15Reversal": "3302c6c1719e9982f6b8e81d2ee61571f4b74dc5e095201bb0887d1de5a671d1",
    "DetectM15VwapPullback": "96c8ae5aceee6bb76c8f9e0db2eb7d4010a3ae683ec3b9627b01f6cbf2e0e286",
    "EarlyCandidateConfidenceScore": "f403305a3072a81023d50b483adacf308790f8c57b7265e72ed2d43ed6f39719",
    "FibonacciRetracementAligned": "f729219b7b014f5d192f8cf2abb3ef4e11ef03e2d201e7a854e155895dcba335",
    "FinalizeOpenSignalAtMarket": "e1a92a12d4473cf9e084b9a0ffab76364de7e538bb0e46f44184f62d808d0247",
    "FindCrossedKeyLevel": "5683a07c7214baa40731d361838de4242a52b1cf94e1971093f8d296a154dd29",
    "GeneratedUtcEpoch": "0cb923845acb7cc06380dc66af876e2768042720199aa7bf858eb543413eefd3",
    "HealthyMarket": "1af862655ddd818c6eed666cf82f8e5cdea852f1a9ff17f99c75fa57753e5970",
    "IndicatorValue": "c75cb73192e6f6c486c34fef6dd82739aaae7b5cf1a82c71a9de4afe54d66dd3",
    "IntradayVwapAligned": "2075ca416b7ecb90f72a32390f5e314bb9d3cf6db27ba3a48f145100d0d079ff",
    "IntradayVwapValue": "648a50c4ba0ce241cb055428a09bb0bbf05be365bf50884321203a3f10b85453",
    "IsConfiguredTradeWindow": "f24fc2a74d738f8dc3ab52e330eb789773fad5cf9b5a94d60e906bf51a5ece6b",
    "IsDojiCandle": "f2b7995d2b4c1589ef9e1368b5fe558231720246da5e26f3a3b888faa2dab776",
    "IsEveningDojiStar": "7f76dc5025d1610f60c995581506b2fd679f90167f94f55a1fd80bb131c797b3",
    "IsMorningDojiStar": "0ba152fc23cb9b3167f59fa6ca417d8ae54fa26fee32c5401fe74cd1cf4b450e",
    "ManageActiveSignalFromM1": "3a6082a451a75e94edfcc777802be94c43918c02a2dec8c6b511e495d565bcf4",
    "NearestFibonacciExtension": "ec1c6bbaa9e429ef6fee4ddcf01ffad612dd5d1ccfca302dfb3d47607c33d4e5",
    "NearestObjectiveTarget": "c81719a5e000fc3eae6593157cf9f43b99d4c495f01858cd9df7d45d53ea687c",
    "NetOutcomeR": "11940a9fcb7d38f546368575c821196bbfdb9e83e92d49eb0eda7325a3766990",
    "OnDeinit": "6fc8b45be67644e7fd78c890ff57397373842d66a647d152be12304b8894df1c",
    "OnTester": "350cd849db328221c07b9792ea25b3a1b9224a5fd84b241a2795bf5ecf42dc19",
    "OnTick": "e5e23a00b51a41ad2d823c77422f3becdf577bf4a526ff82934def20ebb2077c",
    "ProcessClosedM1": "c59d37f8709cfb6aeef1fa894e8212309422b712e4dea85af5dd2b25cb3ad91e",
    "ProcessClosedM15": "09799c5f8e62715e7ef0978188c229998fe874df31e4558ecf7db4740042f4fb",
    "ProcessRetest": "9ca453626d79517342ca56d78a63986fe3be4f4b41f1df04209787afc0fcb662",
    "RecordRoomCandidate": "dc4c3752f6859bd12b1968f7cad0ddd80ece38dea7016b9d6b70dc8b859a6fde",
    "RelativeTickVolume": "a2b7bd1dcd54aff978869e3376da35b729651f6441469ea8f0b9c79109620392",
    "ReleaseHandle": "0fbf971b80c324f7ad29fd7ff7296a6b36b666dca6fb34ffee2b13056be6b156",
    "ServerTimeToUtcEpoch": "85516790e66da4ffa0af819d3e2d4bbc743c56ea67a2b3b61751ef23bd1f9de8",
    "ServerUtcOffsetSeconds": "5fce196d3fed0ea4bd489a1b3a83a2dc2067a26713155efb7c7573842ef3c956",
    "TechnicalScore": "71ebf1015e969eab4b53738d14e3be099af9b4fb5c6f7537681ffd84753b668e",
    "UpdateActiveSignal": "0641eefa5dee8267571b0d8f93e051dd3d47abbd63d121623f395052b8059918",
    "ValidatePendingSetupOnM15": "79332eb1a321fd1e6ef7b1e769e19a3759e4b5e976773b00821c5028fb3c72db",
}

_FUNCTION_START = re.compile(
    r"^(?:bool|void|double|int|long|string)\s+(?P<name>\w+)\s*\(",
    re.MULTILINE,
)


def _function_bodies(source: str) -> dict[str, str]:
    functions: dict[str, str] = {}
    for match in _FUNCTION_START.finditer(source):
        opening = source.find("{", match.end())
        if opening < 0:
            raise AssertionError(f"function {match['name']} has no body")
        depth = 0
        closing = opening
        while closing < len(source):
            depth += (source[closing] == "{") - (source[closing] == "}")
            if depth == 0:
                break
            closing += 1
        if depth != 0:
            raise AssertionError(f"function {match['name']} has unbalanced braces")
        body = re.sub(r"\s+", " ", source[match.start() : closing + 1]).strip()
        functions[match["name"]] = body
    return functions


class GoldMStrategy172ParityTests(unittest.TestCase):
    def test_production_decision_functions_match_exact_6a_baseline(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "mt5"
            / "Experts"
            / "bot-ea"
            / "GoldMSniperParity.mq5"
        ).read_text(encoding="utf-8")
        functions = _function_bodies(source)
        observed = {
            name: hashlib.sha256(functions[name].encode("utf-8")).hexdigest()
            for name in _BASELINE_6A_FUNCTION_SHA256
        }
        self.assertEqual(observed, _BASELINE_6A_FUNCTION_SHA256)

    def test_runtime_hardening_is_outside_the_frozen_decision_contract(self) -> None:
        self.assertTrue(
            {
                "OnInit",
                "ProcessClosedM5",
                "EmitEarlyCandidateIfEligible",
                "CreateTechnicalSignal",
                "CompleteSignal",
                "ResetSetup",
                "PrintSummary",
            }.isdisjoint(_BASELINE_6A_FUNCTION_SHA256)
        )

    def test_entry_distance_guard_waits_for_pullback_without_raising_risk_limit(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "mt5"
            / "Experts"
            / "bot-ea"
            / "GoldMSniperParity.mq5"
        ).read_text(encoding="utf-8")
        function = _function_bodies(source)["CreateTechnicalSignal"]

        self.assertIn("input double InpMaximumEntryDistanceATR = 0.60;", source)
        self.assertIn("g_m1EntryBars < InpMaximumM1EntryBars", function)
        self.assertIn("g_m5ConfluenceVotes >= 3", function)
        self.assertIn("WAIT_PULLBACK_NO_CHASE", function)
        self.assertIn("ENTRY_DISTANCE_EXPIRED_NO_CHASE", function)
        self.assertLess(
            function.index("WAIT_PULLBACK_NO_CHASE"),
            function.index("ENTRY_DISTANCE_EXPIRED_NO_CHASE"),
        )

    def test_fibonacci_impulse_is_anchored_to_m15_not_m1(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "mt5"
            / "Experts"
            / "bot-ea"
            / "GoldMSniperParity.mq5"
        ).read_text(encoding="utf-8")
        functions = _function_bodies(source)
        for name in ("BuildFibonacciImpulse", "BuildReversalFibonacciImpulse"):
            self.assertIn("PERIOD_M15", functions[name])
            self.assertNotRegex(functions[name], r"\bPERIOD_M1\b")


if __name__ == "__main__":
    unittest.main()
