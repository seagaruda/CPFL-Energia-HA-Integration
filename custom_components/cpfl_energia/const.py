# -*- coding: utf-8 -*-
"""Constants for the CPFL Energia integration."""

from datetime import timedelta

DOMAIN = "cpfl_energia"

# Config flow
CONF_DOCUMENT = "document"          # CPF or CNPJ
CONF_PASSWORD = "password"
CONF_AUTH_TOKEN = "auth_token"
CONF_INSTALLATIONS = "installations"  # dict of installation_number -> info
CONF_INSTALLATION_NUMBER = "installation_number"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SETTINGS = "settings"
CONF_UPDATED_AT = "updated_at"
CONF_ACTION = "action"

STEP_USER = "user"
STEP_INIT = "init"
STEP_LOGIN = "login"
STEP_SELECT_INSTALLATION = "select_installation"
STEP_SETTINGS = "settings"
STEP_ADD_INSTALLATION = "add_installation"

ABORT_NO_INSTALLATION = "no_installation"
ABORT_ALL_ADDED = "all_added"

CONF_GENERAL_ERROR = "base"
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_UNKNOWN = "unknown"

# Sensor suffixes
SUFFIX_BALANCE = "balance"
SUFFIX_BILL_AMOUNT = "bill_amount"
SUFFIX_BILL_DUE_DATE = "bill_due_date"
SUFFIX_BILL_REFERENCE_MONTH = "bill_reference_month"
SUFFIX_LAST_BILL_KWH = "last_bill_kwh"
SUFFIX_LAST_BILL_AMOUNT = "last_bill_amount"
SUFFIX_LAST_BILL_DUE_DATE = "last_bill_due_date"
SUFFIX_THIS_MONTH_KWH = "this_month_kwh"
SUFFIX_THIS_MONTH_ESTIMATE = "this_month_estimate"
SUFFIX_THIS_YEAR_KWH = "this_year_total_kwh"
SUFFIX_THIS_YEAR_AMOUNT = "this_year_total_amount"
SUFFIX_LAST_MONTH_KWH = "last_month_kwh"
SUFFIX_LAST_MONTH_AMOUNT = "last_month_amount"
SUFFIX_LAST_YEAR_KWH = "last_year_kwh"
SUFFIX_LAST_YEAR_AMOUNT = "last_year_amount"
SUFFIX_DAILY_AVERAGE_KWH = "daily_average_kwh"
SUFFIX_TARIFF_FLAGS = "tariff_flags"

# Attributes
ATTR_KEY_CONSUMPTION_HISTORY = "consumption_history"
ATTR_KEY_BILL_HISTORY = "bill_history"
STATE_UNAVAILABLE = "unavailable"
STATE_UPDATE_UNCHANGED = "unchanged"

# Settings
SETTING_UPDATE_TIMEOUT = 60

# Defaults
DEFAULT_UPDATE_INTERVAL = int(timedelta(hours=4).total_seconds())
