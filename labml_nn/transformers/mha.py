"""
---
title: Multi-Headed Attention
summary: >
  This implements the Multi-Headed Attention used in transformers
  using PyTorch with explainations.
---

# Multi-Headed Attention

This is a tutorial/implementation of multi-headed attention
from paper [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
in [PyTorch](https://pytorch.org/).
The implementation is inspired from [Annotated Transformer](https://nlp.seas.harvard.edu/2018/04/03/attention.html)
"""

import math
from typing import Optional

import torch
from labml import tracker
from labml_helpers.module import Module
from torch import nn as nn
from torch.nn import functional as F


class PrepareForMultiHeadAttention(Module):
    """
    ## Prepare for multi-head attention

    This module does a linear transformation and splits the vector into given
    number of heads for multi-head attention.
    This is used to transform **key**, **query**, and **value** vectors.
    """

    def __init__(self, d_model: int, heads: int, d_k: int, bias: bool):
        super().__init__()
        # Linear layer for linear transform
        self.linear = nn.Linear(d_model, heads * d_k, bias=bias)
        # Number of heads
        self.heads = heads
        # Number of dimensions in vectors in each head
        self.d_k = d_k

    def __call__(self, x: torch.Tensor):
        # Input has shape `[seq_len, batch_size, d_model]`
        seq_len, batch_size, _ = x.shape

        # Linear transform
        x = self.linear(x)
        # Split into heads
        x = x.view(seq_len, batch_size, self.heads, self.d_k)

        # Output has shape `[seq_len, batch_size, heads, d_k]`
        return x


class MultiHeadAttention(Module):
    def __init__(self, heads: int, d_model: int, dropout_prob: float = 0.1, bias: bool = True):
        """
        ## Multi-Head Attention Module

        * `heads` is the number of heads.
        * `d_model` is the number of features in the `query`, `key` and `value` vectors.

        This computes scaled multi-headed attention for given `query`, `key` and `value` vectors.

        $$Attention(Q, K, V) = \\underset{seq}{softmax}\Bigg(\frac{Q K^T}{\sqrt{d_k}}\Bigg)V$$

        In simple terms, it finds keys that matches the query, and get the values of
         those keys.

        It uses dot-product of query and key as the indicator of how matching they are.
        Before taking the $softmax$ the dot-products are scaled by $\frac{1}{\sqrt{d_k}}$.
        This is done to avoid large dot-product values causing softmax to
        give very small gradients when $d_k$ is large.

        Softmax is calculate along the axis of of the sequence (or time).
        """

        super().__init__()
        self.d_k = d_model // heads
        self.heads = heads

        # These transform the `query`, `key` and `value` vectors for multi-headed attention.
        self.query = PrepareForMultiHeadAttention(d_model, heads, self.d_k, bias)
        self.key = PrepareForMultiHeadAttention(d_model, heads, self.d_k, bias)
        self.value = PrepareForMultiHeadAttention(d_model, heads, self.d_k, bias)

        # Output layer
        self.output = nn.Linear(d_model, d_model)
        # Dropout
        self.dropout = nn.Dropout(dropout_prob)
        # Scaling factor before the softmax
        self.scale = 1 / math.sqrt(self.d_k)

        # We store attentions so that it can used for logging, or other computations if needed
        self.attn = None

    def get_scores(self, query: torch.Tensor, key: torch.Tensor):
        """
        ### Calculate scores between queries and keys

        This method can be overridden for other variations like relative attention.
        """

        # Calculate $Q K^T$ or $S_{ijbh} = \sum_d Q_{ibhd} K_{jbhd}$
        return torch.einsum('ibhd,jbhd->ijbh', query, key)

    def __call__(self, *,
                 query: torch.Tensor,
                 key: torch.Tensor,
                 value: torch.Tensor,
                 mask: Optional[torch.Tensor] = None):
        """
        `query`, `key` and `value` are the tensors that store
        collection of*query*, *key* and *value* vectors.
        They have shape `[seq_len, batch_size, d_model]`.

        `mask` has shape `[seq_len, seq_len, batch_size]` and indicates
        `mask[i, j, b]` indicates whether for batch `b`,
        query at position `i` has access to key-value at position `j`.
        """

        # `query`, `key` and `value`  have shape `[seq_len, batch_size, d_model]`
        seq_len, batch_size, _ = query.shape

        if mask is not None:
            # `mask` has shape `[seq_len, seq_len, batch_size]`,
            # where first dimension is the query dimension.
            # If the query dimension is equal to $1$ it will be broadcasted
            assert mask.shape[0] == 1 or mask.shape[0] == mask.shape[1]

            # Same mask applied to all heads.
            mask = mask.unsqueeze(-1)

        # Prepare `query`, `key` and `value` for attention computation
        # These will then have shape `[seq_len, batch_size, heads, d_k]`
        query = self.query(query)
        key = self.key(key)
        value = self.value(value)

        # Compute attention scores $Q K^T$
        # Results in a tensor of shape `[seq_len, seq_len, batch_size, heads]`
        scores = self.get_scores(query, key)

        # Scale scores $\frac{Q K^T}{\sqrt{d_k}}$
        scores *= self.scale

        # Apply mask
        if mask is not None:
            scores = scores.masked_fill(mask == 0, -1e9)

        # $softmax$ attention along the key sequence dimension
        # $\underset{seq}{softmax}\Bigg(\frac{Q K^T}{\sqrt{d_k}}\Bigg)$$
        attn = F.softmax(scores, dim=1)

        # Save attentions if debugging
        tracker.debug('attn', attn)

        # Apply dropout
        attn = self.dropout(attn)

        # Multiply by values
        # $$\underset{seq}{softmax}\Bigg(\frac{Q K^T}{\sqrt{d_k}}\Bigg)V$$
        x = torch.einsum("ijbh,jbhd->ibhd", attn, value)

        # Save attentions for any other calculations 
        self.attn = attn.detach()

        # Concatenate multiple heads
        x = x.reshape(seq_len, batch_size, -1)

        # Output layer
        return self.output(x)
