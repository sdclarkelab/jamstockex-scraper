# Created by Stephen Clarke at 07-Jul-19
import logging
import sys
from datetime import datetime

from pymongo import MongoClient

from utils import constants, log


def update_stock_info(stock_info_col: MongoClient, stock_info_list: []):
    try:
        logging.info('Updating stock info .... ')
        for stock in stock_info_list:
            query = {constants.INSTRUMENT_NAME: stock[constants.INSTRUMENT_NAME]}

            #  Upsert (Insert if does not exists and Update if it does) stock info into database
            stock_info_col.update(query, stock, upsert=True)
        logging.info('Successfully updated stock info.')

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def update_stock_price_history(stock_info_col: MongoClient, price_history_data: {}):
    try:
        logging.info('Updating stock price history .... ')

        for symbol, extracted_data in price_history_data.items():
            query = {constants.INSTRUMENT_NAME: symbol}

            new_values = {'$set': {'trade_info': extracted_data, 'last_updated_date': datetime.now()}}
            stock_info_col.update_one(query, new_values, upsert=True)
        logging.info('Successfully updated stock price history')

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def update_stock_dividend(stock_info_col: MongoClient, dividend_data: {}):
    try:
        logging.info('Updating stock dividend .... ')

        for k, v in dividend_data.items():
            query = {'symbol': k}
            new_values = {'$set': {'dividends': v, 'last_updated_date': datetime.now()}}
            stock_info_col.update_one(query, new_values, upsert=True)
        logging.info('Successfully updated stock dividends')

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
