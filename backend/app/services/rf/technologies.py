"""Radio-technology presets: link-budget defaults per study type.

Each preset carries typical downlink parameters (frequency, TX power/EIRP
components, receiver sensitivity, antenna heights) and the propagation model
best suited to it, so a user can run a GSM, UMTS, LTE, 5G NR, PMR, broadcast,
Wi-Fi, IoT or microwave study without knowing the underlying model zoo.
Every value can be overridden per request - presets are starting points,
exactly like the technology templates in commercial planning tools.

Receiver sensitivity notes (median values, 50% cell edge):
  GSM     -102 dBm (voice, 200 kHz)         UMTS  -117 dBm (CPICH, proc. gain)
  LTE     -105/-100 dBm (10/20 MHz, edge)   NR    -100 dBm (mid-band, edge)
  Wi-Fi   -82 dBm (20 MHz MCS0)             LoRa  -137 dBm (SF12 125 kHz)
"""
from __future__ import annotations

TECHNOLOGIES: dict[str, dict] = {
    # ------------------------------------------------------------- 2G / GSM
    "gsm900": {
        "label": "GSM 900 (2G)", "generation": "2G",
        "freq_mhz": 945.0, "model": "okumura_hata", "environment": "suburban",
        "tx_power_dbm": 43.0, "tx_gain_dbi": 15.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -102.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    "gsm1800": {
        "label": "GSM 1800 / DCS (2G)", "generation": "2G",
        "freq_mhz": 1842.0, "model": "cost231_hata", "environment": "urban",
        "tx_power_dbm": 43.0, "tx_gain_dbi": 17.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -102.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    # ------------------------------------------------------------ 3G / UMTS
    "umts900": {
        "label": "UMTS 900 (3G)", "generation": "3G",
        "freq_mhz": 942.5, "model": "okumura_hata", "environment": "suburban",
        "tx_power_dbm": 43.0, "tx_gain_dbi": 15.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -117.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    "umts2100": {
        "label": "UMTS 2100 (3G)", "generation": "3G",
        "freq_mhz": 2140.0, "model": "tr38901_uma", "environment": "nlos",
        "tx_power_dbm": 43.0, "tx_gain_dbi": 18.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -117.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    # ------------------------------------------------------------- 4G / LTE
    "lte800": {
        "label": "LTE 800 / B20 (4G)", "generation": "4G",
        "freq_mhz": 806.0, "model": "okumura_hata", "environment": "suburban",
        "tx_power_dbm": 46.0, "tx_gain_dbi": 15.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -105.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    "lte1800": {
        "label": "LTE 1800 / B3 (4G)", "generation": "4G",
        "freq_mhz": 1842.5, "model": "cost231_hata", "environment": "urban",
        "tx_power_dbm": 46.0, "tx_gain_dbi": 17.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -103.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    "lte2600": {
        "label": "LTE 2600 / B7 (4G)", "generation": "4G",
        "freq_mhz": 2655.0, "model": "tr38901_uma", "environment": "nlos",
        "tx_power_dbm": 46.0, "tx_gain_dbi": 18.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -100.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    # ------------------------------------------------------------- 5G / NR
    "nr3500": {
        "label": "5G NR n78 3.5 GHz (mid-band)", "generation": "5G",
        "freq_mhz": 3550.0, "model": "tr38901_uma", "environment": "nlos",
        "tx_power_dbm": 49.0, "tx_gain_dbi": 24.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -100.0,
        "h_bs_m": 25.0, "h_ut_m": 1.5,
    },
    "nr700": {
        "label": "5G NR n28 700 MHz (coverage layer)", "generation": "5G",
        "freq_mhz": 758.0, "model": "okumura_hata", "environment": "suburban",
        "tx_power_dbm": 46.0, "tx_gain_dbi": 15.0, "rx_gain_dbi": 0.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -105.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    "nr28000": {
        "label": "5G NR n257 28 GHz (mmWave)", "generation": "5G",
        "freq_mhz": 28_000.0, "model": "tr38901_umi", "environment": "nlos",
        "tx_power_dbm": 40.0, "tx_gain_dbi": 30.0, "rx_gain_dbi": 10.0,
        "losses_db": 2.0, "rx_sensitivity_dbm": -95.0,
        "h_bs_m": 10.0, "h_ut_m": 1.5,
    },
    # -------------------------------------------------- PMR / TETRA / voice
    "pmr446": {
        "label": "PMR446 handheld", "generation": "PMR",
        "freq_mhz": 446.1, "model": "okumura_hata", "environment": "open",
        "tx_power_dbm": 27.0, "tx_gain_dbi": 0.0, "rx_gain_dbi": 0.0,
        "losses_db": 0.0, "rx_sensitivity_dbm": -119.0,
        "h_bs_m": 30.0, "h_ut_m": 1.5,
    },
    "tetra400": {
        "label": "TETRA 400 (PMR/PPDR)", "generation": "PMR",
        "freq_mhz": 420.0, "model": "okumura_hata", "environment": "suburban",
        "tx_power_dbm": 44.0, "tx_gain_dbi": 9.0, "rx_gain_dbi": 0.0,
        "losses_db": 2.0, "rx_sensitivity_dbm": -112.0,
        "h_bs_m": 40.0, "h_ut_m": 1.5,
    },
    # ------------------------------------------------------------ broadcast
    "fm100": {
        "label": "FM broadcast 87-108 MHz", "generation": "Broadcast",
        "freq_mhz": 100.0, "model": "fspl", "environment": "open",
        "tx_power_dbm": 60.0, "tx_gain_dbi": 6.0, "rx_gain_dbi": 0.0,
        "losses_db": 1.5, "rx_sensitivity_dbm": -90.0,
        "h_bs_m": 100.0, "h_ut_m": 10.0,
    },
    "dvbt600": {
        "label": "DVB-T/T2 UHF 600 MHz", "generation": "Broadcast",
        "freq_mhz": 600.0, "model": "okumura_hata", "environment": "open",
        "tx_power_dbm": 63.0, "tx_gain_dbi": 10.0, "rx_gain_dbi": 12.0,
        "losses_db": 3.0, "rx_sensitivity_dbm": -84.0,
        "h_bs_m": 150.0, "h_ut_m": 10.0,
    },
    # --------------------------------------------------------- Wi-Fi / IoT
    "wifi2400": {
        "label": "Wi-Fi 2.4 GHz outdoor", "generation": "WLAN",
        "freq_mhz": 2442.0, "model": "tr38901_umi", "environment": "nlos",
        "tx_power_dbm": 20.0, "tx_gain_dbi": 8.0, "rx_gain_dbi": 2.0,
        "losses_db": 1.0, "rx_sensitivity_dbm": -82.0,
        "h_bs_m": 10.0, "h_ut_m": 1.5,
    },
    "wifi5800": {
        "label": "Wi-Fi 5.8 GHz PtMP", "generation": "WLAN",
        "freq_mhz": 5800.0, "model": "tr38901_umi", "environment": "los",
        "tx_power_dbm": 23.0, "tx_gain_dbi": 16.0, "rx_gain_dbi": 14.0,
        "losses_db": 1.0, "rx_sensitivity_dbm": -80.0,
        "h_bs_m": 20.0, "h_ut_m": 5.0,
    },
    "lora868": {
        "label": "LoRaWAN 868 MHz (IoT)", "generation": "IoT",
        "freq_mhz": 868.0, "model": "okumura_hata", "environment": "suburban",
        "tx_power_dbm": 14.0, "tx_gain_dbi": 3.0, "rx_gain_dbi": 0.0,
        "losses_db": 0.5, "rx_sensitivity_dbm": -137.0,
        "h_bs_m": 25.0, "h_ut_m": 1.5,
    },
    # ------------------------------------------------------ microwave links
    "ptp18000": {
        "label": "Microwave PtP 18 GHz", "generation": "Backhaul",
        "freq_mhz": 18_000.0, "model": "fspl", "environment": "los",
        "tx_power_dbm": 20.0, "tx_gain_dbi": 38.0, "rx_gain_dbi": 38.0,
        "losses_db": 2.0, "rx_sensitivity_dbm": -70.0,
        "h_bs_m": 30.0, "h_ut_m": 30.0,
    },
    # -------------------------------------------------------------- custom
    "custom": {
        "label": "Custom study", "generation": "Custom",
        "freq_mhz": 446.0, "model": "fspl", "environment": "open",
        "tx_power_dbm": 30.0, "tx_gain_dbi": 0.0, "rx_gain_dbi": 0.0,
        "losses_db": 0.0, "rx_sensitivity_dbm": -100.0,
        "h_bs_m": 20.0, "h_ut_m": 1.5,
    },
}


def _load_operator_presets() -> None:
    """Merge operator-specific presets from DATA_DIR/technologies.json.

    Lets an organization standardize on its real band plan (actual EIRP,
    sensitivities, heights) without touching code: the file maps preset key
    -> partial or full preset dict.  Existing keys are updated field-by-
    field; new keys are added (they need at least the full field set).
    """
    import json

    from ...config import DATA_DIR
    path = DATA_DIR / "technologies.json"
    if not path.exists():
        return
    try:
        custom = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    for key, fields in custom.items():
        if not isinstance(fields, dict):
            continue
        if key in TECHNOLOGIES:
            TECHNOLOGIES[key].update(fields)
        else:
            TECHNOLOGIES[key] = fields


_load_operator_presets()


def get_technology(key: str) -> dict:
    if key not in TECHNOLOGIES:
        raise ValueError(f"Unknown technology preset: {key!r}")
    return dict(TECHNOLOGIES[key])  # copy so callers can override safely


def link_budget(tech: dict, path_loss_db_value: float,
                diffraction_db: float = 0.0) -> dict:
    """RX power and fade margin from a technology dict + losses."""
    rx_power = (tech["tx_power_dbm"] + tech["tx_gain_dbi"] + tech["rx_gain_dbi"]
                - tech["losses_db"] - path_loss_db_value - diffraction_db)
    return {
        "rx_power_dbm": rx_power,
        "margin_db": rx_power - tech["rx_sensitivity_dbm"],
        "served": rx_power >= tech["rx_sensitivity_dbm"],
    }
