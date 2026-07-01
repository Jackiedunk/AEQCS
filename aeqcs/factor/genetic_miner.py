"""Deterministic genetic factor mining helpers."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

import pandas as pd

from aeqcs.core.versioning import assert_not_after, require_as_of

ExpressionOp = Literal["feature", "neg", "add", "sub", "mul", "div"]


@dataclass(frozen=True, slots=True)
class FactorExpression:
    op: ExpressionOp
    args: tuple["FactorExpression", ...] = ()
    feature: str | None = None

    @staticmethod
    def feature_ref(name: str) -> "FactorExpression":
        return FactorExpression("feature", feature=name)

    def render(self) -> str:
        if self.op == "feature":
            if self.feature is None:
                raise ValueError("feature expression missing feature name")
            return self.feature
        if self.op == "neg":
            return f"neg({self.args[0].render()})"
        return f"{self.op}({', '.join(arg.render() for arg in self.args)})"

    def complexity(self) -> int:
        return 1 + sum(arg.complexity() for arg in self.args)

    def evaluate(self, frame: pd.DataFrame) -> pd.Series:
        if self.op == "feature":
            if self.feature is None:
                raise ValueError("feature expression missing feature name")
            return frame[self.feature].astype(float)
        if self.op == "neg":
            return -self.args[0].evaluate(frame)
        left = self.args[0].evaluate(frame)
        right = self.args[1].evaluate(frame)
        if self.op == "add":
            return left + right
        if self.op == "sub":
            return left - right
        if self.op == "mul":
            return left * right
        if self.op == "div":
            denominator = right.where(right.abs() > 1e-12)
            return left / denominator
        raise ValueError(f"unsupported expression op: {self.op}")


@dataclass(frozen=True, slots=True)
class GeneticMinerConfig:
    seed: int = 0
    population_size: int = 32
    generations: int = 4
    top_k: int = 10
    max_depth: int = 3


@dataclass(frozen=True, slots=True)
class GeneticFactorCandidate:
    expression: FactorExpression
    score: float
    observations: int


def mine_genetic_factors(
    frame: pd.DataFrame,
    *,
    feature_columns: list[str],
    target_column: str,
    as_of_date: date | None,
    config: GeneticMinerConfig | None = None,
) -> list[GeneticFactorCandidate]:
    checked_as_of = require_as_of(as_of_date)
    if not isinstance(checked_as_of, date):
        raise ValueError("as_of_date must be a date")
    cfg = config or GeneticMinerConfig()
    _validate_config(cfg)
    if frame.empty or not feature_columns:
        return []
    _validate_columns(frame, feature_columns, target_column)
    scoped = frame.copy()
    scoped["date"] = pd.to_datetime(scoped["date"]).dt.date
    latest_date = cast(date, scoped["date"].max())
    assert_not_after(latest_date, checked_as_of)
    scoped = scoped[scoped["date"] <= checked_as_of].copy()
    if scoped.empty:
        return []

    rng = random.Random(cfg.seed)
    population = _initial_population(feature_columns, cfg, rng)
    for _ in range(cfg.generations):
        ranked = _rank_population(population, scoped, target_column)
        survivors = [candidate.expression for candidate in ranked[: max(1, cfg.population_size // 2)]]
        population = _next_generation(survivors, feature_columns, cfg, rng)
    return _rank_population(population, scoped, target_column)[: cfg.top_k]


def _validate_config(config: GeneticMinerConfig) -> None:
    if config.population_size <= 0:
        raise ValueError("population_size must be positive")
    if config.generations < 0:
        raise ValueError("generations cannot be negative")
    if config.top_k <= 0:
        raise ValueError("top_k must be positive")
    if config.max_depth <= 0:
        raise ValueError("max_depth must be positive")


def _validate_columns(frame: pd.DataFrame, feature_columns: list[str], target_column: str) -> None:
    required = {"date", target_column, *feature_columns}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"genetic mining frame missing columns: {sorted(missing)}")


def _initial_population(
    feature_columns: list[str],
    config: GeneticMinerConfig,
    rng: random.Random,
) -> list[FactorExpression]:
    features = [FactorExpression.feature_ref(name) for name in feature_columns]
    seeds = list(features)
    seeds.extend(FactorExpression("neg", (feature,)) for feature in features)
    for left in features:
        for right in features:
            if left == right:
                continue
            seeds.extend(
                [
                    FactorExpression("add", (left, right)),
                    FactorExpression("sub", (left, right)),
                    FactorExpression("mul", (left, right)),
                    FactorExpression("div", (left, right)),
                ]
            )
    population = _dedupe(seeds)
    while len(population) < config.population_size:
        population.append(_random_expression(feature_columns, config.max_depth, rng))
        population = _dedupe(population)
    return population[: config.population_size]


def _next_generation(
    survivors: list[FactorExpression],
    feature_columns: list[str],
    config: GeneticMinerConfig,
    rng: random.Random,
) -> list[FactorExpression]:
    population = list(survivors)
    while len(population) < config.population_size:
        if len(survivors) >= 2 and rng.random() < 0.5:
            left = rng.choice(survivors)
            right = rng.choice(survivors)
            population.append(_combine(left, right, rng))
        else:
            population.append(_mutate(rng.choice(survivors), feature_columns, config.max_depth, rng))
        population = _dedupe(population)
    return population[: config.population_size]


def _rank_population(
    population: list[FactorExpression],
    frame: pd.DataFrame,
    target_column: str,
) -> list[GeneticFactorCandidate]:
    candidates = [_score_expression(expression, frame, target_column) for expression in _dedupe(population)]
    return sorted(
        candidates,
        key=lambda candidate: (-candidate.score, candidate.expression.complexity(), candidate.expression.render()),
    )


def _score_expression(
    expression: FactorExpression,
    frame: pd.DataFrame,
    target_column: str,
) -> GeneticFactorCandidate:
    values = expression.evaluate(frame).rename("factor")
    target = frame[target_column].astype(float).rename("target")
    joined = pd.concat([values, target], axis=1).replace([math.inf, -math.inf], pd.NA).dropna()
    if len(joined) < 2:
        return GeneticFactorCandidate(expression=expression, score=0.0, observations=len(joined))
    if joined["factor"].nunique() < 2 or joined["target"].nunique() < 2:
        return GeneticFactorCandidate(expression=expression, score=0.0, observations=len(joined))
    score = joined["factor"].corr(joined["target"], method="spearman")
    if pd.isna(score):
        score = 0.0
    return GeneticFactorCandidate(
        expression=expression,
        score=round(abs(float(score)), 12),
        observations=len(joined),
    )


def _random_expression(
    feature_columns: list[str],
    depth: int,
    rng: random.Random,
) -> FactorExpression:
    if depth <= 1 or rng.random() < 0.35:
        return FactorExpression.feature_ref(rng.choice(feature_columns))
    op = rng.choice(["neg", "add", "sub", "mul", "div"])
    if op == "neg":
        return FactorExpression("neg", (_random_expression(feature_columns, depth - 1, rng),))
    return FactorExpression(
        cast(ExpressionOp, op),
        (
            _random_expression(feature_columns, depth - 1, rng),
            _random_expression(feature_columns, depth - 1, rng),
        ),
    )


def _mutate(
    expression: FactorExpression,
    feature_columns: list[str],
    max_depth: int,
    rng: random.Random,
) -> FactorExpression:
    if rng.random() < 0.5:
        return FactorExpression("neg", (expression,))
    return _combine(expression, _random_expression(feature_columns, max_depth, rng), rng)


def _combine(left: FactorExpression, right: FactorExpression, rng: random.Random) -> FactorExpression:
    return FactorExpression(cast(ExpressionOp, rng.choice(["add", "sub", "mul", "div"])), (left, right))


def _dedupe(expressions: list[FactorExpression]) -> list[FactorExpression]:
    deduped: dict[str, FactorExpression] = {}
    for expression in expressions:
        deduped.setdefault(expression.render(), expression)
    return list(deduped.values())
