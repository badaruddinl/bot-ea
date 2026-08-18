from __future__ import annotations

import json


def main() -> int:
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        payload = {
            "account_login": getattr(account, "login", None),
            "account_server": getattr(account, "server", None),
            "build": getattr(terminal, "build", None),
            "connected": getattr(terminal, "connected", None),
            "data_path": getattr(terminal, "data_path", None),
            "maxbars": getattr(terminal, "maxbars", None),
            "path": getattr(terminal, "path", None),
        }
        print(json.dumps(payload, sort_keys=True))
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
