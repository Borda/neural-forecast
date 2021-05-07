# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/data__tsloader.ipynb (unless otherwise specified).

__all__ = ['TimeSeriesLoader']

# Cell
import copy
import logging
import random
from collections import defaultdict
from typing import Collection, Dict, List, Optional, Tuple, Union
from typing_extensions import Literal

import numpy as np
import pandas as pd
import torch as t
from fastcore.foundation import patch

from .tsdataset import TimeSeriesDataset

# Cell
class TimeSeriesLoader(object):
    """
    DataLoader for Time Series data.

    Attributes
    ----------
    ts_dataset: TimeSeriesDataset
        Object of class TimeSeriesDataset.
    t_cols: list
        List of temporal variables (mask variables included).
    f_cols: list
        List of exogenous variables of the future.
    model: str
        Model to be used.
        One of ['nbeats', 'esrnn'].
    window_sampling_limit: int
        Max size of observations to consider, including output_size.
    input_size: int
        Size of the training sets.
    output_size: int
        Forecast horizon.
    idx_to_sample_freq: int
        Step size to construct windows.
        Ej. if idx_to_sample_freq=7, each 7 timestamps
        a window will be constructed.
    batch_size: int
        Number of samples considered in each iteration.
    complete_inputs: bool
        Whether consider only windows of length equals to input_size.
    shuffle: bool
        Shuffled batch.
        If False, batch size will be ignored and
        all windows will be used when training.
    len_sample_chunks: Optional[int] = None
        Size of complete windows.
        Only used for model = 'esrnn'!
        Default None, equls to input_size + ouput_size.
    n_series_per_batch: Optional[int] = None
        Number of time series per batch.
    verbose: bool = False
        Whether display informative messages.
    windows_size: int
        Size of the windows.
        For model='nbeats', window_size=input_size + output_size.
        For model='esrnn', window_size=len_sample_chunks.
    padding: Tuple[int, int]
        Tuple of left and right sizes of the padding.
        Used to pad the ts_tensor with 0.
        For model='nbeats', padding=(input_size, output_size).
        For model='esrnn', padding=(0, 0).
    sampleable_ts_idxs: np.ndarray
        Indexes of sampleable time series.
    n_sampleable_ts_idxs: int
        Number of sampleable time series.
    n_batches:
        Number of batches given conditions.

    Methods
    -------
    get_n_variables()
        Returns Tuple of number of exogenous and static variables.
    get_n_series()
        Returns number of time series.
    get_max_len()
        Returns max length of the time series.
    get_n_channels()
        Returns number of channels.
    get_frequency()
        Returns infered frequency.
    """
    def __init__(self,
                 ts_dataset: TimeSeriesDataset,
                 model: Literal['nbeats', 'esrnn'],
                 window_sampling_limit: int,
                 input_size: int,
                 output_size: int,
                 idx_to_sample_freq: int,
                 batch_size: int,
                 complete_inputs: bool,
                 shuffle: bool,
                 len_sample_chunks: Optional[int] = None,
                 n_series_per_batch: Optional[int] = None,
                 verbose: bool = False) -> 'TimeSeriesLoader':
        """Instatiates loader for TimeSeriesDataset.

        Parameters
        ----------
        ts_dataset: TimeSeriesDataset
            Object of class TimeSeriesDataset.
        model: str
            Model to be used.
            One of ['nbeats', 'esrnn'].
        window_sampling_limit: int
            Max size of observations to consider, including output_size.
        input_size: int
            Size of the training sets.
        output_size: int
            Forecast horizon.
        idx_to_sample_freq: int
            Step size to construct windows.
            Ej. if idx_to_sample_freq=7, each 7 timestamps
            a window will be constructed.
        batch_size: int
            Number of samples considered in each iteration.
        complete_inputs: bool
            If complete_input=True
            return all windows which its ouput_size
            has complete sample_mask and its input_size
            has complete available_mask.
            If complete_input=False
            returns all windows which its
            output_size has complete sample_mask.
            This avoids leakage.
        shuffle: bool
            Shuffled batch.
            If False, batch size will be ignored and
            all windows will be used when training.
        len_sample_chunks: Optional[int] = None
            Size of complete windows.
            Only used for model = 'esrnn'!
            Default None, equls to input_size + ouput_size.
        n_series_per_batch: Optional[int] = None
            Number of time series per batch.
        verbose: bool = False
            Whether display informative messages.
        """
        # Dataloader attributes
        self.model = model
        self.window_sampling_limit = window_sampling_limit
        self.input_size = input_size
        self.output_size = output_size
        self.batch_size = batch_size
        self.complete_inputs = complete_inputs
        self.idx_to_sample_freq = idx_to_sample_freq
        self.ts_dataset = ts_dataset
        self.t_cols = self.ts_dataset.t_cols
        self.f_idxs = self.ts_dataset.f_idxs
        if n_series_per_batch is not None:
            self.n_series_per_batch = n_series_per_batch
        else:
            self.n_series_per_batch = min(batch_size, self.ts_dataset.n_series)

        if len_sample_chunks is not None:
            if len_sample_chunks < self.input_size + self.output_size:
                raise Exception(f'Insufficient len of sample chunks {len_sample_chunks}')
            self.len_sample_chunks = len_sample_chunks
        else:
            self.len_sample_chunks = input_size + output_size

        self.shuffle = shuffle
        self.verbose = verbose

        if not shuffle:
            logging.warning('Batch size will be ignored (shuffle=False). '
                            'All constructed windows will be used to train.')

        # Dataloader protections
        assert self.batch_size % self.n_series_per_batch == 0, (
            f'batch_size {self.batch_size} must be multiple of '
            f'n_series_per_batch {self.n_series_per_batch}'
        )
        assert self.n_series_per_batch <= self.ts_dataset.n_series, (
            f'n_series_per_batch {n_series_per_batch} needs '
            f'to be smaller than n_series {self.ts_dataset.n_series}'
        )

        # Defining windows attributes by model
        self.windows_size: int
        self.padding: Tuple[int, int]

        self._define_attributes_by_model()

        # Defining sampleable time series
        self.sampleable_ts_idxs: np.ndarray
        self.n_sampleable_ts: int

        self._define_sampleable_ts_idxs()

         # Loader iterations attributes
        self.n_batches = int(np.ceil(self.n_sampleable_ts / self.n_series_per_batch)) # Must be multiple of batch_size for paralel gpu


