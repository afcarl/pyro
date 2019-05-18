from __future__ import absolute_import, division, print_function

import os

import pytest
import torch
from six.moves import cPickle as pickle

import pyro.poutine as poutine
from pyro.contrib.tabular.features import Boolean, Discrete, Real
from pyro.contrib.tabular.treecat import TreeCat, TreeCatTrainer, _dm_log_prob, find_center_of_tree
from tests.common import TemporaryDirectory, assert_close


@pytest.mark.parametrize('expected_vertex,edges', [
    (0, []),
    (1, [(0, 1)]),
    (0, [(0, 1), (0, 2)]),
    (1, [(0, 1), (1, 2)]),
    (2, [(0, 2), (1, 2)]),
    (2, [(0, 1), (1, 2), (2, 3)]),
    (1, [(0, 1), (1, 2), (1, 3)]),
    (2, [(0, 1), (1, 2), (2, 3), (3, 4)]),
    (2, [(0, 2), (1, 2), (2, 3), (2, 4)]),
])
def test_find_center_of_tree(expected_vertex, edges):
    edges = torch.LongTensor(edges)
    v = find_center_of_tree(edges)
    assert v == expected_vertex


@pytest.mark.parametrize('alpha', [0.5, 0.1])
@pytest.mark.parametrize('counts_shape', [(6,), (5, 4), (4, 3, 2)])
def test_dm_log_prob(alpha, counts_shape):
    counts = torch.randn(counts_shape).exp()
    actual = _dm_log_prob(alpha, counts)
    expected = (alpha + counts).lgamma().sum(-1) - (1 + counts).lgamma().sum(-1)
    assert_close(actual, expected)


TINY_SCHEMA = [Boolean("f1"), Real("f2"), Discrete("f3", 3), Real("f4"), Boolean("f5")]
TINY_DATASETS = [
    [torch.tensor([0., 0., 1.]), None],
    [None, torch.tensor([-0.5, 0.5, 10.])],
    [None, None, torch.tensor([0, 1, 2, 2, 2], dtype=torch.long)],
    [torch.tensor([0., 0., 1.]), torch.tensor([-0.5, 0.5, 10.])],
    [torch.tensor([0., 0., 0., 1., 1.]),
     torch.tensor([-1.1, -1.0, -0.9, 0.9, 1.0]),
     torch.tensor([0, 1, 2, 2, 2], dtype=torch.long),
     torch.tensor([-2., -1., -0., 1., 2.]),
     torch.tensor([0., 1., 1., 1., 0.])],
]


@pytest.mark.parametrize('data', TINY_DATASETS)
@pytest.mark.parametrize('capacity', [2, 16])
def test_train_smoke(data, capacity):
    V = len(data)
    features = TINY_SCHEMA[:V]
    model = TreeCat(features, capacity)
    trainer = TreeCatTrainer(model)
    trainer.init(data)
    for i in range(10):
        trainer.step(data)


@pytest.mark.parametrize('capacity', [2, 16])
@pytest.mark.parametrize('data', TINY_DATASETS)
@pytest.mark.parametrize('num_samples', [None, 8])
def test_impute_smoke(data, capacity, num_samples):
    features = TINY_SCHEMA[:len(data)]
    model = TreeCat(features, capacity)
    model.impute(data, num_samples=num_samples)


@pytest.mark.parametrize('data', TINY_DATASETS)
@pytest.mark.parametrize('capacity', [2, 16])
def test_pickle(data, capacity):
    V = len(data)
    features = TINY_SCHEMA[:V]
    model = TreeCat(features, capacity)
    trainer = TreeCatTrainer(model)
    trainer.init(data)
    trainer.step(data)
    del trainer

    with TemporaryDirectory() as path:
        filename = os.path.join(path, "model.pkl")
        with open(filename, "wb") as f:
            pickle.dump(model, f, pickle.HIGHEST_PROTOCOL)
        with open(filename, "rb") as f:
            model2 = pickle.load(f)

    assert (model2.edges == model.edges).all()

    expected = poutine.trace(model.guide).get_trace(data)
    actual = poutine.trace(model2.guide).get_trace(data)
    assert expected.nodes.keys() == actual.nodes.keys()
    for key, expected_node in expected.nodes.items():
        if expected_node["type"] in ("param", "sample"):
            actual_node = actual.nodes[key]
            assert_close(expected_node["value"], actual_node["value"])