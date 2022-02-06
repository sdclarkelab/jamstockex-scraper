# StockWatchJa: JamStockEx Scraper

The **StockWatchJa: JamStockEx Scraper** scrapes the [Jamaica Stock Exchange](https://www.jamstockex.com/) website daily using Python and saves to a MongoDB collection.
The data is then served as JSON by **[StockWatchJA: JamStockEx API](https://github.com/sdclarkelab/jamstockex-api)** at this [URL](http://jamstockexapi.stockwatchja.com/stocks).


#### The following stock data is scraped:
- All Listed Stocks
- Dividends pending payout dates
- Stock details:
    - Name
    - Instrument Code
    - Currency
    - Sector
    - Type
    - Website
    - Market
    - Volume Traded
    - Dollar Change
    - Market Price
    - Percentage Change


## Requirements
Tool | Version  | Source |
--- | --- | --- |
Python |3.7.0| [Python 3.7.0 Release](https://www.python.org/downloads/release/python-370/)|
Windows OS| 10 | - |


#### Create Secrets.json file
Create ".env" in application root folder
```.env
NODE_ENV=dev
DB_CONN_STR="<MongoDB-node-2.2.12-connection-string>"
DB_NAME=stockwatch
STOCK_COL=stock
```

#### Initialize database
```shell script
python main.py
```

