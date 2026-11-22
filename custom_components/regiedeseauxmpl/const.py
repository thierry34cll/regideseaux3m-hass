"""Constants for the Régie des Eaux Montpellier integration."""
import logging
from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "regiedeseauxmpl"
LOGGER = logging.getLogger(__package__)

# Configuration keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_METERS = "meters"
CONF_SCAN_INTERVAL = "scan_interval"  # legacy (config entries v1), migrated to CONF_UPDATE_TIME
CONF_UPDATE_TIME = "update_time"
CONF_SMOOTH_CONSUMPTION = "smooth_consumption"
CONF_IMPORT_HISTORY = "import_history"
CONF_OVERWRITE_HISTORY = "overwrite_history"

# Default values
DEFAULT_SCAN_INTERVAL = timedelta(hours=6)  # legacy
DEFAULT_UPDATE_TIME = "05:00"
DEFAULT_SMOOTH_CONSUMPTION = False
DEFAULT_IMPORT_HISTORY = True
DEFAULT_OVERWRITE_HISTORY = False
DEFAULT_NAME = "Régie des Eaux Montpellier"

# Storage key marking that the one-time history import already ran (per entry)
STORAGE_KEY_HISTORY = f"{DOMAIN}_history_imported"

# A reading published on day D reflects the consumption of day D-1.
READING_DATE_OFFSET_DAYS = 0
# Heure d'horodatage des lignes de statistiques journalières (heure locale) :
# 23:30 = la conso du jour apparaît en fin de journée, pas à 00:00
DAILY_STATISTIC_HOUR = 23
DAILY_STATISTIC_MINUTE = 30  # vérifié vs site Régie des Eaux : dateReleve = jour de consommation
# How far back the API is queried for the history import (the server may cap it).
HISTORY_LOOKBACK_DAYS = 1095  # ~3 years

# Minimum and maximum scan intervals
MIN_SCAN_INTERVAL = timedelta(minutes=30)
MAX_SCAN_INTERVAL = timedelta(hours=24)

# Platforms
PLATFORMS = [Platform.SENSOR]

# API Endpoints
BASE_URL = "https://ael.regiedeseaux3m.fr"
API_ROOT_URL = f"{BASE_URL}/webapi"
LOGIN_URL = f"{API_ROOT_URL}/Utilisateur/authentification"
GENERATE_TOKEN_URL = f"{API_ROOT_URL}/Acces/generateToken"
API_URL = f"{API_ROOT_URL}"

# App credentials (extracted from app.js)
WS_APPLICATION_LOGIN = "AEL-TOKEN-R3M-PRD"
WS_APPLICATION_PWD = "XX_fr-5DjklsdMM-R3M-PRD"

# Attributes
ATTR_LAST_UPDATED = "last_updated"
ATTR_LAST_READING = "last_reading"
ATTR_CONTRACT_ID = "contract_id"
ATTR_SERIAL_NUMBER = "serial_number"
ATTR_UNIT = "unit"

# Entity names
ENTITY_WATER_SENSOR = "water_index"
