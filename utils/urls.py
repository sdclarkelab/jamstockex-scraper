import os
from urllib.parse import urljoin

web_crawler_path = os.path.dirname(os.path.dirname(__file__))
logging_config_path = os.path.join(web_crawler_path, os.path.join('conf', 'logging.conf'))
print(logging_config_path)

base_url = "https://www.jamstockex.com/"

#  Ticker URL
_ticker = "ticker-data"
ticker_url = urljoin(base_url, _ticker)

#  Listed Stocks URL
_stock_list = "/market-data/listed-companies/"
listed_compaines_url = urljoin(base_url, _stock_list)

#  Listed Dividend URL
_dividend = "corporate-actions/{0}/latest"
dividend_url = urljoin(listed_compaines_url, _dividend)

#  Corporate Action URL
corporate_url = 'https://www.jamstockex.com/market-data/download-data/corporate-actions-history/'

#  Index Composition URL
index_composition_url = 'https://www.jamstockex.com/market-data/index-data/index-composition/index-information/combined-index'
