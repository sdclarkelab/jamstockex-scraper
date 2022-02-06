import logging

import constants
import helper
from urls import URLS

logger = logging.getLogger('root')
urls = URLS()


def get_trade_summaries(current_date, retry_num):
    try:
        url = urls.get_formatted_resource_url(constants.SUMMARY_RESOURCE, constants.COMBINED_MARKET, current_date)
        parse_tree = helper.get_parse_tree(url, retry_num)

        trade_summaries = _extract_trade_summaries(parse_tree)

        return trade_summaries

    except Exception as e:
        logger.error(e)


def _extract_trade_summaries(parse_tree):
    try:
        tables = helper.find_tables(parse_tree, is_find_all=True)

        trade_summaries = {
            'indices': _extract_indices_summary(tables[0]),
            'stocks': _extract_shares_summaries(tables[1:])
        }

        return trade_summaries
    except Exception as e:
        logger.error(e)


def _extract_indices_summary(table):
    try:
        indices_trade_summaries = []

        for row in table.findAll('tr')[1:]:
            cells = helper.Cells(row.findAll("td"))

            indices_trade_summary = {
                constants.LAST_UPDATED_DATE: helper.get_current_time(),
                constants.INDEX: cells.extract_text(0),
                constants.VALUE: cells.extract_text(1),
                constants.VOLUME: cells.extract_text(2),
                constants.DOLLAR_CHANGE: cells.extract_text(3),
                constants.PERCENT_CHANGE: cells.extract_text(4)
            }

            indices_trade_summaries.append(indices_trade_summary)

        return indices_trade_summaries

    except Exception as e:
        raise


def _extract_shares_summaries(tables):
    trade_summaries = []

    try:
        for index, table in enumerate(tables):
            for row in table.findAll('tr')[1:]:
                cells = helper.Cells(row.findAll("td"))

                trade_summary = {
                    constants.TRADE_INFO: {
                        constants.LAST_UPDATED_DATE: helper.get_current_time(),
                        constants.MARKET_PRICE: cells.extract_text(2),
                        constants.DOLLAR_CHANGE: cells.extract_text(4),
                        constants.VOLUME: cells.extract_text(7),
                    },
                    constants.INSTRUMENT_CODE: urls.get_query_param_value(urls.join_url(cells.extract_href(1)),
                                                                          'instrument')
                }

                trade_summaries.append(trade_summary)

        return trade_summaries
    except Exception as e:
        raise
