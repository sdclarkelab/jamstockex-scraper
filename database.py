import logging
import os

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

import constants

logger = logging.getLogger('root')
load_dotenv()


class Database:
    __instance = None

    def __new__(cls, *args, **kwargs):
        if not Database.__instance:
            Database.__instance = object.__new__(cls)
        return Database.__instance

    def __init__(self):
        try:
            connection_str = os.getenv("DB_CONN_STR")
            db_name = os.getenv("DB_NAME")

            client = MongoClient(connection_str, tlsCAFile=certifi.where())
            self.client = client[db_name]
            self.stock_collection = self.client['Stocks']

        except Exception as e:
            logger.error(e)

    def get_collection(self, collection_name):
        try:
            return self.client[collection_name]
        except Exception as e:
            logger.error(e)

    def update_stock_collection(self, resource_name, data):
        try:

            if data is None:
                raise Exception("Missing scraped data")

            update_db = {
                constants.LISTED_COMPANIES_RESOURCE: self._update_stock,
                constants.SUMMARY_RESOURCE: self._update_stock_trade_summary,
                constants.CORPORATE_ACTION_RESOURCE: self._update_stock_corporate_actions
            }

            logger.info(f'Updating {resource_name} .... ')
            update_db[resource_name](data)
            logger.info('Successfully updated collection.')

        except Exception as e:
            logger.error(e)

    def _update_stock(self, listed_companies):

        try:
            if listed_companies is None:
                raise Exception('No data found.')

            for listed_company in listed_companies:
                if listed_company is None:
                    raise Exception('No data found.')

                query = {constants.INSTRUMENT_CODE: listed_company[constants.INSTRUMENT_CODE]}
                self.stock_collection.update_one(query, {"$set": listed_company}, upsert=True)

        except Exception as e:
            raise e

    def _update_stock_trade_summary(self, stock_trade_summary):
        try:
            if stock_trade_summary is None:
                raise Exception('No data found.')

            for stock_summary in stock_trade_summary["stocks"]:
                if stock_summary is None:
                    raise Exception('No data found.')

                query = {constants.INSTRUMENT_CODE: stock_summary[constants.INSTRUMENT_CODE]}

                new_values = {'$set': {'trade_info': stock_summary['trade_info']}}
                self.stock_collection.update_one(query, new_values, upsert=True)

        except Exception as e:
            raise e

    def _update_stock_corporate_actions(self, corporate_actions):
        try:
            if corporate_actions is None:
                raise Exception('No data found.')

            for instrument_code, action_data in corporate_actions.items():
                if action_data is None:
                    raise Exception('No data found.')
                for action_name, data in action_data.items():
                    if data is None:
                        raise Exception('No data found.')
                    query = {constants.INSTRUMENT_CODE: instrument_code}

                    new_values = {'$set': {
                        'corporate_action': {
                            action_name: data
                        }
                    }}
                    self.stock_collection.update_one(query, new_values, upsert=True)

        except Exception as e:
            raise e
