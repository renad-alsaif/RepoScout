"""weather-cli: print a (fake) weather report for a city."""

import sys

FAKE_WEATHER = {"riyadh": "Sunny, 34°C", "jeddah": "Humid, 31°C", "abha": "Cloudy, 22°C"}


def report(city: str) -> str:
    return f"{city.title()}: {FAKE_WEATHER.get(city.lower(), 'No data')}"


if __name__ == "__main__":
    print(report(sys.argv[1] if len(sys.argv) > 1 else "Riyadh"))
