# -*- coding: utf-8 -*-
"""Data provider module."""

from data_provider.base import BaseFetcher, DataFetchError
from data_provider.multi_source_fetcher import MultiSourceFetcher

__all__ = ["BaseFetcher", "DataFetchError", "MultiSourceFetcher"]
