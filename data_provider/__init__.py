# -*- coding: utf-8 -*-
"""Data provider module."""

from data_provider.base import BaseFetcher, DataFetchError
from data_provider.sina_fetcher import SinaFetcher

__all__ = ["BaseFetcher", "DataFetchError", "SinaFetcher"]
