# StockWatchJa: JamStockEx Scraper

The **StockWatchJa: JamStockEx Scraper** scrapes the [Jamaica Stock Exchange](https://www.jamstockex.com/) website daily using Python and saves to a MongoDB collection.
The data is then served as JSON by **[StockWatchJA: JamStockEx API](https://github.com/sdclarkelab/jamstockex-api)** at this [URL](http://jamstockexapi.stockwatchja.com/stocks).

#####The following stock data is scrapped:
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
Python |3.7.4| [Python 3.7.4 Release](https://www.python.org/downloads/release/python-374/)|
Heroku|-|[Getting Started on Heroku with Python](https://devcenter.heroku.com/articles/getting-started-with-python)|
Windows OS| 10 | - |


## Heroku Setup

### Installation
1. Install GIT
2. [Install Heroku on local machine](https://devcenter.heroku.com/articles/getting-started-with-python#set-up)


### Prepare Heroku to receive source code

#### Login to Heroku on local machine
Login using the following command
```shell script
heroku login
```

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
python initialize_database.py
```

#### Create Heroku project in Heroku
```shell script
heroku create jamstockex-scraper
```

#### Set Heroku environment variables
```shell script
python heroku-config.py
```

### Deploy 
```shell script
git push heroku your_local_branch_name:master
```
Validate that the application is live
```shell script
heroku ps:scale clock=1
```

# Test locally
Do the following to the stock_handler.py file:
``` python
    #  Get environment variables
    # mongoDB_connection_str = os.environ['DB_CONN_STR']
    # mongoDB_name = os.environ['DB_NAME']
    # stock_col = os.environ['STOCK_COL']

    mongoDB_connection_str = "<MongoDB-node-2.2.12-connection-string>"
    mongoDB_name = "stockwatch"
    stock_col = "stock"
    
    """ some code """
    # End of file
```
