# CPFL Energia - Home Assistant Integration

> Integração do Home Assistant para a CPFL Energia (Brazil)

A Home Assistant custom integration to monitor your electricity consumption and billing data from **CPFL Energia** — one of the largest electricity distribution companies in Brazil, serving São Paulo state and other regions (CPFL Paulista, CPFL Piratininga, RGE, CPFL Santa Cruz, etc.).

## Features

- 🔐 **Secure login** with your CPF/CNPJ and password
- ⚡ **Electricity consumption tracking** — daily, monthly, and yearly kWh
- 💰 **Billing information** — current bill amount, due date, payment status
- 📊 **Historical data** — consumption history with monthly breakdown
- 🏠 **Multi-installation support** — monitor multiple installations (casas, apartamentos, etc.)
- 🔄 **Configurable update interval** — default every 4 hours
- 🇧🇷 **Portuguese & English** UI translations

## Sensors

For each installation, the following sensors are created:

| Sensor | Unit | Description |
|--------|------|-------------|
| `bill_amount` | BRL | Current bill amount |
| `last_bill_kwh` | kWh | Latest bill consumption |
| `bill_due_date` | — | Current bill due date |
| `bill_reference_month` | — | Bill reference month |
| `balance` | BRL | Account balance (negative = credit) |
| `this_month_kwh` | kWh | This month's consumption |
| `this_month_estimate` | BRL | This month's estimated cost |
| `this_year_total_kwh` | kWh | Year-to-date total consumption |
| `this_year_total_amount` | BRL | Year-to-date total cost |
| `last_month_kwh` | kWh | Last month's consumption |
| `last_month_amount` | BRL | Last month's cost |
| `last_year_kwh` | kWh | Last year same month consumption |
| `last_year_amount` | BRL | Last year same month cost |
| `daily_average_kwh` | kWh | Daily average consumption |
| `tariff_flags` | — | Current tariff flags (Bandeira Tarifária) |

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → ⋮ → **Custom repositories**
3. Add this repository URL: `https://github.com/seagaruda/cpfl_energia`
4. Category: **Integration**
5. Click **Add**
6. Search for "CPFL Energia" and install
7. Restart Home Assistant

### Manual

1. Copy the `custom_components/cpfl_energia` folder to your `custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "CPFL Energia"
3. Enter your CPF or CNPJ (numbers only) and password
4. Select the installation you want to monitor
5. Done!

### Adding more installations

1. Go to the integration settings (⚙️ on the CPFL Energia card)
2. Select "Add installation"
3. Choose from the list of installations linked to your account

## Requirements

- Home Assistant 2023.1 or later
- A CPFL Energia account (registered at [servicosonline.cpfl.com.br](https://servicosonline.cpfl.com.br))

## How it works

The integration authenticates with CPFL's web API (`servicosonline.cpfl.com.br`) using your document number (CPF/CNPJ) and password. It periodically polls the API to fetch:

- **Consumption data** from `/api/historico-consumo/busca-graficos`
- **Invoice/billing data** from `/api/historico-contas/`
- **Installation info** from `/api/instalacao/informacoes-instalacao/`

All API calls are made synchronously in executor threads, following the same pattern as the [China Southern Power Grid integration](https://github.com/CubicPill/china_southern_power_grid_stat) that this project is modeled after.

## Known Limitations

- The CPFL portal uses Azure B2C authentication, which may change over time. If the API endpoints change, this integration may need updates.
- Real-time data is not available — CPFL's data has a delay of 1-2 days.
- Tariff flags (Bandeiras Tarifárias) are currently not fetched from the API.

## Credits

This integration is modeled after the [china_southern_power_grid_stat](https://github.com/CubicPill/china_southern_power_grid_stat) integration by [@CubicPill](https://github.com/CubicPill), adapted for CPFL Energia's API.

## License

MIT License — see [LICENSE](LICENSE)

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by CPFL Energia. Use at your own risk.
