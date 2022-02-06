import logging

import constants
import helper
from urls import URLS

logger = logging.getLogger('root')
urls = URLS()


def get_listed_companies(markets, retry_num):
    security_data = dict()

    try:
        for market in markets:
            url = urls.get_formatted_resource_url(constants.LISTED_COMPANIES_RESOURCE, market)

            parse_tree = helper.get_parse_tree(url, retry_num)
            security_data[market] = _extract_listed_companies_data(parse_tree, market)

        return security_data
    except Exception as e:
        raise


def _extract_listed_companies_data(parse_tree, market):
    try:
        listed_companies = list()

        table = parse_tree.find('table')

        if table is None:
            raise Exception("Table is missing")

        # Ignore table header
        for row in table.findAll('tr')[1:]:
            cells = helper.Cells(row.findAll("td"))

            instrument_url = urls.join_url(cells.extract_href(0))

            listed_company = {
                constants.LAST_UPDATED_DATE: helper.get_current_time(),
                constants.INSTRUMENT_NAME: cells.extract_text(0),
                constants.INSTRUMENT_URL: instrument_url,
                constants.INSTRUMENT_CODE: urls.get_query_param_value(instrument_url, 'instrument'),
                constants.SYMBOL: cells.extract_text(1),
                constants.CURRENCY: cells.extract_text(2),
                constants.SECTOR: cells.extract_text(3),
                constants.TYPE: cells.extract_text(4),
                constants.WEBSITE: cells.extract_href(5),
                constants.IS_LISTED: True,
                constants.MARKET: market,
                constants.TRADE_INFO: {}
            }

            listed_companies.append(listed_company)

        return listed_companies
    except Exception as e:
        logger.error(e)
        raise