# Cell
@patch
def _define_attributes_by_model(self: TimeSeriesLoader):
    if self.model in ['nbeats']:
        self.windows_size = self.input_size + self.output_size
        self.padding = (self.input_size, self.output_size)
    elif self.model in ['esrnn']:
        self.windows_size = self.len_sample_chunks
        self.padding = (0, 0)
    else:
        raise Exception(f'There is no batch strategy for {self.model}')

# Cell
@patch
def _define_sampleable_ts_idxs(self: TimeSeriesLoader):
    sum_sample_mask = self.ts_dataset.ts_tensor[:, self.t_cols.index('sample_mask')] \
                              .sum(axis=1)
    if self.complete_inputs:
        min_mask = self.windows_size
    else:
        min_mask = self.output_size
    self.sampleable_ts_idxs = np.argwhere(sum_sample_mask > min_mask).reshape(1, -1)[0]
    self.n_sampleable_ts = self.sampleable_ts_idxs.size

# Cell
@patch
def _get_sampleable_windows_idxs(self: TimeSeriesLoader,
                                 ts_windows_flatten: t.Tensor) -> np.ndarray:
    """Gets indexes of windows that fulfills conditions.

    Parameters
    ----------
    ts_windows_flatten: t.Tensor
        Tensor of shape (windows, n_channels, windows_size)

    Returns
    -------
    Numpy array of indexes of ts_windows_flatten that
    fulfills conditions.

    Notes
    -----
    [1] If complete_input=True
    return all windows which its ouput_size
    has complete sample_mask and its input_size
    has complete available_mask.
    [2] If complete_input=False
    returns all windows which its
    output_size has complete sample_mask.
    This avoids leakage.
    """
    sample_condition = t.sum(ts_windows_flatten[:, self.t_cols.index('sample_mask'), -self.output_size:], axis=1)
    sample_condition = (sample_condition == self.output_size) * 1
    if self.complete_inputs:
        available_condition = t.sum(ts_windows_flatten[:, self.t_cols.index('available_mask'), :-self.output_size], axis=1)
        available_condition = (available_condition == self.windows_size - self.output_size) * 1
        sampling_idx = t.nonzero(available_condition * sample_condition > 0)
    else:
        sampling_idx = t.nonzero(sample_condition)

    sampling_idx = sampling_idx.flatten().numpy()
    assert sampling_idx.size > 0, (
        'Check the data and masks as sample_idxs are empty, '
        'check window_sampling_limit, input_size, output_size, masks'
    )

    return sampling_idx

