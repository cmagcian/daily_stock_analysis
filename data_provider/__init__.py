# -*- coding: utf-8 -*-
"""Data provider module."""

from data_provider.base import BaseFetcher, DataFetchError
from data_provider.akshare_fetcher import AkShareFetcher

__all__ = ["BaseFetcher", "DataFetchError", "AkShareFetcher"]