# Cell
@patch
def _create_windows_tensor(self: TimeSeriesLoader,
                           index: Optional[np.ndarray] = None) -> Tuple[t.Tensor,
                                                                        t.Tensor,
                                                                        t.Tensor]:
    """Creates windows of size windows_size from
    the ts_tensor of the TimeSeriesDataset filtered by
    window_sampling_limit and ts_idxs. The step of each window
    is defined by idx_to_sample_freq.

    Parameters
    ----------
    index: Optional[np.ndarray]
        Indexes of time series to consider.
        Default None: returns all ts.

    Returns
    -------
    Tuple of three elements:
        - Windows tensor of shape (windows, channels, input_size + output_size)
        - Static variables tensor of shape (windows * series, n_static)
        - Time Series indexes for each window.
    """
    # Default ts_idxs=ts_idxs sends all the data, otherwise filters series
    tensor, _ = self.ts_dataset \
                    .get_filtered_ts_tensor(output_size=self.output_size,
                                            window_sampling_limit=self.window_sampling_limit,
                                            ts_idxs=index)
    tensor = t.Tensor(tensor)

    padder = t.nn.ConstantPad1d(padding=self.padding, value=0)
    tensor = padder(tensor)

    # Creating rolling windows and 'flattens' them
    windows = tensor.unfold(dimension=-1,
                            size=self.windows_size,
                            step=self.idx_to_sample_freq)
    # n_serie, n_channel, n_time, window_size -> n_serie, n_time, n_channel, window_size
    windows = windows.permute(0, 2, 1, 3)
    windows = windows.reshape(-1, self.ts_dataset.n_channels, self.windows_size)

    # Broadcast s_matrix: This works because unfold in windows_tensor, orders: serie, time
    s_matrix = self.ts_dataset.s_matrix[index]
    n_ts = self.ts_dataset.n_series if index is None else len(index)
    windows_per_serie = len(windows) / n_ts
    s_matrix = s_matrix.repeat(repeats=windows_per_serie, axis=0)
    ts_idxs = index.repeat(repeats=windows_per_serie)

    s_matrix = t.Tensor(s_matrix)
    ts_idxs = t.as_tensor(ts_idxs, dtype=t.long)


    return windows, s_matrix, ts_idxs

# Cell
@patch
def _windows_batch(self: TimeSeriesLoader,
                   index: np.ndarray) -> Dict[str, t.Tensor]:
    """Creates batch based on index.

    Parameters
    ----------
    index: np.ndarray
        Indexes of time series to consider.

    Returns
    -------
    Dictionary with keys:
        - S
        - Y
        - X
        - available_mask
        - sample_mask
        - idxs
    """

    # Create windows for each sampled ts and sample random unmasked windows from each ts
    windows, s_matrix, ts_idxs = self._create_windows_tensor(index=index)
    sampleable_windows = self._get_sampleable_windows_idxs(ts_windows_flatten=windows)

    # Get sample windows_idxs of batch
    if self.shuffle:
        windows_idxs = np.random.choice(sampleable_windows, self.batch_size, replace=True)
    else:
        windows_idxs = sampleable_windows

    # Index the windows and s_matrix tensors of batch
    windows = windows[windows_idxs]
    S = s_matrix[windows_idxs]
    ts_idxs = ts_idxs[windows_idxs]

    # Parse windows to elements of batch
    Y = windows[:, self.t_cols.index('y'), :]
    X = windows[:, (self.t_cols.index('y') + 1):self.t_cols.index('available_mask'), :]
    available_mask = windows[:, self.t_cols.index('available_mask'), :]
    sample_mask = windows[:, self.t_cols.index('sample_mask'), :]

    batch = {'S': S, 'Y': Y, 'X': X,
             'available_mask': available_mask,
             'sample_mask': sample_mask,
             'idxs': ts_idxs}

    return batch

# Cell
@patch
def __getitem__(self: TimeSeriesLoader,
                index: Union[Collection[int], np.ndarray]) -> Dict[str, t.Tensor]:
    """Gets batch based on index.

    Parameters
    ----------
    index: Collection[int]
        Indexes of time series to consider.

    Returns
    -------
    Batch corresponding to index.
    """

    return self._windows_batch(index=np.array(index))

# Cell
@patch
def __iter__(self: TimeSeriesLoader) -> Dict[str, t.Tensor]:
    """Batch iterator."""
    # Hierarchical sampling
    # 1. Sampling series
    if self.shuffle:
        sample_idxs = np.random.choice(a=self.sampleable_ts_idxs,
                                       size=self.n_sampleable_ts,
                                       replace=False)
    else:
        sample_idxs = np.array(self.sampleable_ts_idxs)

    for idx in range(self.n_batches):
        ts_idxs = sample_idxs[(idx * self.n_series_per_batch) : (idx + 1) * self.n_series_per_batch]
        # 2. Sampling windows
        batch = self[ts_idxs]
        yield batch

# Cell
@patch
def get_n_variables(self: TimeSeriesLoader) -> Tuple[int, int]:
    """Gets number of exogenous and static variables."""
    return self.ts_dataset.n_x, self.ts_dataset.n_s

@patch
def get_n_series(self: TimeSeriesLoader) -> int:
    """Gets number of time series."""
    return self.ts_dataset.n_series

@patch
def get_max_len(self: TimeSeriesLoader) -> int:
    """Gets max len of time series."""
    return self.ts_dataset.max_len

@patch
def get_n_channels(self: TimeSeriesLoader) -> int:
    """Gets number of channels considered."""
    return self.ts_dataset.n_channels

@patch
def get_frequency(self: TimeSeriesLoader) -> str:
    """Gets infered frequency."""
    return self.ts_dataset.frequency